# 03 — Backend Systems (detailed design)

This doc specifies each backend service: responsibility, interface, internal design, scaling
profile, and failure handling. Services communicate over gRPC (internal) and emit events to Kafka.

---

## 1. Run Orchestrator (the brain)

**Responsibility:** turn a run request into executed, scored, aggregated results — durably, with
retries, budget/consent enforcement, and partial-failure tolerance.

**Why Temporal:** a run is a long-lived (seconds→minutes), stateful, failure-prone distributed
process. Hand-rolling this with cron + a status column is how you get stuck runs and lost money.
Temporal gives durable execution: if a worker dies mid-run, the workflow resumes exactly where it
left off; retries, timeouts, and heartbeats are declarative.

**Workflow (pseudocode):**
```
workflow ExecuteRun(run_id):
    cfg = load_run_config(run_id)                      # suite version, target, repeats, gates
    assert consent_valid(cfg.target_id)                # HARD gate — abort if not (doc 06)
    assert budget_available(cfg.org_id, estimate(cfg)) # pre-authorize spend
    jobs = expand(cfg.suite.personas, cfg.repeats)     # persona × repeat → job specs
    # Fan out with bounded concurrency = min(plan_limit, provider_limit, target_rate_limit)
    results = parallel_map(jobs, concurrency=cfg.concurrency):
        activity ExecuteConversation(job)  # ret/timeout: 2 retries, 5-min timeout, heartbeat
        activity ScoreConversation(conv)   # judge ensemble
    report = activity Aggregate(results, baseline=cfg.baseline)   # doc 04
    activity Persist(report); activity EmitWebhook(run.completed)
    if cfg.gates and report.fails(cfg.gates): mark_run(FAILED_GATE)
```

**Concurrency control:** the effective parallelism is
`min(plan concurrency, telephony channel limit, model rate limit, customer-declared target rate)`.
The customer declares how many simultaneous calls their agent can take (default 5) so we never
DoS their own line — this is both courtesy and a trust policy.

**Budget enforcement:** before fan-out, estimate cost (doc 04 §7) and reserve it against the org's
balance/plan. Abort rather than overspend. Emit metering events per job.

**Failure handling:** a single conversation failing (busy signal, provider hiccup) retries up to 2×;
persistent failures are recorded as `errored` (not `failed`) and excluded from scoring with a noted
denominator — a call we couldn't complete is not the bot failing.

**Scaling:** orchestrator is stateless; Temporal persists workflow state. Scale workers horizontally.

---

## 2. Conversation Workers + Realtime Bridge (the hard part)

**Responsibility:** execute exactly one conversation (one persona, one repeat) against the target
and return a structured transcript + audio reference.

### Voice path
This is the grown-up `caller.py` + `server.py`. Per call:
1. Worker claims a job; requests a telephony channel from the pool.
2. **Realtime Bridge** opens: (a) outbound call to the target number via Twilio/SIP Media Streams;
   (b) a session to the voice model (OpenAI Realtime or pluggable) configured with the persona's
   wrapped `system_prompt`, g711 μlaw audio format, VAD, and transcription on both directions.
3. Bridge forwards audio target→model and model→target in real time, handling **barge-in**
   (interruptions), **turn-taking**, and **silence/timeout** (hang up if the target dead-airs 15s).
4. Captures a **dual-channel transcript** (agent utterances via input transcription, synthetic-user
   utterances via output transcription) with timestamps, plus raw audio.
5. On call end: persist transcript (OLTP) + audio (object store, SSE-KMS, TTL), emit `job.completed`.

**Critical engineering details (learned on the prototype, now productized):**
- **Prompt wrapper** is mandatory: synthetic users must answer verification questions directly, keep
  turns short, not loop. (Encoded in `persona_generator.py::BEHAVIORAL_RULES`.)
- **Latency budget:** total round-trip (agent speech → model → audio out) must stay < ~800ms or the
  target agent talks over us. Voice-to-voice Realtime (not STT→LLM→TTS) is why.
- **One worker = one call**; never share the fragile in-memory session across calls (the prototype's
  `active_sessions` dict becomes per-worker state keyed by CallSid, backed by Redis for recovery).

### Chat path
Much simpler and cheaper. Worker opens an HTTP/WebSocket session to the customer's declared chat
endpoint (with their auth), drives a turn-by-turn dialogue from the persona prompt, captures the
transcript. No telephony, no audio, no latency constraint. This is how we expand TAM 10× (doc 01).

**Pluggable target adapters:** `TargetAdapter` interface with implementations for `twilio_voice`,
`sip_voice`, `http_chat`, `websocket_chat`, `web_widget` (headless-browser driven). New channels =
new adapters, not new architecture.

---

## 3. Suite / Persona Service

**Responsibility:** generate, store, and version test suites and the matching evaluation rubric.

- **Generator** — productized `persona_generator.py`: `generate_personas(description, count,
  channel, domain_hints, spec)`. Produces schema-valid personas with forced coverage across
  happy/variation/edge/adversarial buckets (doc 04 §8 explains how we optimize the mix).
- **Rubric compiler** — from the same bot description + customer **spec** (hard rules), compiles a
  machine-checkable rubric: dimensions, weights, pass thresholds, and hard constraints
  ("MUST escalate chest pain" → a binary safety check). Keeps persona generation and scoring in sync.
- **Versioning** — suites are immutable, content-addressed (`suite@v3`, hash of personas+rubric).
  A regression run pins `baseline=suite@v2` so comparisons are apples-to-apples.
- **Library** — curated starter suites per vertical (healthcare-triage, fintech-dispute,
  ecommerce-returns) that seed generation and encode accumulated failure taxonomies (the data moat).

---

## 4. Judge Pipeline

**Responsibility:** convert a raw transcript into a structured, evidence-backed, calibrated score.

**Design:** an **ensemble of heterogeneous judge models** (e.g., Claude-class, GPT-class,
Gemini-class) each scores the transcript against the rubric, returning per-dimension scores, binary
hard-constraint checks, and **evidence spans** (the exact exchange + severity). The pipeline then:
1. Aggregates ensemble outputs (median per dimension; majority vote on binary safety checks; see
   doc 04 §6 for disagreement handling and calibration).
2. Extracts and stores evidence spans linked to transcript offsets + audio timestamps.
3. Writes a `ScoredResult` to the Scoring DB.

**Why ensemble:** single-LLM judges are biased and occasionally wrong. Ensemble + calibration
against a human-labeled golden set gives us a *measured* judge accuracy we can report to customers —
"our safety judge agrees with human experts 96% of the time (κ=0.89)."

**Guardrails:** judges never see other tenants' data; prompts are injection-hardened (the transcript
is data, not instructions); a confidence/abstain path routes low-agreement cases to human review for
high-stakes customers.

---

## 5. Reporting / Results Service

**Responsibility:** aggregation, statistics, regression diffing, and the read API.

- Aggregates `ScoredResult`s into **Bot Health Score**, **Safety Risk Score**, per-dimension scores,
  each with confidence intervals (doc 04 §2–3).
- Computes **regression diffs** vs. a baseline run using two-proportion tests (doc 04 §5).
- Detects **flaky personas** (high run-to-run variance) and surfaces them (doc 04 §4).
- Serves the dashboard, report exports (PDF/JSON), and trend time-series.
- Evaluates **gates** (configurable pass/fail rules) and returns a single CI verdict.

---

## 6. Billing & Metering

Meters three cost drivers: **telephony minutes, model tokens (voice + judge), and runs/seats.**
Emits a usage event per job to Kafka; a metering consumer rolls up per-org usage into the billing
system (Stripe). Enforces plan limits and pre-authorizes run budgets (doc 08 pricing).

---

## 7. Cross-cutting services

- **Consent & Ownership service** (in Tenant/Auth) — see [doc 06](06-trust-security-compliance.md).
  Nothing executes without a valid record. This is a hard dependency of the Orchestrator.
- **PII Vault** — tokenizes sensitive fields; raw PII is stored encrypted with per-tenant keys and
  short TTL, referenced by token elsewhere so the control plane never holds raw PII.
- **Observability** — every job carries a trace ID from API request → call → judge → report. Health
  of the platform itself (not just customers' bots) is an SLO (doc 07).
- **Feature flags / config** — per-tenant rollout of new judges, new channels, new voice providers.

---

## 8. Service inventory & scaling profile (summary)

| Service | Plane | Lang | State | Scaling driver | Failure if down |
|---|---|---|---|---|---|
| API Gateway | Control | Go | none | req/s | No new runs; existing continue |
| Tenant/Auth/Consent | Control | Go | Postgres | orgs | No auth; hard stop |
| Suite/Persona | Control | Python | Postgres | gen requests | No new suites; runs with existing OK |
| Run Orchestrator | Control | Go+Temporal | Temporal | concurrent runs | Runs pause, resume on recovery |
| Conversation Workers | **Data** | Python | Redis/ephemeral | concurrent calls | In-flight calls lost; retried |
| Realtime Bridge | **Data** | Python | ephemeral | concurrent audio streams | Same |
| Judge Pipeline | **Data** | Python | queue | completed convs | Scoring backs up; catches up |
| Reporting | Control | Go | Postgres+ClickHouse | read QPS | Reports unavailable; data safe |
| Billing/Metering | Control | Go | Postgres+Kafka | usage events | Metering buffers in Kafka |
