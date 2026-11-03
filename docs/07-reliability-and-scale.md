# 07 — Reliability & Scale

## 1. SLOs (our own promises)

| Service | SLO | Error budget |
|---|---|---|
| API availability | 99.9% monthly | 43 min/mo |
| Run completion (started → report) | 99.5% of runs complete or cleanly error | — |
| Run latency | p95 < 5 min for a 100-persona chat suite; < 30 min voice | — |
| Dashboard read | p95 < 300 ms | — |
| Data durability (audio/results) | 99.999999999% (S3-class) | — |

A run that cannot complete must fail **loudly and refund budget** — a silent stuck run is the worst
outcome (customer thinks they're covered and isn't). The Orchestrator's durable workflows (doc 03 §1)
exist precisely to make this guarantee.

## 2. Capacity math (queueing model)

Concurrent voice calls are the scarce resource (telephony channels + realtime model slots). Model
the system as **M/M/c**: jobs arrive at rate λ (calls/sec), each call holds a channel for mean
service time `1/μ` (≈ call duration + setup, say 3.5 min = 210 s → μ ≈ 0.00476/s), with `c` channels.

- **Utilization** ρ = λ/(cμ); keep ρ < 0.8 for healthy queueing.
- **Little's Law**: average calls in system `L = λ · W` (W = time in system). To sustain, e.g.,
  **100 concurrent calls** you need `c ≥ 100` channels and the matching realtime-model concurrency.
- **Throughput planning:** to run a 190-call suite in ≤ 25 min at ρ≈0.7, required concurrency
  `c ≈ L/ (service_time) ≈ (190 calls · 210 s) / (1500 s) ≈ 27` channels. Provision headroom → ~40.

Capacity is elastic: Conversation Workers autoscale on queue depth; telephony channels are
pre-negotiated pools (Twilio subaccounts / SIP trunks) with burst reservations. Chat has no channel
limit — it scales with worker CPU and model rate limits only.

## 3. Cost at scale (why COGS halves)

From doc 04 §7, the two biggest voice COGS levers:
1. **Telephony:** migrate Twilio ($0.014/min) → **direct SIP trunking** (~$0.004/min) past ~50k
   min/mo. ~70% cut on the telephony line item.
2. **Realtime model:** committed-use / negotiated rates and model選 choice; evaluate cheaper
   voice-to-voice models as they mature; cache/trim judge token usage.

Net effect (doc 04 example): voice conversation COGS drops ~$0.37 → ~$0.22. Chat stays ~$0.01–0.05.
Gross margin target **75–85%** at scale (doc 08) depends on executing these two migrations, so they
are explicit roadmap items (doc 09), not afterthoughts.

## 4. Multi-region & isolation

- **Control plane:** multi-region active-active behind global anycast; Postgres with regional
  read replicas; stateless services deploy everywhere.
- **Data plane:** region-pinned pools (US-East, EU-West, …) so raw audio/PII never crosses borders
  (doc 06 §3). A run's data plane is chosen by the Target's region.
- **Enterprise single-tenant / in-VPC** data plane: same worker images deployed into the customer's
  cloud account; control plane orchestrates but never holds their raw content.

## 5. Failure modes & mitigations

| Failure | Blast radius | Mitigation |
|---|---|---|
| Telephony provider outage | Voice runs in a region stall | Multi-provider telephony abstraction; failover trunk; retry/backoff |
| Realtime model provider outage/limit | Voice execution degraded | Pluggable provider interface; queue + backpressure; degrade to chat where applicable |
| A judge model down/slow | Scoring backs up | Ensemble tolerates J−1; abstain path; async catch-up |
| Worker crash mid-call | 1 conversation lost | Temporal re-queues the job; dedupe by idempotency key |
| Orchestrator node loss | None (durable state) | Temporal resumes workflows on another node |
| Customer line overwhelmed | Customer's prod impacted | Enforced per-target concurrency cap + customer-declared rate (doc 06 §1) |
| Bad judge calibration drift | Wrong verdicts | Continuous golden-set monitoring (doc 04 §6); alert on κ drop; freeze gating on regression |
| Cost runaway (buggy loop calls) | $$$ | Pre-authorized per-run budget cap; global spend circuit-breaker; anomaly alerts |

## 6. Observability

Every job carries one trace ID across API → orchestrator → worker → bridge → judge → report
(OpenTelemetry). Golden signals per service (latency, traffic, errors, saturation). Business metrics
(runs/day, calls/day, COGS/run, judge κ) on the same stack. Alerting via PagerDuty with runbooks.
We dogfood: Proctor's own health has SLOs and error budgets like any FANG service.

## 7. From prototype to platform (reliability)

Today: single process, `ngrok`, in-memory `active_sessions`, sequential calls, no retries, secrets
in `.env`. None of that survives a paying customer. The ordered hardening: (1) secrets → Vault,
(2) sequential → queue + parallel workers, (3) in-memory session → durable store, (4) ngrok →
managed regional ingress, (5) add retries/timeouts/circuit-breakers, (6) add the budget
circuit-breaker. Each maps to a doc-09 milestone.
