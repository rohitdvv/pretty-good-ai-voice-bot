"""Thin LLM wrapper with a hard offline fallback.

Centralizes OpenAI access so the rest of the code never imports the SDK directly.
In offline mode (no key, or PROCTOR_MODE=offline) `chat_json`/`chat_text` raise
`OfflineError`, and every caller has a deterministic fallback path — so the whole
platform runs end-to-end with no external services for demos, tests, and CI.
"""

from __future__ import annotations

import json
import logging

from . import config

logger = logging.getLogger("proctor.llm")


class OfflineError(RuntimeError):
    """Raised when an LLM call is attempted but the engine is offline."""


_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def chat_text(system: str, user: str, model: str | None = None, temperature: float = 0.7) -> str:
    if not config.llm_enabled():
        raise OfflineError("LLM disabled (offline mode or no API key).")
    resp = _get_client().chat.completions.create(
        model=model or config.JUDGE_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def chat_json(system: str, user: str, model: str | None = None, temperature: float = 0.7) -> dict:
    if not config.llm_enabled():
        raise OfflineError("LLM disabled (offline mode or no API key).")
    resp = _get_client().chat.completions.create(
        model=model or config.JUDGE_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    return json.loads(resp.choices[0].message.content or "{}")


def chat_turns(system: str, turns: list[dict], model: str | None = None,
               temperature: float = 0.8) -> str:
    """Multi-turn completion (used by the built-in demo bot and chat personas)."""
    if not config.llm_enabled():
        raise OfflineError("LLM disabled (offline mode or no API key).")
    messages = [{"role": "system", "content": system}] + turns
    resp = _get_client().chat.completions.create(
        model=model or config.DEMO_BOT_MODEL, messages=messages, temperature=temperature,
    )
    return resp.choices[0].message.content or ""
