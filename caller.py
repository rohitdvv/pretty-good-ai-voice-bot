"""
Outbound call manager — uses Twilio to place calls and connects them to our server.

Also handles:
- Converting raw ulaw recordings to MP3
- Downloading Twilio's dual-channel recording as a backup
"""

import time
import logging
import subprocess
from pathlib import Path

from twilio.rest import Client

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    TARGET_PHONE_NUMBER,
    PUBLIC_URL,
    RECORDINGS_DIR,
)
from server import active_sessions

logger = logging.getLogger(__name__)


def get_twilio_client() -> Client:
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def place_call(persona_id: str, persona_prompt: str) -> str:
    """
    Place an outbound call to the target number.

    Returns the Twilio CallSid which is used to track the session.
    """
    client = get_twilio_client()
    twiml_url = f"{PUBLIC_URL}/twiml"

    logger.info(f"Placing call with persona '{persona_id}' to {TARGET_PHONE_NUMBER}")
    logger.info(f"TwiML URL: {twiml_url}")

    call = client.calls.create(
        to=TARGET_PHONE_NUMBER,
        from_=TWILIO_PHONE_NUMBER,
        url=twiml_url,
        record=True,  # Twilio records the full call as a backup
        recording_channels="dual",
        status_callback=f"{PUBLIC_URL}/call-status",
        status_callback_event=["completed"],
    )

    call_sid = call.sid
    logger.info(f"Call placed: {call_sid}")

    # Register the session so the WebSocket handler picks up the persona
    active_sessions[call_sid] = {
        "persona_id": persona_id,
        "persona_prompt": persona_prompt,
        "status": "in_progress",
        "transcript": [],
        "transcript_path": None,
        "audio_path": None,
    }

    return call_sid


def wait_for_call_completion(call_sid: str, timeout: int = 300) -> dict:
    """Poll until the call session completes or times out."""
    start = time.time()
    while time.time() - start < timeout:
        session = active_sessions.get(call_sid, {})
        if session.get("status") == "completed":
            logger.info(f"Call {call_sid} completed")
            # Wait a bit longer for the WebSocket handler to finish saving
            # transcript and audio data after the call-status webhook fires.
            logger.info("Waiting for transcript data to finalize...")
            time.sleep(8)
            session = active_sessions.get(call_sid, {})
            transcript = session.get("transcript", [])
            # If still no transcript, wait a bit more (WebSocket might still be closing)
            if not transcript:
                logger.info("Transcript not yet available, waiting a bit more...")
                time.sleep(10)
                session = active_sessions.get(call_sid, {})
            logger.info(f"Transcript entries available: {len(session.get('transcript', []))}")
            return session
        time.sleep(2)
    logger.warning(f"Call {call_sid} timed out after {timeout}s")
    return active_sessions.get(call_sid, {})


def convert_ulaw_to_mp3(ulaw_path: str) -> str | None:
    """Convert raw ulaw audio file to MP3 using ffmpeg."""
    ulaw = Path(ulaw_path)
    if not ulaw.exists():
        logger.warning(f"Audio file not found: {ulaw_path}")
        return None

    mp3_path = ulaw.with_suffix(".mp3")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "mulaw",
                "-ar", "8000",
                "-ac", "1",
                "-i", str(ulaw),
                "-ar", "44100",
                "-ac", "1",
                str(mp3_path),
            ],
            check=True,
            capture_output=True,
        )
        logger.info(f"Converted to MP3: {mp3_path}")
        return str(mp3_path)
    except FileNotFoundError:
        logger.error("ffmpeg not found — install it to convert recordings to MP3")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg conversion failed: {e.stderr.decode()}")
        return None


def download_twilio_recording(call_sid: str) -> str | None:
    """Download the Twilio-hosted recording for a call as an MP3 backup."""
    client = get_twilio_client()
    try:
        recordings = client.recordings.list(call_sid=call_sid)
        if not recordings:
            logger.info(f"No Twilio recording found for {call_sid}")
            return None

        recording = recordings[0]
        uri = f"https://api.twilio.com{recording.uri.replace('.json', '.mp3')}"

        import requests
        resp = requests.get(uri, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        resp.raise_for_status()

        session = active_sessions.get(call_sid, {})
        persona_id = session.get("persona_id", "unknown")
        filename = f"{persona_id}_{call_sid}_twilio.mp3"
        path = RECORDINGS_DIR / filename
        path.write_bytes(resp.content)
        logger.info(f"Twilio recording downloaded: {path}")
        return str(path)
    except Exception as e:
        logger.error(f"Failed to download Twilio recording: {e}")
        return None
