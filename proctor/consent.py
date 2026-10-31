"""Consent & ownership gate (docs/06 §1) — the hard precondition for any run.

MVP implements the *mechanism* (a verification record that the orchestrator enforces).
Real deployments plug in the call-back-code / DNS-TXT / signed-authorization methods.
The built-in 'demo' channel is auto-verified because it is Proctor's own local bot.

Codes are single-use, time-limited, and attempt-limited (docs/06): a leaked or stale
code cannot silently re-verify a target.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse, urlunparse

from . import config, db
from .models import Target, now
from .netguard import UnsafeURLError, validate_external_url

logger = logging.getLogger("proctor.consent")


class ConsentError(RuntimeError):
    """Raised when a run is attempted against a target without valid consent."""


def issue_verification(target: Target) -> str:
    """Issue a one-time ownership code.

    Reissues are capped (VERIFY_MAX_ISSUES) so a caller cannot renew guessing attempts
    indefinitely against an unverified target.
    """
    if target.verification_issues >= config.VERIFY_MAX_ISSUES:
        raise ConsentError(
            f"Verification code reissue limit ({config.VERIFY_MAX_ISSUES}) reached for this target.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    target.verification_code = code
    target.verification_attempts = 0
    target.verification_issues += 1
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


def well_known_url(endpoint: str) -> str:
    """The origin-rooted URL where a chat target's owner must host the challenge code."""
    p = urlparse(endpoint)
    return urlunparse((p.scheme, p.netloc, config.VERIFY_WELL_KNOWN_PATH, "", "", ""))


def verify_by_http(target: Target, method: str = "http_challenge") -> bool:
    """Prove ownership of a chat target by fetching the issued code from its own origin.

    ACME HTTP-01 style: the owner hosts the code at /.well-known/proctor-verify.txt on the
    target's server. Only someone who controls that server can satisfy this — echoing the code
    back is not enough. Redirects are disabled so the proof can't be bounced elsewhere.
    """
    import requests
    if not target.verification_code:
        return False
    if target.verification_expires_at and now() > target.verification_expires_at:
        _invalidate(target)
        return False
    url = well_known_url(target.endpoint)
    try:
        validate_external_url(url)                 # SSRF guard on the challenge URL too
        r = requests.get(url, timeout=15, allow_redirects=False)
    except (UnsafeURLError, requests.RequestException) as e:
        logger.info("HTTP challenge fetch failed for %s: %s", target.id, e)
        return False
    if r.status_code == 200 and target.verification_code in r.text:
        target.consent_status = "verified"
        target.consent_method = method
        target.verification_code = ""              # consume
        target.verification_expires_at = 0.0
        target.verification_attempts = 0
        db.save_target(target)
        return True
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
