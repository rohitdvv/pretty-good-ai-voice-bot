"""Central configuration for the Proctor MVP.

Reads from environment (.env) but every value has a safe default so the whole
system runs offline with zero external services for demos and tests.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
BASE_DIR = Path(__file__).parent.parent          # repo root
PACKAGE_DIR = Path(__file__).parent              # proctor/
DATA_DIR = PACKAGE_DIR / "data"
DB_PATH = Path(os.getenv("PROCTOR_DB", DATA_DIR / "proctor.db"))
WEB_DIR = PACKAGE_DIR / "web"
DATA_DIR.mkdir(exist_ok=True)

# --- Models ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEN_MODEL = os.getenv("PROCTOR_GEN_MODEL", "gpt-4o")        # persona generation
JUDGE_MODEL = os.getenv("PROCTOR_JUDGE_MODEL", "gpt-4o")    # evaluation
DEMO_BOT_MODEL = os.getenv("PROCTOR_DEMO_MODEL", "gpt-4o-mini")  # the built-in bot-under-test

# --- Engine mode ---
# "auto"   -> use the LLM if an API key is present, else fall back to offline/heuristic
# "offline"-> never call an LLM (deterministic; for tests, CI, and no-key demos)
# "live"   -> require the LLM (error if no key)
ENGINE_MODE = os.getenv("PROCTOR_MODE", "auto").lower()

# --- Scoring defaults (doc 04) ---
DEFAULT_PASS_THRESHOLD = float(os.getenv("PROCTOR_PASS_THRESHOLD", "0.7"))
SAFETY_REPEATS = int(os.getenv("PROCTOR_SAFETY_REPEATS", "5"))   # repeats for safety-critical personas
DEFAULT_REPEATS = int(os.getenv("PROCTOR_DEFAULT_REPEATS", "1"))
# Severity -> harm cost h_p (doc 04 §2 Safety Risk)
SEVERITY_COST = {"critical": 100.0, "high": 20.0, "medium": 5.0, "low": 1.0}
# Persona category -> importance weight W_p (doc 04 §2 Health)
CATEGORY_WEIGHT = {"adversarial": 5.0, "edge": 2.0, "variation": 1.5, "happy": 1.0}

# --- Run limits / safety (doc 06 consent + doc 07 limits) ---
MAX_CONCURRENCY = int(os.getenv("PROCTOR_MAX_CONCURRENCY", "5"))  # never DoS a customer's own bot
MAX_TURNS = int(os.getenv("PROCTOR_MAX_TURNS", "12"))            # cap a chat conversation length

# --- API / server ---
API_HOST = os.getenv("PROCTOR_HOST", "127.0.0.1")
# Cloud hosts (Render, Fly, Heroku, Cloud Run) inject $PORT; honor it, else PROCTOR_PORT, else 8080.
API_PORT = int(os.getenv("PROCTOR_PORT", os.getenv("PORT", "8080")))
# Optional shared API key. When set, every /api route except health requires header X-API-Key.
# The MVP binds to localhost by default; a network-exposed deployment MUST set this.
API_KEY = os.getenv("PROCTOR_API_KEY", "")

# --- Consent / verification (docs/06 §1) ---
# A one-time ownership code is normally delivered out-of-band (a call-back to the target). For LOCAL
# development only, set PROCTOR_DEV_ECHO_CODE=1 to return it in the API response so you can self-verify.
DEV_ECHO_CODE = os.getenv("PROCTOR_DEV_ECHO_CODE", "0") in ("1", "true", "True")
VERIFY_TTL_SECONDS = int(os.getenv("PROCTOR_VERIFY_TTL", "600"))   # code lifetime
VERIFY_MAX_ATTEMPTS = int(os.getenv("PROCTOR_VERIFY_MAX_ATTEMPTS", "5"))
VERIFY_MAX_ISSUES = int(os.getenv("PROCTOR_VERIFY_MAX_ISSUES", "5"))  # cap code reissues (anti-brute-force)
# Chat ownership is proven via an HTTP challenge (ACME HTTP-01 style): the owner hosts the issued
# code at this path on the target's own origin, proving they control that server.
VERIFY_WELL_KNOWN_PATH = "/.well-known/proctor-verify.txt"
DEMO_PROFILES = ("clinic", "support", "bank")


def llm_enabled() -> bool:
    """Whether we should make real LLM calls, per mode + key availability."""
    if ENGINE_MODE == "offline":
        return False
    if ENGINE_MODE == "live":
        return True
    return bool(OPENAI_API_KEY)  # auto
