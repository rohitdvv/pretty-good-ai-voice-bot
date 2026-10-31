"""Consent & ownership gate (docs/06 §1) — the hard precondition for any run.

MVP implements the *mechanism* (a verification record that the orchestrator enforces).
Real deployments plug in the call-back-code / DNS-TXT / signed-authorization methods.
The built-in 'demo' channel is auto-verified because it is Proctor's own local bot.

Codes are single-use, time-limited, and attempt-limited (docs/06): a leaked or stale
code cannot silently re-verify a target.
"""

from __future__ import annotations

import secrets

from . import config, db
from .models import Target, now


class ConsentError(RuntimeError):
    """Raised when a run is attempted against a target without valid consent."""


def issue_verification(target: Target) -> str:
    """Create a one-time code the customer must echo back to prove control of the target."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    target.verification_code = code
    target.verification_attempts = 0
    target.verification_expires_at = now() + config.VERIFY_TTL_SECONDS
    target.consent_status = "unverified"
    db.save_target(target)
    return code


def confirm_verification(target: Target, code: str, method: str = "callback_code") -> bool:
    """Mark the target verified iff the echoed code matches, is unexpired, and attempts remain.

    On success the code is consumed (cleared) so it cannot be reused; on repeated failure the
    code is invalidated to stop brute-forcing.
    """
    if not target.verification_code:
        return False
    if target.verification_expires_at and now() > target.verification_expires_at:
        _invalidate(target)
        return False
    if target.verification_attempts >= config.VERIFY_MAX_ATTEMPTS:
        _invalidate(target)
        return False

    if secrets.compare_digest(code.strip(), target.verification_code):
        target.consent_status = "verified"
        target.consent_method = method
        target.verification_code = ""            # single-use: consume it
        target.verification_expires_at = 0.0
        target.verification_attempts = 0
        db.save_target(target)
        return True

    target.verification_attempts += 1
    if target.verification_attempts >= config.VERIFY_MAX_ATTEMPTS:
        _invalidate(target)
    else:
        db.save_target(target)
    return False


def _invalidate(target: Target) -> None:
    target.verification_code = ""
    target.verification_expires_at = 0.0
    db.save_target(target)


def ensure_consent(target: Target) -> None:
    """Hard gate used by the orchestrator. Demo targets are implicitly authorized (local only)."""
    if target.channel == "demo":
        return
    if target.consent_status != "verified":
        raise ConsentError(
            f"Target {target.id} ({target.endpoint}) is not verified. Verify ownership before "
            f"testing it (docs/06 §1)."
        )
