"""Consent & ownership gate (docs/06 §1) — the hard precondition for any run.

MVP implements the *mechanism* (a verification record that the orchestrator enforces).
Real deployments plug in the call-back-code / DNS-TXT / signed-authorization methods.
The built-in 'demo' channel is auto-verified because it is Proctor's own bot.
"""

from __future__ import annotations

import random

from . import db
from .models import Target


class ConsentError(RuntimeError):
    """Raised when a run is attempted against a target without valid consent."""


def issue_verification(target: Target) -> str:
    """Create a one-time code the customer must echo back to prove control of the target."""
    code = f"{random.randint(0, 999999):06d}"
    target.verification_code = code
    target.consent_status = "unverified"
    db.save_target(target)
    return code


def confirm_verification(target: Target, code: str, method: str = "callback_code") -> bool:
    """Mark the target verified if the echoed code matches."""
    if target.verification_code and code.strip() == target.verification_code:
        target.consent_status = "verified"
        target.consent_method = method
        db.save_target(target)
        return True
    return False


def ensure_consent(target: Target) -> None:
    """Hard gate used by the orchestrator. Demo targets are implicitly authorized."""
    if target.channel == "demo":
        return
    if target.consent_status != "verified":
        raise ConsentError(
            f"Target {target.id} ({target.endpoint}) is not verified. Verify ownership before "
            f"testing it (docs/06 §1)."
        )
