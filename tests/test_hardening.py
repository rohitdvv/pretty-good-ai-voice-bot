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

from proctor import db, consent, config, reporting
from proctor.models import Rubric, Dimension, HardConstraint, Suite, Target, _id
from proctor.netguard import validate_external_url, UnsafeURLError
from proctor.personas import generate as gen_personas
from proctor.execution.synthetic import ScriptedSyntheticUser


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
    # Echo verification is for callback (voice) targets; chat must use the HTTP challenge.
    db.init()
    t = Target.new("t", "voice", "+15551230000")
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


def test_chat_echo_rejected():
    # A chat target can never be verified by echoing the code (prevents CLI bypass of the challenge).
    db.init()
    t = Target.new("tc", "chat", "https://example.com/chat")
    db.save_target(t)
    code = consent.issue_verification(t)
    assert consent.confirm_verification(t, code) is False
    assert t.consent_status == "unverified"


def test_consent_attempt_lockout():
    db.init()
    t = Target.new("t2", "voice", "+15551230001")
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


def test_reissue_cooldown_not_permanent_lockout():
    db.init()
    t = Target.new("t3", "voice", "+15551230002")
    db.save_target(t)
    consent.issue_verification(t)
    # An immediate reissue is throttled by the cooldown...
    try:
        consent.issue_verification(t)
        assert False, "immediate reissue should be throttled"
    except consent.ConsentError:
        pass
    # ...but once the cooldown elapses, a new code can be issued (no permanent lockout).
    t.verification_last_issued_at = 0.0
    assert consent.issue_verification(t)             # succeeds, returns a code


def test_offline_medical_suite_not_all_emergency():
    # A medical suite must not turn every persona into a chest-pain call (bug: description leaked
    # into the per-persona emergency trigger).
    _, personas = gen_personas("A medical clinic booking assistant handling appointments and symptoms",
                               count=6, channel="demo")
    first_lines = [ScriptedSyntheticUser(p).lines[0].lower() for p in personas]
    emergency = [l for l in first_lines if "chest pain" in l]
    assert 0 < len(emergency) < len(first_lines), "exactly the emergency persona(s) should voice chest pain"


def test_decompress_bounded():
    import zlib
    from proctor.netguard import _decompress_bounded
    payload = b'{"reply":"hello"}'
    # raw (headerless) DEFLATE
    raw_deflate = (lambda d: d.compress(payload) + d.flush())(zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS))
    assert _decompress_bounded(raw_deflate, "deflate", 1000) == payload
    # zlib-wrapped deflate
    assert _decompress_bounded(zlib.compress(payload), "deflate", 1000) == payload
    # multi-member gzip (two concatenated members)
    def gz(b):
        c = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS); return c.compress(b) + c.flush()
    multi = gz(b'{"rep') + gz(b'ly":"hello"}')
    assert _decompress_bounded(multi, "gzip", 1000) == payload
    # gzip bomb is bounded to the limit
    big = (lambda c: c.compress(b"A" * 5_000_000) + c.flush())(zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS))
    assert len(_decompress_bounded(big, "gzip", 100)) == 100


def test_legacy_target_row_loads():
    # An older DB row containing a since-removed field must still load (forward-compat).
    import json as _j
    import sqlite3
    from proctor.config import DB_PATH
    db.init()
    data = {"id": "tgt_legacy", "name": "old", "channel": "chat",
            "endpoint": "https://example.com/chat", "description": "", "consent_status": "verified",
            "consent_method": "x", "verification_code": "", "verification_attempts": 0,
            "verification_issues": 3, "verification_expires_at": 0.0, "created_at": 0}
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO targets VALUES (?,?,?)", ("tgt_legacy", _j.dumps(data), 0))
    con.commit(); con.close()
    t = db.get_target("tgt_legacy")
    assert t is not None and t.consent_status == "verified"


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
