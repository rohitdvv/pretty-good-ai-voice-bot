"""Tests for the PR-review hardening fixes. Run: python tests/test_hardening.py

Covers: SSRF guard, single-use/expiring consent codes, and the fail-safe gate verdicts
(zero-scored runs and invalid baselines must BLOCK).
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Isolate the DB for this test run.
os.environ["PROCTOR_DB"] = tempfile.mktemp(suffix=".db")

from proctor import db, consent
from proctor.models import Rubric, Dimension, HardConstraint, Suite, Target, _id
from proctor.netguard import validate_external_url, UnsafeURLError
from proctor import reporting


def test_ssrf_guard():
    for bad in ["http://169.254.169.254/latest/meta-data/", "http://localhost:8080/",
                "http://127.0.0.1/", "ftp://example.com/", "http://10.0.0.5/", "not-a-url"]:
        try:
            validate_external_url(bad)
            assert False, f"should have blocked {bad}"
        except UnsafeURLError:
            pass
    # A public URL is allowed (DNS resolves to a public IP).
    assert validate_external_url("https://example.com/chat")


def test_consent_single_use_and_attempts():
    db.init()
    t = Target.new("t", "chat", "https://example.com/chat")
    db.save_target(t)
    code = consent.issue_verification(t)
    # Wrong code increments attempts, does not verify.
    assert consent.confirm_verification(t, "000000") is False
    assert t.consent_status == "unverified"
    # Correct code verifies and consumes the code.
    assert consent.confirm_verification(t, code) is True
    assert t.consent_status == "verified"
    assert t.verification_code == ""                 # single-use: consumed
    # Re-using the old code does nothing now.
    assert consent.confirm_verification(t, code) is False


def test_consent_attempt_lockout():
    db.init()
    t = Target.new("t2", "chat", "https://example.com/chat")
    db.save_target(t)
    code = consent.issue_verification(t)
    for _ in range(5):
        consent.confirm_verification(t, "999999")
    # After max attempts the code is invalidated; even the right code fails.
    assert consent.confirm_verification(t, code) is False
    assert t.consent_status == "unverified"


def _suite():
    return Suite(id=_id("suite"), name="s", description="a clinic bot", channel="demo",
                 personas=[], rubric=Rubric([Dimension("task_success", 1.0)], 0.7, []))


def test_zero_scored_blocks():
    rep = reporting.build_report("run_x", _suite(), results=[], gates={})
    assert rep["gate_verdict"] == "BLOCK"
    assert any("nothing was tested" in r for r in rep["gate_reasons"])


def test_missing_baseline_blocks():
    db.init()
    rep = reporting.build_report("run_y", _suite(), results=[],
                                 baseline_run_id="run_does_not_exist", gates={})
    assert rep["gate_verdict"] == "BLOCK"
    assert rep["regression"]["error"]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} hardening tests passed.")
