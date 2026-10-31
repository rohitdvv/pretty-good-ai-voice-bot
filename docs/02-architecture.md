# 02 — System Architecture

## 1. The whole system on one page

```
                                    ┌──────────────────────────────────────────┐
                                    │                CLIENTS                     │
                                    │  Web dashboard · REST/SDK · CI plugin ·    │
                                    │  Terraform provider · Webhooks consumer    │
                                    └───────────────────┬────────────────────────┘
                                                        │ HTTPS (OAuth2 / API key)
                                    ╔═══════════════════▼════════════════════════╗
                                    ║              EDGE / API GATEWAY              ║
                                    ║  AuthN/Z · rate limit · quota · WAF · audit  ║
                                    ╚═══════════════════╦════════════════════════╝
                                                        │
        ┌───────────────────────────────── CONTROL PLANE (stateless services) ─────────────────────────────────┐
        │                                                                                                        │
        │   ┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────────────┐  │
        │   │  Tenant &   │   │  Suite /     │   │  Run          │   │  Reporting   │   │  Billing &         │  │
        │   │  Auth Svc   │   │  Persona Svc │   │  Orchestrator │   │  / Results   │   │  Metering Svc      │  │
        │   │ (orgs,RBAC) │   │ (generator)  │   │  (scheduler)  │   │  Svc         │   │                    │  │
        │   └─────────────┘   └──────┬───────┘   └──────┬────────┘   └──────┬───────┘   └────────────────────┘  │
        │                            │                  │                   │                                   │
        └────────────────────────────┼──────────────────┼───────────────────┼───────────────────────────────────┘
                                     │                  │ enqueue jobs      │ read results
                           calls LLM │           ┌──────▼───────┐           │
                                     │           │  JOB QUEUE   │  (Kafka / SQS + Temporal workflows)
                                     │           └──────┬───────┘           │
        ┌──────────────── DATA PLANE (isolated, encrypted, short-retention) ─┼──────────────────────────────────┐
        │                                   consume     │                    │                                   │
        │   ┌───────────────────────┐   ┌───────────────▼─────────┐   ┌──────▼─────────┐   ┌──────────────────┐  │
        │   │  Conversation Workers │   │  Realtime Bridge         │   │  Judge Pipeline│   │  Object Store     │ │
        │   │  (voice + chat exec)  │◄─▶│  (Twilio/SIP ↔ Realtime) │   │  (ensemble     │   │  (audio, raw      │ │
        │   │                       │   │                          │   │   LLM scoring) │   │  transcripts)     │ │
        │   └───────────┬───────────┘   └──────────────────────────┘   └──────┬─────────┘   └──────────────────┘ │
        │               │                                                     │                                  │
        │        ┌──────▼──────┐   ┌───────────────┐   ┌──────────────┐   ┌───▼──────────┐                       │
        │        │ Telephony   │   │ STT / diariz. │   │ Transcript    │   │ Scoring DB    │  (results, metrics)   │
        │        │ providers   │   │ (backup)      │   │ store (OLTP)  │   │ + metrics TSDB│                       │
        │        └─────────────┘   └───────────────┘   └──────────────┘   └──────────────┘                       │
        └────────────────────────────────────────────────────────────────────────────────────────────────────────┘

   Cross-cutting: Observability (OTel traces/metrics/logs) · Secrets (Vault) · Feature flags · Config · PII vault
```

## 2. The organizing idea: control plane vs. data plane

This split is the single most important architectural decision and it drives security, compliance,
scaling, and cost.

- **Control plane** — stateless microservices that manage *metadata*: tenants, suites, run
  definitions, schedules, results, billing. It orchestrates work but **never touches raw audio or
  live conversation content**. It can run in standard multi-tenant infrastructure.
- **Data plane** — the workers that actually place calls, bridge audio, hold PHI/PII and raw
  transcripts, and run judges. It is **isolated, encrypted, short-retention, and regionally
  pinned**. For enterprise/HIPAA customers it can be deployed single-tenant or in-VPC.

Why: raw conversations contain the most sensitive data (voices, SSNs, symptoms). Keeping that in a
blast-radius-limited data plane means the bulk of the system (control plane) is out of compliance
scope, and we can offer "your audio never leaves your region/VPC" — a decisive enterprise selling point.

## 3. Components (responsibilities)

### Control plane
- **API Gateway / Edge** — TLS termination, authN (API keys + OAuth2/OIDC), authZ (RBAC per org),
  rate limiting, per-tenant quotas, WAF, request audit logging. Single front door.
- **Tenant & Auth Service** — organizations, users, roles, API keys, SSO, the **consent &
  ownership-verification records** that gate whether a target number/endpoint may be tested.
- **Suite / Persona Service** — houses the auto-persona generator (today's `persona_generator.py`
  grown up), suite versioning, and the rubric/spec compiler. Suites are immutable versioned
  artifacts so a regression run can pin an exact baseline.
- **Run Orchestrator** — the scheduler/state-machine. Turns a "run this suite against this target"
  request into a DAG of conversation jobs, enforces concurrency/consent/budget limits, tracks run
  lifecycle, handles retries and partial failures. Implemented as durable **Temporal** workflows.
- **Reporting / Results Service** — aggregates per-conversation scores into suite/bot health scores,
  computes statistics (doc 04), serves the dashboard and report exports, diffs runs for regression.
- **Billing & Metering Service** — meters telephony minutes, model tokens, and runs; enforces plan
  limits; emits usage events for invoicing.

### Data plane
- **Conversation Workers** — stateless workers that execute a single conversation job end-to-end for
  one channel. Voice workers manage a call's lifecycle; chat workers drive an HTTP/websocket dialog.
  Horizontally scaled, each handles N concurrent conversations bounded by provider limits.
- **Realtime Bridge** — the audio pipe (today's `server.py`): Twilio/SIP media stream ⇄ OpenAI
  Realtime (or pluggable voice model), handling barge-in, turn-taking, g711 transcoding, and
  bidirectional transcript capture. The hardest, most latency-sensitive component.
- **Judge Pipeline** — post-conversation scoring. Runs an ensemble of judge models against the
  rubric, extracts evidence spans, and emits structured scored results (today's `bug_detector.py`
  generalized into a calibrated, multi-judge service).
- **Stores** — OLTP transcript store, object store for audio, scoring DB for results, time-series DB
  for metrics/trends, and an isolated **PII vault** (tokenization) for any sensitive fields.

## 4. End-to-end data flow for one run (sequence)

```
Client ──POST /v1/runs {suite_id, target_id, repeats}──▶ API GW ──▶ Run Orchestrator
Orchestrator: verify consent for target_id; check budget/quota; expand suite×repeats into jobs
Orchestrator ──enqueue N conversation jobs──▶ Job Queue
Conversation Worker (per job):
    ├─ voice: Realtime Bridge opens call (Telephony) + Realtime model session
    │         drives dialogue from persona system_prompt; captures dual transcript + audio
    └─ chat:  opens session to customer endpoint; drives dialogue over HTTP/WS
    ──▶ persist transcript (OLTP) + audio (object store); emit job-complete event
Judge Pipeline (triggered per completed job):
    ──▶ ensemble score vs rubric; extract evidence; write scored result (Scoring DB)
Reporting Service (on all jobs done, or streaming):
    ──▶ aggregate → health score + CIs + risk score; diff vs baseline if regression run
    ──▶ emit webhook run.completed; dashboard renders; CI plugin reads gate verdict
```

## 5. Technology choices (and why)

| Concern | Choice | Why (one line) |
|---|---|---|
| Services language | **Go** (control plane), **Python** (data-plane workers/ML) | Go for concurrent stateless services; Python where the model/ML ecosystem lives |
| Workflow orchestration | **Temporal** | Durable, retryable, long-running run state machines without hand-rolling a scheduler |
| Async messaging | **Kafka** (events) + **SQS/Temporal task queues** (work) | Kafka for the audit/event log; task queues for job dispatch |
| Telephony | **Twilio** now; **SIP trunking (Telnyx/direct)** at scale | Twilio for speed; raw SIP cuts per-minute cost ~60% at volume (doc 07) |
| Voice model | **OpenAI Realtime** now; **pluggable provider interface** | Avoid lock-in; customers may want to test with a specific voice stack |
| Judges | **Multi-provider ensemble** (Claude, GPT, Gemini class) | Reduce single-model bias; calibrate against human labels (doc 04 §6) |
| OLTP | **PostgreSQL** (Aurora) | Boring, correct, transactional for runs/results |
| Metrics/trends | **ClickHouse / TimescaleDB** | Cheap high-cardinality time-series for health-score trends |
| Object store | **S3** (SSE-KMS, per-tenant keys, lifecycle TTL) | Durable, cheap, encrypted, auto-expiring audio |
| Secrets | **Vault / KMS** | Customer telephony creds & tokens never in env files |
| Observability | **OpenTelemetry** → traces/metrics/logs | One standard across polyglot services |
| Deploy | **Kubernetes** + per-region data-plane node pools | Data-plane isolation and regional pinning |

## 6. From prototype to platform (migration path)

| Prototype (today) | Platform (target) | Migration step |
|---|---|---|
| `main.py` CLI orchestrates sequentially | Run Orchestrator (Temporal), parallel | Extract run logic into a workflow; jobs to a queue |
| `server.py` single FastAPI + background thread + `active_sessions` dict | Stateless Conversation Workers + Realtime Bridge, state in Redis/DB | Replace in-memory dict with a job/session store; one worker per call |
| `ngrok` public URL | Managed ingress + per-call signed media URLs | Terminate media at a stable regional endpoint |
| `bug_detector.py` single GPT-4o call | Judge Pipeline: ensemble + calibration + evidence spans | Wrap current call as one judge; add ensemble + stats |
| `personas/*.json` on disk | Suite/Persona Service with versioned suites | Move files into DB; keep JSON schema identical (already compatible) |
| No consent gate | Ownership verification + authorization records | Build the trust gate FIRST (doc 06) — it blocks everything |
| Files in `reports/` | Reporting Service + dashboard + exports | Persist structured results; build read API |

**Sequencing principle:** build the **consent gate (doc 06)** and the **Run Orchestrator** first —
they are the backbone everything else hangs on — then parallelize workers, then ensemble the judges.
