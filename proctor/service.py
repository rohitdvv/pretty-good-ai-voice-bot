"""Service facade — the use-case layer the API and CLI both call.

Keeps orchestration logic out of the transport layers (docs/02 'everything is an API':
the dashboard is just a client of these same operations).
"""

from __future__ import annotations

from . import consent, db
from .evaluator.rubric import compile_rubric
from .models import Suite, Target, _id
from .personas import generate as generate_personas


def create_target(name: str, channel: str, endpoint: str, description: str = "") -> Target:
    t = Target.new(name=name, channel=channel, endpoint=endpoint, description=description)
    if channel == "demo":
        t.consent_status = "verified"
        t.consent_method = "builtin_demo"
    db.save_target(t)
    return t


def generate_suite(description: str, channel: str = "chat", count: int = 12,
                   spec: str = "", name: str = "") -> Suite:
    suite_name, personas = generate_personas(description, count=count, channel=channel)
    rubric = compile_rubric(description, spec=spec)
    suite = Suite(id=_id("suite"), name=name or suite_name, description=description,
                  channel=channel, personas=personas, rubric=rubric)
    db.save_suite(suite)
    return suite
