"""
FastAPI server that handles Twilio Media Streams webhooks.

When Twilio connects a call, it opens a WebSocket to this server.
This server bridges that audio to OpenAI's Realtime API, which drives
the patient-side conversation.
"""

import json
import base64
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response

from config import OPENAI_API_KEY, RECORDINGS_DIR, TRANSCRIPTS_DIR

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
app = FastAPI()

# Stores active call sessions so the caller module can set the persona
active_sessions: dict[str, dict] = {}


def _build_session_update(persona_prompt: str) -> dict:
    """Build the OpenAI Realtime API session.update message."""
    # Wrap the persona prompt with critical directives so the bot
    # behaves like a real patient and answers verification questions.
    wrapped_prompt = (
        "CRITICAL RULES — follow these at ALL times:\n"
        "1. You are calling a medical office as a patient. Act like a real human caller.\n"
        "2. ALWAYS answer the agent's questions DIRECTLY and IMMEDIATELY. "
        "When they ask for your date of birth, name, phone number, or any other info, "
        "provide it right away. NEVER deflect, ignore, or redirect their questions.\n"
        "3. Do NOT repeat yourself. If you already said something, do not say it again.\n"
        "4. Have a natural two-way conversation. Listen to what the agent says and respond appropriately.\n"
        "5. Keep responses short and natural — 1-2 sentences max, like a real phone call.\n"
        "6. Once your goal is accomplished (appointment booked, info received, etc.), "
        "say thank you and goodbye to end the call.\n\n"
        f"{persona_prompt}"
    )
    return {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": "alloy",
            "instructions": wrapped_prompt,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
        },
    }


@app.api_route("/call-status", methods=["POST"])
async def call_status(request: Request):
    """Receive call status updates from Twilio."""
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    logger.info(f"Call status update: {call_sid} -> {status}")
    if call_sid in active_sessions and status in ("completed", "failed", "busy", "no-answer"):
        active_sessions[call_sid]["status"] = "completed"
    return Response(content="OK", media_type="text/plain")


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml_webhook(request: Request):
    """Return TwiML that tells Twilio to stream audio to our WebSocket."""
    call_sid = ""
    if request.method == "POST":
        form = await request.form()
        call_sid = form.get("CallSid", "")

    # Get the host from the request to build the WebSocket URL
    host = request.headers.get("host", "localhost:8765")
    ws_url = f"wss://{host}/media-stream"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="callSid" value="{call_sid}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(twilio_ws: WebSocket):
    """Handle bidirectional audio streaming between Twilio and OpenAI Realtime."""
    await twilio_ws.accept()
    logger.info("Twilio WebSocket connected")

    call_sid = ""
    stream_sid = ""
    persona_prompt = "You are a patient calling a medical office. Be polite and cooperative."
    transcript_entries: list[dict] = []
    audio_chunks: list[bytes] = []  # raw ulaw from both sides for recording

    # Wait briefly for the call_sid to appear in active_sessions
    # (set by the caller module before the stream connects)
    await asyncio.sleep(0.5)

    openai_ws = None
    try:
        openai_ws = await websockets.connect(
            "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview",
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            },
        )
        logger.info("Connected to OpenAI Realtime API")

        async def receive_from_twilio():
            """Forward Twilio audio to OpenAI and collect raw audio for recording."""
            nonlocal call_sid, stream_sid, persona_prompt
            try:
                async for message in twilio_ws.iter_text():
                    data = json.loads(message)
                    event_type = data.get("event")

                    if event_type == "start":
                        start_data = data.get("start", {})
                        stream_sid = start_data.get("streamSid", "")
                        call_sid = start_data.get("callSid", "") or start_data.get(
                            "customParameters", {}
                        ).get("callSid", "")
                        logger.info(f"Stream started: stream={stream_sid} call={call_sid}")

                        # Look up persona for this call
                        session = active_sessions.get(call_sid, {})
                        persona_prompt = session.get("persona_prompt", persona_prompt)
                        logger.info(f"Using persona prompt for call {call_sid}")

                        # Send session config to OpenAI
                        await openai_ws.send(
                            json.dumps(_build_session_update(persona_prompt))
                        )
                        logger.info("Session config sent to OpenAI — waiting for agent to speak first")

                    elif event_type == "media":
                        payload = data["media"]["payload"]
                        audio_bytes = base64.b64decode(payload)
                        audio_chunks.append(audio_bytes)

                        # Forward to OpenAI
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": payload,
                                }
                            )
                        )

                    elif event_type == "stop":
                        logger.info("Twilio stream stopped")
                        # Close OpenAI WS so receive_from_openai() also exits
                        if openai_ws:
                            await openai_ws.close()
                        break
            except Exception as e:
                logger.error(f"Twilio receive error: {e}")

        async def receive_from_openai():
            """Forward OpenAI audio back to Twilio and capture transcript events."""
            nonlocal stream_sid
            try:
                async for message in openai_ws:
                    data = json.loads(message)
                    event_type = data.get("type", "")

                    # Log all event types for debugging (skip noisy deltas)
                    if "delta" not in event_type:
                        logger.debug(f"OpenAI event: {event_type}")

                    if event_type == "session.created":
                        logger.info("OpenAI session created")

                    elif event_type == "session.updated":
                        logger.info("OpenAI session updated successfully")

                    elif event_type == "response.audio.delta":
                        # Send audio back to Twilio
                        audio_delta = data.get("delta", "")
                        if audio_delta and stream_sid:
                            audio_bytes = base64.b64decode(audio_delta)
                            audio_chunks.append(audio_bytes)

                            await twilio_ws.send_json(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": audio_delta},
                                }
                            )

                    elif event_type == "response.audio_transcript.done":
                        text = data.get("transcript", "")
                        if text:
                            entry = {
                                "role": "bot",
                                "text": text,
                                "timestamp": datetime.now().isoformat(),
                            }
                            transcript_entries.append(entry)
                            # Save incrementally so main.py can read it even if
                            # the WebSocket hasn't closed yet
                            if call_sid and call_sid in active_sessions:
                                active_sessions[call_sid]["transcript"] = list(transcript_entries)
                            logger.info(f"Bot said: {text}")

                    elif event_type == "response.audio_transcript.delta":
                        pass  # Partial transcript, ignore

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        text = data.get("transcript", "")
                        if text:
                            entry = {
                                "role": "agent",
                                "text": text,
                                "timestamp": datetime.now().isoformat(),
                            }
                            transcript_entries.append(entry)
                            # Save incrementally
                            if call_sid and call_sid in active_sessions:
                                active_sessions[call_sid]["transcript"] = list(transcript_entries)
                            logger.info(f"Agent said: {text}")

                    elif event_type == "response.done":
                        resp = data.get("response", {})
                        status = resp.get("status", "unknown")
                        cancel_reason = resp.get("status_details", {})
                        output = resp.get("output", [])
                        logger.info(f"OpenAI response complete — status={status}, outputs={len(output)}, details={cancel_reason}")

                    elif event_type == "error":
                        logger.error(f"OpenAI error: {json.dumps(data, indent=2)}")

                    elif event_type not in (
                        "response.created",
                        "response.output_item.added",
                        "response.content_part.added",
                        "response.content_part.done",
                        "response.output_item.done",
                        "response.audio.done",
                        "conversation.item.created",
                        "conversation.item.input_audio_transcription.failed",
                        "conversation.item.input_audio_transcription.delta",
                        "input_audio_buffer.speech_started",
                        "input_audio_buffer.speech_stopped",
                        "input_audio_buffer.committed",
                        "rate_limits.updated",
                    ):
                        # Log any unexpected event types
                        logger.warning(f"Unhandled OpenAI event: {event_type} — {json.dumps(data)[:200]}")

            except Exception as e:
                logger.error(f"OpenAI receive error: {e}")

        # Run both receivers concurrently
        await asyncio.gather(receive_from_twilio(), receive_from_openai())

    except Exception as e:
        logger.error(f"WebSocket session error: {e}")
    finally:
        if openai_ws and not openai_ws.close_code:
            try:
                await openai_ws.close()
            except Exception:
                pass

        # Save transcript
        if transcript_entries and call_sid:
            _save_transcript(call_sid, transcript_entries)

        # Save raw audio
        if audio_chunks and call_sid:
            _save_raw_audio(call_sid, audio_chunks)

        # Update session status
        if call_sid in active_sessions:
            active_sessions[call_sid]["status"] = "completed"
            active_sessions[call_sid]["transcript"] = transcript_entries

        logger.info(f"Call {call_sid} finished — {len(transcript_entries)} transcript entries")


def _save_transcript(call_sid: str, entries: list[dict]):
    """Save transcript to a JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Use persona id if available
    session = active_sessions.get(call_sid, {})
    persona_id = session.get("persona_id", "unknown")
    filename = f"{persona_id}_{timestamp}.json"
    path = TRANSCRIPTS_DIR / filename
    path.write_text(json.dumps({"call_sid": call_sid, "entries": entries}, indent=2))
    logger.info(f"Transcript saved: {path}")

    # Also save a readable .txt version
    txt_path = path.with_suffix(".txt")
    lines = []
    for entry in entries:
        role = "Patient Bot" if entry["role"] == "bot" else "Office Agent"
        lines.append(f"[{role}]: {entry['text']}")
    txt_path.write_text("\n\n".join(lines))
    logger.info(f"Readable transcript saved: {txt_path}")

    if call_sid in active_sessions:
        active_sessions[call_sid]["transcript_path"] = str(txt_path)


def _save_raw_audio(call_sid: str, chunks: list[bytes]):
    """Save raw ulaw audio chunks. The caller module converts to MP3 later."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = active_sessions.get(call_sid, {})
    persona_id = session.get("persona_id", "unknown")
    filename = f"{persona_id}_{timestamp}.ulaw"
    path = RECORDINGS_DIR / filename
    path.write_bytes(b"".join(chunks))
    logger.info(f"Raw audio saved: {path}")

    if call_sid in active_sessions:
        active_sessions[call_sid]["audio_path"] = str(path)
