# Proctor — Quickstart

Proctor is the **Conversational AI Quality & Safety Assurance** platform (MVP). It auto-generates
realistic test users for any AI bot, runs them against it, and scores the results with real
statistics — producing an evidence-backed report and a CI/CD regression gate.

Full design corpus: [`../docs/`](../docs/README.md). The math behind the scores:
[`../docs/04-scoring-and-math.md`](../docs/04-scoring-and-math.md).

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # fastapi, uvicorn, openai, python-dotenv, requests, ...
```

Optional: set `OPENAI_API_KEY` in `.env` for real LLM persona generation, judging, and the
built-in demo bot. **Without a key, everything still runs** in deterministic offline mode
(`PROCTOR_MODE=offline`) — great for tests and CI.

## 60-second demo (no phone, no keys needed)

```bash
# Offline (deterministic): proves the full pipeline
PROCTOR_MODE=offline python -m proctor.cli demo --verbose

# With an API key: runs real conversations against a deliberately-flawed demo bot and
# catches the planted safety bug (chest pain not escalated -> BLOCK)
python -m proctor.cli demo --profile clinic --count 6 --verbose
```

## The dashboard

```bash
python -m proctor.server       # -> http://127.0.0.1:8080
```

Click **Run demo test**, or describe your own bot to auto-generate a suite. Click any persona
row to read the transcripts and the judge's evidence.

## Real flow (your own bot)

```bash
# 1. Register the bot under test
python -m proctor.cli targets add --name "My Bot" --channel chat --endpoint https://mybot/chat

# 2. Prove you own it (consent gate, docs/06) — issue a code, then echo it back
python -m proctor.cli targets verify <target_id> --issue
python -m proctor.cli targets verify <target_id> --code <code>

# 3. Generate a tailored suite
python -m proctor.cli suites generate --description "what your bot does" --channel chat --count 12

# 4. Run it
python -m proctor.cli run --suite <suite_id> --target <target_id> --verbose
```

## CI/CD regression gate

Exits non-zero when safety or task success regresses vs. a baseline run — wire into any pipeline:

```bash
python -m proctor.cli gate --suite <suite_id> --target <target_id> --baseline <previous_run_id>
```

## Channels

| Channel | Status | Notes |
|---|---|---|
| `demo` | ✅ built-in | deliberately-flawed bot to demo the whole loop with zero setup |
| `chat` | ✅ | drives a customer HTTP chat endpoint (`{messages:[...]}` → `{reply:"..."}`) |
| `voice` | 🔌 seam | wraps the existing Twilio + OpenAI Realtime pipeline (`../caller.py`, `../server.py`) |

## Layout (maps onto docs/02 architecture)

```
proctor/
  config.py          settings + engine mode (auto/offline/live)
  models.py          domain entities (docs/05)
  db.py              SQLite persistence (swaps for Postgres later)
  consent.py         ownership/consent gate (docs/06 §1) — hard precondition
  personas.py        auto-persona generator (docs/03 §3)
  evaluator/
    rubric.py        derive the rubric from the bot description (docs/03 §3)
    judge.py         score a transcript, evidence + ensemble (docs/03 §4, docs/04 §1,§6)
  scoring/stats.py   THE MATH — docs/04 (Wilson CIs, health/risk, regression, FDR, ...)
  execution/
    targets.py       adapters: demo bot, HTTP chat, voice seam (docs/03 §2)
    synthetic.py     the synthetic user driving a persona
    runner.py        drives one conversation turn-by-turn
  orchestrator.py    fan out persona×repeat, tiered repeats, score, aggregate (docs/03 §1)
  reporting.py       health/risk/CIs/regression/gates (docs/03 §5, docs/04 §2-5)
  service.py         use-case facade
  api.py             public REST API + serves the dashboard (docs/05 §3)
  server.py          launches API + dashboard
  cli.py             full loop + CI gate from the terminal
  web/index.html     the dashboard
```

## Engine modes

- `PROCTOR_MODE=auto` (default) — use the LLM if a key is present, else offline.
- `PROCTOR_MODE=offline` — never call an LLM (deterministic; tests/CI/no-key demos).
- `PROCTOR_MODE=live` — require the LLM.
