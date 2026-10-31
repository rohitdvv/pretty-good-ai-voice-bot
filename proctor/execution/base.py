"""Adapter interfaces (docs/03 §2 'pluggable target adapters').

A TargetAdapter is the bot under test; a SyntheticUser is the persona driving it.
New channels = new TargetAdapter implementations, not new architecture.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Turn


class TargetAdapter(Protocol):
    """The customer's bot under test."""

    def greeting(self) -> str | None:
        """Optional opening line the agent says first (e.g. a receptionist greeting)."""
        ...

    def respond(self, history: list[Turn]) -> str:
        """Given the conversation so far, return the agent's next utterance."""
        ...

    def close(self) -> None:
        ...


class SyntheticUser(Protocol):
    """The persona playing a realistic user."""

    def respond(self, history: list[Turn]) -> tuple[str, bool]:
        """Return (utterance, done). done=True means the user ends the conversation."""
        ...
