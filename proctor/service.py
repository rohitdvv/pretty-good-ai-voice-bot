"""Service facade — the use-case layer the API and CLI both call.

Keeps orchestration logic out of the transport layers (docs/02 'everything is an API':
the dashboard is just a client of these same operations).
"""

from __future__ import annotations

from . import config, consent, db
from .evaluator.rubric import compile_rubric
from .models import Suite, Target, _id
from .netguard import validate_external_url
from .personas import generate as generate_personas


def create_target(name: str, channel: str, endpoint: str, description: str = "") -> Target:
    if channel == "demo":
        # Demo targets are a fixed set of local, network-free profiles — never a URL.
        if endpoint not in config.DEMO_PROFILES:
            endpoint = "clinic"
    elif channel == "chat":
        # Block SSRF: a chat endpoint must be a public http(s) URL (docs/06).
        validate_external_url(endpoint)

    t = Target.new(name=name, channel=channel, endpoint=endpoint, description=description)
    if channel == "demo":
        t.consent_status = "verified"
        t.consent_method = "builtin_demo"       # local-only bot; no external action possible
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
