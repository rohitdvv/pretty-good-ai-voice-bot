"""Public REST API (docs/05 §3) + serves the dashboard.

The dashboard is just a client of these endpoints — 'everything is an API' (docs/02).
Runs execute in a background thread; clients poll GET /api/runs/{id}.
"""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, consent, db, service
from .models import Run, _id
from .orchestrator import execute_run

logger = logging.getLogger("proctor.api")

app = FastAPI(title="Proctor API", version="0.1.0")


@app.on_event("startup")
def _startup():
    db.init()


# --------------------------- request models --------------------------------- #
class TargetIn(BaseModel):
    name: str
    channel: str = "chat"      # demo | chat | voice
    endpoint: str = ""
    description: str = ""


class VerifyIn(BaseModel):
    code: str


class SuiteIn(BaseModel):
    description: str
    channel: str = "chat"
    count: int = 12
    spec: str = ""
    name: str = ""


class RunIn(BaseModel):
    suite_id: str
    target_id: str
    repeats: int = 0
    baseline_run_id: str = ""
    gates: dict = {}


class DemoIn(BaseModel):
    profile: str = "clinic"
    count: int = 10


# --------------------------- run execution ---------------------------------- #
def _execute_async(run: Run):
    def _go():
        try:
            execute_run(run)
        except Exception as e:                 # record failure on the run, don't crash the server
            logger.exception("Run %s failed", run.id)
            run.status = "failed"
            run.report = {"error": str(e), "gate_verdict": "BLOCK", "gate_reasons": [str(e)]}
            db.save_run(run)
    threading.Thread(target=_go, daemon=True).start()


# --------------------------- endpoints -------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok", "mode": config.ENGINE_MODE, "llm": config.llm_enabled(),
            "version": "0.1.0"}


@app.post("/api/targets")
def create_target(body: TargetIn):
    t = service.create_target(body.name, body.channel, body.endpoint, body.description)
    return t.__dict__


@app.get("/api/targets")
def list_targets():
    return [t.__dict__ for t in db.list_targets()]


@app.post("/api/targets/{target_id}/verify/issue")
def issue_verify(target_id: str):
    t = db.get_target(target_id)
    if not t:
        raise HTTPException(404, "target not found")
    code = consent.issue_verification(t)
    # In production the code is delivered by calling the target; echoed here for the MVP demo.
    return {"issued": True, "code": code, "note": "Echo this code back to verify ownership."}


@app.post("/api/targets/{target_id}/verify")
def confirm_verify(target_id: str, body: VerifyIn):
    t = db.get_target(target_id)
    if not t:
        raise HTTPException(404, "target not found")
    ok = consent.confirm_verification(t, body.code)
    if not ok:
        raise HTTPException(400, "code did not match")
    return {"verified": True}


@app.post("/api/suites/generate")
def generate_suite(body: SuiteIn):
    s = service.generate_suite(body.description, channel=body.channel, count=body.count,
                               spec=body.spec, name=body.name)
    return {"id": s.id, "name": s.name, "channel": s.channel, "description": s.description,
            "personas": [p.__dict__ for p in s.personas], "rubric": s.rubric.to_dict()}


@app.get("/api/suites")
def list_suites():
    return [{"id": s.id, "name": s.name, "channel": s.channel, "description": s.description,
             "personas": len(s.personas)} for s in db.list_suites()]


@app.get("/api/suites/{suite_id}")
def get_suite(suite_id: str):
    s = db.get_suite(suite_id)
    if not s:
        raise HTTPException(404, "suite not found")
    return {"id": s.id, "name": s.name, "channel": s.channel, "description": s.description,
            "personas": [p.__dict__ for p in s.personas], "rubric": s.rubric.to_dict()}


@app.post("/api/runs")
def create_run(body: RunIn):
    if not db.get_suite(body.suite_id):
        raise HTTPException(404, "suite not found")
    target = db.get_target(body.target_id)
    if not target:
        raise HTTPException(404, "target not found")
    try:
        consent.ensure_consent(target)
    except consent.ConsentError as e:
        raise HTTPException(403, str(e))
    run = Run(id=_id("run"), suite_id=body.suite_id, target_id=body.target_id,
              repeats_override=body.repeats, baseline_run_id=body.baseline_run_id, gates=body.gates)
    db.save_run(run)
    _execute_async(run)
    return {"id": run.id, "status": run.status}


@app.get("/api/runs")
def list_runs():
    return [{"id": r.id, "suite_id": r.suite_id, "target_id": r.target_id, "status": r.status,
             "created_at": r.created_at,
             "verdict": (r.report or {}).get("gate_verdict"),
             "health": (r.report or {}).get("health_score")} for r in db.list_runs()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return {"id": r.id, "status": r.status, "suite_id": r.suite_id, "target_id": r.target_id,
            "baseline_run_id": r.baseline_run_id, "report": r.report}


@app.get("/api/runs/{run_id}/conversations")
def get_conversations(run_id: str):
    out = []
    results = {res.conversation_id: res for res in db.list_results(run_id)}
    for cv in db.list_conversations(run_id):
        res = results.get(cv.id)
        out.append({
            "id": cv.id, "persona_id": cv.persona_id, "repeat": cv.repeat_index,
            "status": cv.status, "error": cv.error,
            "transcript": [{"role": t.role, "text": t.text} for t in cv.transcript],
            "result": None if not res else {
                "score": res.score, "passed": res.passed,
                "dimension_scores": res.dimension_scores,
                "hard_violations": res.hard_violations, "critical": res.critical_violated,
                "evidence": [e.__dict__ for e in res.evidence], "judges": res.judges,
            },
        })
    return out


@app.post("/api/demo")
def start_demo(body: DemoIn):
    descs = {
        "clinic": "An AI phone receptionist for a family medical clinic that books, reschedules and "
                  "cancels appointments, answers hours/location questions, and must triage urgent "
                  "symptoms by advising 911/ER. Office hours Mon-Fri 8am-5pm.",
        "support": "A SaaS support chatbot handling billing, password resets and plan questions.",
        "bank": "A bank phone assistant for card disputes and fraud that must verify identity before "
                "disclosing or changing account information.",
    }
    profile = body.profile if body.profile in descs else "clinic"
    desc = descs[profile]
    target = service.create_target(f"Demo {profile} bot", "demo", profile, desc)
    suite = service.generate_suite(desc, channel="demo", count=body.count)
    run = Run(id=_id("run"), suite_id=suite.id, target_id=target.id)
    db.save_run(run)
    _execute_async(run)
    return {"run_id": run.id, "target_id": target.id, "suite_id": suite.id, "status": run.status}


# --------------------------- dashboard -------------------------------------- #
@app.get("/")
def index():
    return FileResponse(str(config.WEB_DIR / "index.html"))


try:
    app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")
except Exception:
    pass
