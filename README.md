# Proctor — Conversational AI Quality & Safety Assurance

> **Point Proctor at any AI bot — voice or chat. It unleashes a swarm of realistic synthetic users
> on it, then hands you a scored, statistically-grounded report of every way it breaks, before your
> customers find out.**

Every team shipping a conversational AI agent has the same unsolved problem: they can't know how it
behaves across the long tail of real human inputs, the system is non-deterministic, and every prompt
change is a silent regression risk. Proctor is the automated QA, evaluation, and continuous-assurance
layer for conversational AI — the `npm test` a conversation never had.

📄 **MIT licensed.** · 📐 Full design corpus in [`docs/`](docs/README.md) · 🚀 Run it in 60 seconds below.

---

## The loop

```
  CONNECT            GENERATE              EXECUTE             EVALUATE            ASSURE
  point us at   →   auto-build a    →    a swarm of     →   judge ensemble  →   scored report +
  a bot (#/URL)     tailored suite       synthetic users     + real stats        CI regression gate
  + prove consent   for your domain      talk to the bot     + evidence          (continuous)
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**60-second demo — no phone, no API key needed.** Runs the whole pipeline against a built-in,
deliberately-flawed bot and catches its planted safety bug:

```bash
PROCTOR_MODE=offline python -m proctor.cli demo --verbose
```

With an `OPENAI_API_KEY` in `.env`, it runs **real** LLM conversations and judging:

```bash
python -m proctor.cli demo --profile clinic --verbose
```

**The dashboard:**

```bash
python -m proctor.server     # → http://127.0.0.1:8080
```

Full guide: [`proctor/QUICKSTART.md`](proctor/QUICKSTART.md).

## What's inside

| Area | What it does | Docs |
|---|---|---|
| **Auto-persona generator** | Describe any bot → a tailored suite (happy / variation / edge / adversarial) | [03 §3](docs/03-backend-systems.md) |
| **Generalized evaluator** | A rubric derived from the bot description + a multi-dimension judge with evidence | [03 §4](docs/03-backend-systems.md) |
| **The scoring math** | Gated scores, Wilson CIs, tiered repeats, Bot Health + Safety Risk, regression tests + FDR | [04](docs/04-scoring-and-math.md) |
| **Run orchestrator** | Fan out persona × repeat, consent gate, bounded concurrency, aggregate | [03 §1](docs/03-backend-systems.md) |
| **Trust & consent** | Hard ownership gate, SSRF guard, single-use codes, secret redaction | [06](docs/06-trust-security-compliance.md) |
| **REST API + dashboard** | Everything is an API; the UI is just a client | [05](docs/05-data-model-and-api.md) |
| **CI/CD gate** | `proctor gate …` exits non-zero when safety or task success regresses | [05 §3](docs/05-data-model-and-api.md) |

## CI/CD regression gate

```bash
python -m proctor.cli gate --suite <suite_id> --target <target_id> --baseline <previous_run_id>
# exits non-zero (fails the build) if a critical persona regresses or the baseline is invalid
```

## Channels

| Channel | Status | Notes |
|---|---|---|
| `demo` | ✅ built-in | deliberately-flawed local bot — demo the whole loop with zero setup |
| `chat` | ✅ | drives a customer HTTP chat endpoint (SSRF-guarded, consent-gated) |
| `voice` | 🔌 seam | wraps the original Twilio + OpenAI Realtime pipeline (see below) |

## Tests

```bash
python tests/test_stats.py        # the scoring math (docs/04 worked examples)
python tests/test_hardening.py    # SSRF guard, consent codes, fail-safe gate verdicts
```

## The voice engine (origin)

Proctor grew out of an automated **voice** bot tester that calls a medical-office AI agent via Twilio,
drives a live conversation with OpenAI's Realtime API, records/transcribes it, and analyzes it for
bugs. That stack still lives at the repo root (`caller.py`, `server.py`, `bug_detector.py`,
`main.py`, `personas/`) and is the seam the `voice` channel plugs into. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for its design.

## Status

This is a **starting-level MVP**: the full loop works on one machine and maps cleanly onto the
distributed architecture in [`docs/`](docs/README.md). Not yet included (funded scaling milestones,
not a weekend's work): massive parallelism, multi-tenant auth, HIPAA/SOC-2 certification, SIP
telephony, and the live voice path driving real calls. The MVP binds to localhost by default; set
`PROCTOR_API_KEY` before exposing it on a network.

## License

[MIT](LICENSE) © 2026 Rohit Dusanapudi
