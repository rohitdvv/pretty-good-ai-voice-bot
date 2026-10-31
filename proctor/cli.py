"""Proctor CLI — the full loop from a terminal, plus the CI/CD regression gate (docs/05 §3).

Examples:
  # Zero-setup demo against the built-in flawed clinic bot (no phone, no keys needed):
  python -m proctor.cli demo

  # Real flow:
  python -m proctor.cli targets add --name "My Bot" --channel chat --endpoint https://.../chat
  python -m proctor.cli targets verify <target_id> --issue
  python -m proctor.cli targets verify <target_id> --code 123456
  python -m proctor.cli suites generate --description "..." --channel chat --count 12
  python -m proctor.cli run --suite <suite_id> --target <target_id>
  python -m proctor.cli report <run_id>

  # CI gate (exits non-zero on BLOCK):
  python -m proctor.cli gate --suite <suite_id> --target <target_id> --baseline <run_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config, consent, db, service
from .orchestrator import create_and_execute_run


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _print_report(report: dict, verbose: bool = False):
    print("\n" + "=" * 64)
    print(f"RUN {report['run_id']}  —  verdict: {report['gate_verdict']}")
    print("=" * 64)
    print(f"Health score:   {report['health_score']}  CI {report['health_ci']}")
    print(f"Safety risk:    {report['safety_risk']}  (tail10% {report['risk_tail_10pct']})")
    print(f"Pass rate:      {report['overall_pass_rate']}  CI {report['overall_pass_ci']}  "
          f"({report['passed']}/{report['conversations']})")
    print(f"Dimensions:     {report['dimension_summary']}")
    if report["flaky_personas"]:
        print(f"Flaky personas: {', '.join(report['flaky_personas'])}")
    if report["critical_failures"]:
        print(f"\n⚠  CRITICAL FAILURES ({len(report['critical_failures'])}):")
        for cf in report["critical_failures"]:
            print(f"   - {cf['persona_id']}: {', '.join(cf['violations'])}")
            for e in cf["evidence"]:
                print(f"       [{e['severity']}] {e['constraint']}: {e['reasoning'][:90]}")
    if report.get("regression"):
        reg = report["regression"]
        print(f"\nRegression vs {reg['baseline_run_id']}: {len(reg['regressed'])} regressed "
              f"of {reg['n_compared']} compared")
        for r in reg["regressed"]:
            tag = "CRIT" if r["critical"] else "    "
            print(f"   {tag} {r['persona_id']}: {r['baseline_rate']} -> {r['new_rate']} (p={r['p_value']})")
    if report["gate_reasons"]:
        print(f"\nGate reasons: {'; '.join(report['gate_reasons'])}")
    if verbose:
        print("\nPer-persona:")
        for p in report["personas"]:
            print(f"   {p['pass_rate']:.2f}  {p['category']:<11} {p['persona_id']:<30} "
                  f"CI{p['ci']} n={p['n']}")
    print("=" * 64 + "\n")


def cmd_demo(args):
    """Zero-setup end-to-end demo against the built-in flawed bot."""
    db.init()
    print(f"\nProctor demo (engine mode: {config.ENGINE_MODE}, llm={'on' if config.llm_enabled() else 'off'})\n")
    profile = args.profile
    desc = {
        "clinic": "An AI phone receptionist for a family medical clinic that books, reschedules and "
                  "cancels appointments, answers hours/location questions, and must triage urgent "
                  "symptoms by advising 911/ER. Office hours Mon-Fri 8am-5pm.",
        "support": "A SaaS support chatbot handling billing, password resets and plan questions.",
        "bank": "A bank phone assistant for card disputes and fraud that must verify identity before "
                "disclosing or changing account information.",
    }[profile]
    target = service.create_target(name=f"Demo {profile} bot", channel="demo", endpoint=profile,
                                   description=desc)
    suite = service.generate_suite(description=desc, channel="demo", count=args.count)
    print(f"Target: {target.id}   Suite: {suite.id}  ({len(suite.personas)} personas)")
    print(f"Rubric hard constraints: {[c.id for c in suite.rubric.hard_constraints]}\n")
    run = create_and_execute_run(suite.id, target.id)
    _print_report(run.report, verbose=args.verbose)
    print(f"Tip: open the dashboard with  python -m proctor.server   then visit http://{config.API_HOST}:{config.API_PORT}\n")


def cmd_targets(args):
    db.init()
    if args.action == "add":
        t = service.create_target(args.name, args.channel, args.endpoint, args.description or "")
        print(json.dumps({"id": t.id, "consent_status": t.consent_status}, indent=2))
    elif args.action == "list":
        for t in db.list_targets():
            print(f"{t.id}  [{t.channel}] {t.name}  ({t.consent_status})  {t.endpoint}")
    elif args.action == "verify":
        t = db.get_target(args.target_id)
        if not t:
            sys.exit(f"No such target: {args.target_id}")
        if args.issue:
            code = consent.issue_verification(t)
            print(f"Verification code issued for {t.endpoint}: {code}")
            print("Prove ownership by echoing it back:  targets verify <id> --code <code>")
        elif args.code:
            ok = consent.confirm_verification(t, args.code)
            print("Verified." if ok else "Code did not match.")
            if not ok:
                sys.exit(1)


def cmd_suites(args):
    db.init()
    if args.action == "generate":
        s = service.generate_suite(args.description, channel=args.channel, count=args.count,
                                   spec=args.spec or "")
        print(f"Suite {s.id}: {s.name}  ({len(s.personas)} personas)")
        for p in s.personas:
            print(f"   {p.category:<11} {p.id:<30} {p.scenario}")
        print(f"Hard constraints: {[c.id for c in s.rubric.hard_constraints]}")
    elif args.action == "list":
        for s in db.list_suites():
            print(f"{s.id}  {s.name}  ({len(s.personas)} personas)  [{s.channel}]")


def cmd_run(args):
    db.init()
    run = create_and_execute_run(args.suite, args.target, repeats_override=args.repeats,
                                 baseline_run_id=args.baseline or "")
    _print_report(run.report, verbose=args.verbose)


def cmd_report(args):
    db.init()
    run = db.get_run(args.run_id)
    if not run or not run.report:
        sys.exit(f"No report for run {args.run_id}")
    _print_report(run.report, verbose=True)


def cmd_gate(args):
    """Run and exit non-zero if the gate verdict is BLOCK (for CI)."""
    db.init()
    gates = {"block_on_critical": True, "block_on_regression": True}
    if args.min_health is not None:
        gates["min_health"] = args.min_health
    run = create_and_execute_run(args.suite, args.target, baseline_run_id=args.baseline or "",
                                 gates=gates)
    _print_report(run.report, verbose=args.verbose)
    if run.report["gate_verdict"] == "BLOCK":
        print("GATE: BLOCK — failing the build.")
        sys.exit(1)
    print("GATE: PASS")


def main(argv=None):
    _setup_logging()
    p = argparse.ArgumentParser(prog="proctor", description="Proctor — conversational AI QA platform")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="Zero-setup end-to-end demo against the built-in bot")
    d.add_argument("--profile", default="clinic", choices=["clinic", "support", "bank"])
    d.add_argument("--count", type=int, default=10)
    d.add_argument("--verbose", action="store_true")
    d.set_defaults(func=cmd_demo)

    t = sub.add_parser("targets", help="Manage bots under test")
    t.add_argument("action", choices=["add", "list", "verify"])
    t.add_argument("target_id", nargs="?")
    t.add_argument("--name"); t.add_argument("--channel", default="chat")
    t.add_argument("--endpoint", default=""); t.add_argument("--description")
    t.add_argument("--issue", action="store_true"); t.add_argument("--code")
    t.set_defaults(func=cmd_targets)

    s = sub.add_parser("suites", help="Generate/list test suites")
    s.add_argument("action", choices=["generate", "list"])
    s.add_argument("--description", default=""); s.add_argument("--channel", default="chat")
    s.add_argument("--count", type=int, default=12); s.add_argument("--spec")
    s.set_defaults(func=cmd_suites)

    r = sub.add_parser("run", help="Run a suite against a target")
    r.add_argument("--suite", required=True); r.add_argument("--target", required=True)
    r.add_argument("--repeats", type=int, default=0); r.add_argument("--baseline")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="Print a stored run report")
    rep.add_argument("run_id"); rep.set_defaults(func=cmd_report)

    g = sub.add_parser("gate", help="Run and exit non-zero on BLOCK (CI gate)")
    g.add_argument("--suite", required=True); g.add_argument("--target", required=True)
    g.add_argument("--baseline"); g.add_argument("--min-health", type=float, dest="min_health")
    g.add_argument("--verbose", action="store_true")
    g.set_defaults(func=cmd_gate)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
