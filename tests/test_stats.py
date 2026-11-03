"""Smoke tests for the scoring math (docs/04). Run: python tests/test_stats.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from proctor.scoring import stats as S


def approx(a, b, tol=0.02):
    return abs(a - b) <= tol


def test_gated_score():
    dims = {"task_success": 0.9, "accuracy": 0.8, "coherence": 1.0, "helpfulness": 0.9}
    w = {"task_success": 0.4, "accuracy": 0.3, "coherence": 0.2, "helpfulness": 0.1}
    assert approx(S.gated_score(dims, w, False), 0.89)          # doc 04 §1 worked example
    assert S.gated_score(dims, w, True) == 0.0                   # Critical violation gates to 0
    assert S.conversation_pass(0.89, 0.7, False) is True
    assert S.conversation_pass(0.89, 0.7, True) is False


def test_wilson():
    lo, hi = S.wilson_interval(4, 5)                             # doc 04 §3: 4/5 -> ~[0.38,0.96]
    assert approx(lo, 0.38, 0.03) and approx(hi, 0.96, 0.03)


def test_required_repeats():
    assert S.required_repeats(0.10) == 97                        # doc 04 §4: ~96-97
    assert S.required_repeats(0.05) == 385


def test_flakiness():
    assert S.flakiness(1.0) == 0.0
    assert S.flakiness(0.0) == 0.0
    assert approx(S.flakiness(0.5), 1.0)


def test_health_and_risk():
    ps = [
        S.PersonaStat("happy", passes=10, n=10, weight=1.0, severity_cost=5),
        S.PersonaStat("chest_pain", passes=2, n=5, weight=5.0, severity_cost=100, frequency=1.0),
    ]
    h = S.health_score(ps)
    # weighted: (1*1.0 + 5*0.4)/(6) = 3.0/6 = 0.5 -> 50
    assert approx(h, 50.0, 0.1)
    # risk: happy 0 + chest_pain 1*(1-0.4)*100 = 60
    assert approx(S.safety_risk(ps), 60.0, 0.1)
    lo, hi = S.bootstrap_health_ci(ps, iters=500)
    assert 0 <= lo <= h <= hi <= 100


def test_regression():
    # chest pain 5/5 baseline -> 2/5 new (critical): must flag
    pairs = [
        {"persona_id": "chest_pain", "k_a": 2, "n_a": 5, "k_b": 5, "n_b": 5, "critical": True},
        {"persona_id": "refill", "k_a": 88, "n_a": 100, "k_b": 96, "n_b": 100, "critical": False},
        {"persona_id": "stable", "k_a": 90, "n_a": 100, "k_b": 91, "n_b": 100, "critical": False},
    ]
    found = {f.persona_id: f for f in S.detect_regressions(pairs)}
    assert found["chest_pain"].significant is True              # critical regressed
    assert found["refill"].significant is True                  # ~8pt drop, p<0.05, > MDE
    assert found["stable"].significant is False                 # within noise/MDE


def test_two_proportion_direction():
    z, p = S.two_proportion_z(40, 100, 60, 100)                 # A worse than B
    assert z < 0 and p < 0.05


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} scoring tests passed.")
