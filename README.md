# Pretty Good AI — Voice Bot Tester

An automated voice bot that calls a medical office AI agent, simulates realistic patient conversations, records everything, and identifies bugs.

## Architecture

The system has four layers:

1. **Telephony (Twilio)** — Places outbound calls and streams bidirectional audio via WebSocket Media Streams. Twilio also records the full call as a backup.

2. **Conversation Engine (OpenAI Realtime API)** — Receives the office agent's audio, generates patient responses in real-time using GPT-4o's voice capabilities. Each call uses a different "patient persona" (system prompt) that defines the patient's personality, scenario, and goals.

3. **Webhook Server (FastAPI)** — Bridges Twilio's audio stream to OpenAI's Realtime API. Captures transcripts from both sides and saves raw audio for MP3 conversion.

4. **Bug Detector (GPT-4o)** — Post-call analysis of each transcript. Looks for logic errors (e.g., booking on closed days), safety issues (e.g., not triaging chest pain), dropped context, and hallucinations. Generates structured bug reports with severity ratings.

**Why these choices?** Twilio is the most reliable telephony API with excellent WebSocket streaming support. OpenAI's Realtime API provides natural, low-latency voice conversations — critical since the #1 evaluation criterion is coherent voice interaction. FastAPI handles async WebSocket traffic efficiently. Using GPT-4o for post-call analysis (separate from the voice model) gives deeper, more structured bug detection than trying to detect issues during the call.

## Prerequisites

- **Python 3.11+**
- **ffmpeg** (for audio conversion): `brew install ffmpeg`
- **ngrok** (for public webhooks): `brew install ngrok`
- **Twilio account** with a phone number ([twilio.com](https://www.twilio.com))
- **OpenAI API key** with access to the Realtime API ([platform.openai.com](https://platform.openai.com))

## Setup

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd pretty-good-ai-voice-bot

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual credentials

# 5. Start ngrok tunnel (in a separate terminal)
ngrok http 8765
# Copy the https URL (e.g., https://abc123.ngrok-free.app)
# Paste it as PUBLIC_URL in your .env file
```

## Running

```bash
# List all available patient personas
python main.py --list

# Run a single persona
python main.py --persona scheduling_simple

# Run multiple specific personas
python main.py --persona scheduling_simple weekend_appointment urgent_care

# Run ALL personas (12 calls)
python main.py --all

# Run all with custom delay between calls
python main.py --all --delay 30
```

## Patient Personas

| ID | Scenario | Tests |
|---|---|---|
| `scheduling_simple` | New patient books checkup | Basic scheduling flow |
| `scheduling_reschedule` | Reschedule existing appointment | Appointment lookup + change |
| `scheduling_cancel` | Cancel and transfer records | Cancellation handling |
| `medication_refill` | Refill blood pressure meds | Medication name handling |
| `office_hours_question` | Ask about hours/location/insurance | Information accuracy |
| `weekend_appointment` | Request Sunday appointment | Office hour validation |
| `vague_symptoms` | Rambling, confused patient | Ambiguity handling |
| `urgent_care` | Chest pain symptoms | Emergency triage |
| `spanish_speaker` | Mixed Spanish/English | Language accommodation |
| `multiple_requests` | 3 requests in one call | Multi-task handling |
| `interrupt_test` | Frequent interruptions | Conversation resilience |
| `after_hours` | 6:30 AM / 8 PM appointment | Time boundary validation |

## Output

After each run, you'll find:

- **`recordings/`** — MP3 audio files of each call
- **`transcripts/`** — JSON and readable .txt transcripts
- **`reports/`** — Individual bug reports (JSON) and a summary report (Markdown)

## Bug Detection Strategy

The bug detector automatically checks for:

- **Logic errors** — Confirming appointments when the office is closed
- **Safety failures** — Not recognizing urgent symptoms like chest pain
- **Information accuracy** — Wrong office hours, locations, or insurance info
- **Context retention** — Forgetting patient info mid-conversation
- **Completeness** — Missing one of multiple patient requests
- **Hallucinations** — Making up doctors, times, or policies
- **Conversation quality** — Handling interruptions, language barriers, vague requests

Each bug is rated Critical/High/Medium/Low with details on what happened and what should have happened.

## Environment Variables

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number (E.164 format) |
| `OPENAI_API_KEY` | OpenAI API key |
| `PUBLIC_URL` | Public URL from ngrok |
| `SERVER_PORT` | Webhook server port (default: 8765) |
