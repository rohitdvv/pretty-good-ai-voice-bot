"""Core domain entities (docs/05 data model), as dataclasses.

These are the in-memory shapes; db.py handles persistence to SQLite. IDs are
short prefixed strings (tgt_, suite_, run_, conv_) like the public API.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# Target (the bot under test) + consent (docs/06 §1)
# --------------------------------------------------------------------------- #
@dataclass
class Target:
    id: str
    name: str
    channel: str                 # "voice" | "chat" | "demo"
    endpoint: str                # phone number (voice) or URL (chat) or demo key
    description: str = ""         # what the bot is supposed to do (drives generation + rubric)
    consent_status: str = "unverified"   # "unverified" | "verified"
    consent_method: str = ""      # how ownership was proven
    verification_code: str = ""   # one-time code for the call-back/echo check
    created_at: float = field(default_factory=now)

    @staticmethod
    def new(name: str, channel: str, endpoint: str, description: str = "") -> "Target":
        return Target(id=_id("tgt"), name=name, channel=channel, endpoint=endpoint,
                      description=description)


# --------------------------------------------------------------------------- #
# Suite = personas + rubric (docs/05 §2), immutable+versioned by id
# --------------------------------------------------------------------------- #
@dataclass
class Dimension:
    key: str
    weight: float


@dataclass
class HardConstraint:
    id: str
    severity: str                # "critical" | "high" | "medium" | "low"
    rule: str                    # natural-language MUST/MUST-NOT the judge checks


@dataclass
class Rubric:
    dimensions: list[Dimension]
    pass_threshold: float
    hard_constraints: list[HardConstraint]

    def to_dict(self) -> dict:
        return {
            "dimensions": [asdict(d) for d in self.dimensions],
            "pass_threshold": self.pass_threshold,
            "hard_constraints": [asdict(c) for c in self.hard_constraints],
        }

    @staticmethod
    def from_dict(d: dict) -> "Rubric":
        return Rubric(
            dimensions=[Dimension(**x) for x in d["dimensions"]],
            pass_threshold=d.get("pass_threshold", 0.7),
            hard_constraints=[HardConstraint(**x) for x in d.get("hard_constraints", [])],
        )


@dataclass
class Persona:
    id: str
    name: str
    scenario: str
    description: str
    system_prompt: str
    goal: str
    edge_cases_to_probe: list[str] = field(default_factory=list)
    expected_duration_seconds: int = 120
    category: str = "happy"      # happy | variation | edge | adversarial
    weight: float = 1.0          # importance W_p (doc 04 §2)

    @staticmethod
    def from_dict(d: dict) -> "Persona":
        known = {f for f in Persona.__dataclass_fields__}
        return Persona(**{k: v for k, v in d.items() if k in known})


@dataclass
class Suite:
    id: str
    name: str
    description: str             # the bot description used to generate it
    channel: str
    personas: list[Persona]
    rubric: Rubric
    created_at: float = field(default_factory=now)


# --------------------------------------------------------------------------- #
# Run / Conversation / Results (docs/05 §2)
# --------------------------------------------------------------------------- #
@dataclass
class Turn:
    role: str                    # "agent" (bot under test) | "user" (synthetic persona)
    text: str
    t_ms: int = 0                # offset in the conversation


@dataclass
class Conversation:
    id: str
    run_id: str
    persona_id: str
    repeat_index: int
    transcript: list[Turn] = field(default_factory=list)
    status: str = "pending"      # pending | completed | errored
    error: str = ""
    audio_path: str = ""


@dataclass
class Evidence:
    constraint: str
    severity: str
    transcript_span: list[int]   # [start_turn, end_turn]
    judge_reasoning: str


@dataclass
class ScoredResult:
    conversation_id: str
    persona_id: str
    score: float
    passed: bool
    dimension_scores: dict[str, float]
    hard_violations: list[str]   # ids of violated constraints
    critical_violated: bool
    evidence: list[Evidence] = field(default_factory=list)
    judges: list[str] = field(default_factory=list)
    judge_agreement: float = 1.0


@dataclass
class Run:
    id: str
    suite_id: str
    target_id: str
    repeats_override: int = 0    # 0 => use per-persona tiering
    baseline_run_id: str = ""
    gates: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"       # queued | running | completed | failed | errored
    created_at: float = field(default_factory=now)
    report: dict | None = None   # filled by reporting.py
