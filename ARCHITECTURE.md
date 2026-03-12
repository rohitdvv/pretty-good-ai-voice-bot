# Architecture

## System Overview

Pretty Good AI Voice Bot Tester is a four-layer automated testing system that calls a medical office AI agent, simulates realistic patient conversations, and identifies bugs through post-call analysis.

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (Orchestrator)                │
│         CLI · Sequencing · Report Generation            │
└──────────┬──────────────┬───────────────┬───────────────┘
           │              │               │
           ▼              ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  caller.py   │  │  server.py   │  │ bug_detector.py  │
│   Telephony  │  │  WebSocket   │  │  Post-Call       │
│   (Twilio)   │◄─┤  Bridge      │  │  Analysis        │
│              │  │  (FastAPI)   │  │  (GPT-4o)        │
└──────┬───────┘  └──────┬───────┘  └──────────────────┘
       │                 │
       ▼                 ▼
   Twilio API    OpenAI Realtime API
```

## The Four Layers

### 1. Telephony — Twilio

Twilio places outbound calls to the target medical office number and opens a bidirectional WebSocket Media Stream for real-time audio. It also records each call server-side as an MP3 backup.

**Why Twilio?** It's the most mature telephony API with first-class WebSocket streaming support. The Media Streams feature lets us intercept raw audio in real time rather than waiting for a post-call recording, which is essential for driving a live conversation. Twilio's dual-channel recording also gives us a reliable backup if our local audio capture has issues.

### 2. Conversation Engine — OpenAI Realtime API

The OpenAI Realtime API (`gpt-4o-mini-realtime-preview`) receives the office agent's speech and generates patient responses as streaming audio. Each call loads a different patient persona — a system prompt that defines the patient's name, date of birth, medical scenario, and conversational goals.

**Why OpenAI Realtime?** It's the only production API that supports true voice-to-voice conversation with sub-second latency. Traditional speech-to-text → LLM → text-to-speech pipelines add 2-4 seconds of delay per turn, which makes phone conversations feel robotic and causes the office agent to time out or talk over the bot. The Realtime API handles VAD (voice activity detection), turn-taking, and interruptions natively — all critical for testing a phone-based AI agent.

### 3. Webhook Server — FastAPI

A FastAPI server acts as the bridge between Twilio and OpenAI. When Twilio connects a call, it opens a WebSocket to our `/media-stream` endpoint. The server:

1. Receives the Twilio `start` event and looks up the persona for this call
2. Opens a second WebSocket to OpenAI's Realtime API
3. Configures the OpenAI session with the persona prompt, audio format (g711 ulaw), and transcription settings
4. Forwards incoming audio from Twilio → OpenAI and response audio from OpenAI → Twilio
5. Captures transcript events from both sides (office agent via input transcription, patient bot via output transcription)
6. Saves transcripts (JSON + readable TXT) and raw audio when the call ends

**Why FastAPI?** It has native async/await support and handles WebSocket connections efficiently. Since we're managing two concurrent WebSocket connections per call (Twilio + OpenAI), async is essential — a synchronous framework would block on one connection while the other has data waiting. FastAPI's lightweight design also means minimal overhead on the audio path.

### 4. Bug Detector — GPT-4o (Chat API)

After each call, the full transcript is sent to GPT-4o's chat completions API for structured analysis. The detector checks for seven categories of bugs:

- **Incorrect information** — wrong clinic names, office hours, doctor names
- **Logic errors** — booking appointments on closed days, impossible dates
- **Safety failures** — not triaging urgent symptoms like chest pain
- **Dropped context** — forgetting patient info mid-conversation, asking for details already provided
- **Incomplete handling** — not resolving the patient's request, dead-end transfers
- **Hallucinations** — inventing doctors, policies, or appointment times
- **Conversation quality** — language switches, handling interruptions, managing vague requests

Each bug gets a severity rating (Critical/High/Medium/Low), the specific exchange where it occurred, and a description of what went wrong versus what should have happened.

**Why a separate model for analysis?** Using the voice model for real-time bug detection would degrade conversation quality — the bot needs to stay in character as a patient. Post-call analysis with GPT-4o (the full chat model, not the mini variant) gives deeper, more structured results because it can review the entire conversation with hindsight and cross-reference earlier exchanges against later ones.

## Key Design Decisions

### Persona-Driven Testing

Rather than scripting exact dialogue trees, each test case is a persona — a system prompt that gives the bot a personality, medical scenario, and goals. This lets the bot have natural conversations that adapt to whatever the office agent says, which surfaces bugs that scripted tests would miss. The 12 personas cover scheduling, cancellations, medication refills, urgent care, language barriers, interruptions, and edge cases like after-hours and weekend calls.

### Shared State via `active_sessions`

The `active_sessions` dictionary in `server.py` is the central coordination point between modules. When `caller.py` places a call, it registers the persona in `active_sessions` keyed by CallSid. When the WebSocket handler starts, it looks up the persona from this dict. Transcripts are saved incrementally to `active_sessions` as they arrive, so `main.py` can access them even before the WebSocket fully closes. This avoids race conditions where the orchestrator tries to read transcripts before they're written to disk.

### Audio Format: g711 ulaw

Twilio's Media Streams send audio in g711 ulaw format at 8kHz mono. Rather than transcoding on the fly (which adds latency), we configure OpenAI to accept and output the same format. The raw ulaw is saved locally, and Twilio's server-side MP3 recording serves as the primary audio deliverable.

### Wrapped System Prompts

The raw persona prompts define the patient scenario, but they're wrapped with critical behavioral rules before being sent to OpenAI: always answer verification questions directly, keep responses to 1-2 sentences, don't repeat yourself, and end the call when the goal is met. This wrapper was essential — without it, the bot would deflect the office agent's identity verification questions (name, DOB, phone) and get stuck in loops.

## Data Flow for a Single Call

```
1. main.py loads persona JSON
2. caller.py → Twilio API: create call to target number
3. Twilio connects → HTTP POST to /twiml
4. Server returns TwiML with WebSocket stream URL
5. Twilio opens WebSocket to /media-stream
6. Server opens WebSocket to OpenAI Realtime API
7. Server sends session.update with wrapped persona prompt
8. Office agent speaks → Twilio streams audio → Server → OpenAI
9. OpenAI generates patient response → Server → Twilio → Office agent hears it
10. Transcript events captured from both directions
11. Call ends → transcripts saved to disk (JSON + TXT)
12. caller.py downloads Twilio MP3 recording
13. bug_detector.py analyzes transcript with GPT-4o
14. Bug report saved as JSON; summary report as Markdown
```
