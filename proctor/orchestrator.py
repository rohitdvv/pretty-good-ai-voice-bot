"""Run Orchestrator (docs/03 §1) — the brain of a run.

Expands a suite into persona×repeat jobs with tiered repeats, enforces the consent
gate and bounded concurrency, executes conversations, scores them, aggregates a report,
and persists everything. The MVP's thread pool stands in for the distributed worker
fleet; the control flow is identical.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, consent, db, reporting
from .evaluator.judge import JudgeError, score_conversation
from .execution.runner import run_conversation
from .models import Run, ScoredResult, Suite, Target, _id

logger = logging.getLogger("proctor.orchestrator")


def _repeats_for(persona, suite: Suite, override: int) -> int:
    """Tiered repeats (docs/04 §4): safety-critical personas run more; happy-path run few."""
    if override and override > 0:
        return override
    if persona.category == "adversarial":
        return config.SAFETY_REPEATS
    if persona.category == "edge":
        return max(config.DEFAULT_REPEATS, 2)
    return config.DEFAULT_REPEATS


def execute_run(run: Run) -> Run:
    """Execute a queued run to completion and attach its report. Persists as it goes."""
    suite = db.get_suite(run.suite_id)
    target = db.get_target(run.target_id)
    if suite is None or target is None:
        run.status = "failed"
        db.save_run(run)
        raise ValueError("Run references a missing suite or target.")

    # HARD consent gate (docs/06 §1) — nothing executes without it.
    consent.ensure_consent(target)

    run.status = "running"
    db.save_run(run)

    # Expand jobs: persona × repeats.
    jobs = []
    for persona in suite.personas:
        n = _repeats_for(persona, suite, run.repeats_override)
        for i in range(n):
            jobs.append((persona, i))

    logger.info("Run %s: %d personas -> %d conversations (concurrency=%d, mode=%s)",
                run.id, len(suite.personas), len(jobs),
                min(config.MAX_CONCURRENCY, len(jobs) or 1), config.ENGINE_MODE)

    results: list[ScoredResult] = []

    def _one(job):
        persona, idx = job
        cv = run_conversation(run.id, persona, target.channel, target.endpoint, idx)
        if cv.status != "completed":
            db.save_conversation(cv)
            return None  # errored call != bot failure; excluded from scoring (docs/03 §1)
        try:
            res = score_conversation(cv, suite.rubric, suite.description or target.description)
        except JudgeError as e:
            # The judge could not evaluate this conversation — exclude it rather than pass it.
            cv.status = "errored"
            cv.error = str(e)
            db.save_conversation(cv)
            return None
        db.save_conversation(cv)
        db.save_result(run.id, res)
        return res

    concurrency = max(1, min(config.MAX_CONCURRENCY, len(jobs) or 1))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_one, j) for j in jobs]
        for f in as_completed(futures):
            r = f.result()
            if r is not None:
                results.append(r)

    report = reporting.build_report(
        run.id, suite, results,
        baseline_run_id=run.baseline_run_id, gates=run.gates, target_id=run.target_id,
    )
    run.report = report
    run.status = "completed"
    db.save_run(run)
    logger.info("Run %s complete: health=%.1f risk=%.1f verdict=%s",
                run.id, report["health_score"], report["safety_risk"], report["gate_verdict"])
    return run


# --- high-level convenience used by API/CLI ---------------------------------
def create_and_execute_run(suite_id: str, target_id: str, repeats_override: int = 0,
                           baseline_run_id: str = "", gates: dict | None = None) -> Run:
    run = Run(id=_id("run"),
              suite_id=suite_id, target_id=target_id, repeats_override=repeats_override,
              baseline_run_id=baseline_run_id, gates=gates or {})
    db.save_run(run)
    return execute_run(run)
