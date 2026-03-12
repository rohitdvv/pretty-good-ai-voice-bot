"""Configuration management — loads environment variables and provides app-wide settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Twilio ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")  # Your Twilio number in E.164

# --- OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# --- Target ---
TARGET_PHONE_NUMBER = "+18054398008"

# --- Paths ---
BASE_DIR = Path(__file__).parent
PERSONAS_DIR = BASE_DIR / "personas"
RECORDINGS_DIR = BASE_DIR / "recordings"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
REPORTS_DIR = BASE_DIR / "reports"

# Ensure output dirs exist
for d in [RECORDINGS_DIR, TRANSCRIPTS_DIR, REPORTS_DIR]:
    d.mkdir(exist_ok=True)

# --- Server ---
SERVER_PORT = int(os.getenv("SERVER_PORT", "8765"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "")  # ngrok or similar public URL
