"""SQLite persistence (docs/05 data lifecycle).

Deliberately simple: one table per entity, payload stored as JSON. This mirrors
the OLTP store in docs/02 and swaps cleanly for Postgres later. All access goes
through this module so the storage engine is a single seam.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .models import (
    Conversation, Persona, Rubric, Run, ScoredResult, Suite, Target, Turn, Evidence,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS targets   (id TEXT PRIMARY KEY, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS suites    (id TEXT PRIMARY KEY, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS runs      (id TEXT PRIMARY KEY, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS convos    (id TEXT PRIMARY KEY, run_id TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS results   (conversation_id TEXT PRIMARY KEY, run_id TEXT, data TEXT);
"""


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


# --- serialization helpers ---------------------------------------------------
def _suite_to_json(s: Suite) -> str:
    return json.dumps({
        "id": s.id, "name": s.name, "description": s.description, "channel": s.channel,
        "created_at": s.created_at,
        "personas": [asdict(p) for p in s.personas],
        "rubric": s.rubric.to_dict(),
    })


def _suite_from_json(txt: str) -> Suite:
    d = json.loads(txt)
    return Suite(
        id=d["id"], name=d["name"], description=d["description"], channel=d["channel"],
        created_at=d.get("created_at", 0),
        personas=[Persona.from_dict(p) for p in d["personas"]],
        rubric=Rubric.from_dict(d["rubric"]),
    )


def _convo_from_json(txt: str) -> Conversation:
    d = json.loads(txt)
    d["transcript"] = [Turn(**t) for t in d.get("transcript", [])]
    return Conversation(**d)


def _result_from_json(txt: str) -> ScoredResult:
    d = json.loads(txt)
    d["evidence"] = [Evidence(**e) for e in d.get("evidence", [])]
    return ScoredResult(**d)


# --- Targets -----------------------------------------------------------------
def save_target(t: Target) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO targets VALUES (?,?,?)",
                  (t.id, json.dumps(asdict(t)), t.created_at))


def get_target(tid: str) -> Target | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM targets WHERE id=?", (tid,)).fetchone()
    return Target(**json.loads(row["data"])) if row else None


def list_targets() -> list[Target]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM targets ORDER BY created_at DESC").fetchall()
    return [Target(**json.loads(r["data"])) for r in rows]


# --- Suites ------------------------------------------------------------------
def save_suite(s: Suite) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO suites VALUES (?,?,?)",
                  (s.id, _suite_to_json(s), s.created_at))


def get_suite(sid: str) -> Suite | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM suites WHERE id=?", (sid,)).fetchone()
    return _suite_from_json(row["data"]) if row else None


def list_suites() -> list[Suite]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM suites ORDER BY created_at DESC").fetchall()
    return [_suite_from_json(r["data"]) for r in rows]


# --- Runs --------------------------------------------------------------------
def save_run(r: Run) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?)",
                  (r.id, json.dumps(asdict(r)), r.created_at))


def get_run(rid: str) -> Run | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM runs WHERE id=?", (rid,)).fetchone()
    return Run(**json.loads(row["data"])) if row else None


def list_runs() -> list[Run]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM runs ORDER BY created_at DESC").fetchall()
    return [Run(**json.loads(r["data"])) for r in rows]


# --- Conversations & results -------------------------------------------------
def save_conversation(cv: Conversation) -> None:
    d = asdict(cv)
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO convos VALUES (?,?,?)",
                  (cv.id, cv.run_id, json.dumps(d)))


def list_conversations(run_id: str) -> list[Conversation]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM convos WHERE run_id=?", (run_id,)).fetchall()
    return [_convo_from_json(r["data"]) for r in rows]


def save_result(run_id: str, res: ScoredResult) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO results VALUES (?,?,?)",
                  (res.conversation_id, run_id, json.dumps(asdict(res))))


def list_results(run_id: str) -> list[ScoredResult]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM results WHERE run_id=?", (run_id,)).fetchall()
    return [_result_from_json(r["data"]) for r in rows]
