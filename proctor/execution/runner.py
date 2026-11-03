"""Conversation runner — executes ONE conversation (persona × repeat) turn-by-turn.

Maps to a single Conversation Worker job in docs/03 §2. Produces a Conversation with
a full dual-role transcript, ready for the judge.
"""

from __future__ import annotations

import logging

from .. import config
from ..models import Conversation, Persona, Turn, _id
from .base import SyntheticUser, TargetAdapter
from .synthetic import make_synthetic_user
from .targets import make_target

logger = logging.getLogger("proctor.runner")


def run_conversation(run_id: str, persona: Persona, channel: str, endpoint: str,
                     repeat_index: int = 0) -> Conversation:
    """Drive a persona against a target until the user ends it or MAX_TURNS is hit."""
    cv = Conversation(id=_id("conv"), run_id=run_id, persona_id=persona.id,
                      repeat_index=repeat_index)
    try:
        target: TargetAdapter = make_target(channel, endpoint)
        user: SyntheticUser = make_synthetic_user(persona)

        history: list[Turn] = []
        t_ms = 0

        # Agent may greet first (receptionist-style).
        greeting = target.greeting()
        if greeting:
            history.append(Turn(role="agent", text=greeting, t_ms=t_ms))
            t_ms += 3000

        for _turn in range(config.MAX_TURNS):
            # User speaks.
            user_text, done = user.respond(history)
            if user_text:
                history.append(Turn(role="user", text=user_text, t_ms=t_ms))
                t_ms += 3000
            if done:
                break
            # Agent responds.
            agent_text = target.respond(history)
            history.append(Turn(role="agent", text=agent_text, t_ms=t_ms))
            t_ms += 3000

        target.close()
        cv.transcript = history
        cv.status = "completed"
    except NotImplementedError as e:
        cv.status = "errored"
        cv.error = str(e)
    except Exception as e:                      # a failed call != the bot failing (docs/03 §1)
        logger.warning("Conversation errored for persona %s: %s", persona.id, e)
        cv.status = "errored"
        cv.error = str(e)
    return cv
