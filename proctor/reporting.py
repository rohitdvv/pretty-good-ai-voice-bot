"""Reporting & aggregation (docs/03 §5, docs/04 §2–5) — turn scored results into a Report.

Computes Bot Health, Safety Risk, confidence intervals, flakiness, a regression diff
vs. a baseline run, and a single CI gate verdict.
"""

from __future__ import annotations

from collections import defaultdict

from . import config, db
from .models import Persona, ScoredResult, Suite
from .scoring import stats as S

_SEV_BY_CATEGORY = {"adversarial": "critical", "edge": "high", "variation": "medium", "happy": "low"}


def _persona_severity_cost(persona: Persona, results: list[ScoredResult]) -> float:
    """h_p = worst severity actually observed for this persona, else a category default."""
    worst = 0.0
    for r in results:
        for v in r.evidence:
            worst = max(worst, config.SEVERITY_COST.get(v.severity, 0.0))
    if worst > 0:
        return worst
    return config.SEVERITY_COST[_SEV_BY_CATEGORY.get(persona.category, "low")]


def _persona_stats(suite: Suite, results: list[ScoredResult]) -> list[S.PersonaStat]:
    by_persona: dict[str, list[ScoredResult]] = defaultdict(list)
    for r in results:
        by_persona[r.persona_id].append(r)
    pmap = {p.id: p for p in suite.personas}
    stats = []
    for pid, rs in by_persona.items():
        persona = pmap.get(pid)
        if persona is None:
            continue
        passes = sum(1 for r in rs if r.passed)
        stats.append(S.PersonaStat(
            persona_id=pid, passes=passes, n=len(rs),
            weight=persona.weight,
            severity_cost=_persona_severity_cost(persona, rs),
        ))
    return stats


def build_report(run_id: str, suite: Suite, results: list[ScoredResult],
                 baseline_run_id: str = "", gates: dict | None = None) -> dict:
    gates = gates or {}
    pstats = _persona_stats(suite, results)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    overall_ci = S.wilson_interval(passed, total)

    health = S.health_score(pstats)
    health_ci = S.bootstrap_health_ci(pstats)
    risk = S.safety_risk(pstats)
    risk_tail = S.risk_tail(pstats, alpha=0.1)

    # Per-dimension mean scores across all conversations.
    dim_keys = [d.key for d in suite.rubric.dimensions]
    dim_summary = {}
    for k in dim_keys:
        vals = [r.dimension_scores.get(k, 0.0) for r in results]
        dim_summary[k] = round(sum(vals) / len(vals), 3) if vals else 0.0

    # Per-persona table (for the dashboard).
    pmap = {p.id: p for p in suite.personas}
    persona_rows = []
    for ps in pstats:
        lo, hi = ps.ci
        p = pmap[ps.persona_id]
        persona_rows.append({
            "persona_id": ps.persona_id, "scenario": p.scenario, "category": p.category,
            "passes": ps.passes, "n": ps.n, "pass_rate": round(ps.pass_rate, 3),
            "ci": [round(lo, 3), round(hi, 3)], "flakiness": round(S.flakiness(ps.pass_rate), 3),
            "weight": ps.weight,
        })
    persona_rows.sort(key=lambda r: (r["pass_rate"], -r["weight"]))

    flaky = [r["persona_id"] for r in persona_rows if r["flakiness"] >= 0.5]

    # Critical failures with evidence.
    critical_failures = []
    for r in results:
        if r.critical_violated:
            critical_failures.append({
                "persona_id": r.persona_id, "conversation_id": r.conversation_id,
                "violations": r.hard_violations,
                "evidence": [{"constraint": e.constraint, "severity": e.severity,
                              "span": e.transcript_span, "reasoning": e.judge_reasoning}
                             for e in r.evidence],
            })

    report = {
        "run_id": run_id, "suite_id": suite.id,
        "conversations": total, "passed": passed,
        "overall_pass_rate": round(passed / total, 3) if total else 0.0,
        "overall_pass_ci": [round(overall_ci[0], 3), round(overall_ci[1], 3)],
        "health_score": round(health, 1), "health_ci": [round(health_ci[0], 1), round(health_ci[1], 1)],
        "safety_risk": round(risk, 1), "risk_tail_10pct": round(risk_tail, 1),
        "dimension_summary": dim_summary,
        "flaky_personas": flaky,
        "critical_failures": critical_failures,
        "personas": persona_rows,
        "regression": None,
        "gate_verdict": "PASS",
        "gate_reasons": [],
    }

    if baseline_run_id:
        report["regression"] = _regression_diff(run_id, baseline_run_id, suite, results)

    _apply_gates(report, gates)
    return report


def _regression_diff(run_id: str, baseline_run_id: str, suite: Suite,
                     new_results: list[ScoredResult]) -> dict:
    base_results = db.list_results(baseline_run_id)
    base_stats = {ps.persona_id: ps for ps in _persona_stats(suite, base_results)}
    new_stats = {ps.persona_id: ps for ps in _persona_stats(suite, new_results)}
    pmap = {p.id: p for p in suite.personas}

    pairs = []
    for pid, ns in new_stats.items():
        bs = base_stats.get(pid)
        if not bs:
            continue
        persona = pmap.get(pid)
        critical = bool(persona and persona.category == "adversarial")
        pairs.append({"persona_id": pid, "k_a": ns.passes, "n_a": ns.n,
                      "k_b": bs.passes, "n_b": bs.n, "critical": critical})

    findings = S.detect_regressions(pairs)
    regressed = [{
        "persona_id": f.persona_id, "baseline_rate": round(f.baseline_rate, 3),
        "new_rate": round(f.new_rate, 3), "z": round(f.z, 2),
        "p_value": round(f.p_value, 4), "critical": f.critical,
    } for f in findings if f.significant]

    return {"baseline_run_id": baseline_run_id, "regressed": regressed,
            "n_compared": len(pairs)}


def _apply_gates(report: dict, gates: dict) -> None:
    """Evaluate configurable gates into a single CI verdict (docs/04 §5)."""
    reasons: list[str] = []

    # Default hard gate: any Critical failure in the run blocks.
    if gates.get("block_on_critical", True) and report["critical_failures"]:
        reasons.append(f"{len(report['critical_failures'])} critical safety failure(s) observed")

    min_health = gates.get("min_health")
    if min_health is not None and report["health_score"] < min_health:
        reasons.append(f"health {report['health_score']} < gate {min_health}")

    max_risk = gates.get("max_safety_risk")
    if max_risk is not None and report["safety_risk"] > max_risk:
        reasons.append(f"safety risk {report['safety_risk']} > gate {max_risk}")

    reg = report.get("regression")
    if reg and gates.get("block_on_regression", True):
        crit_reg = [r for r in reg["regressed"] if r["critical"]]
        if crit_reg:
            reasons.append(f"{len(crit_reg)} critical persona(s) regressed vs baseline")
        elif reg["regressed"]:
            reasons.append(f"{len(reg['regressed'])} persona(s) regressed vs baseline")

    report["gate_reasons"] = reasons
    report["gate_verdict"] = "BLOCK" if reasons else "PASS"
