# 09 — Roadmap & Org

## 1. Phased build plan

Sequencing principle: **build the trust gate and the orchestrator first** (everything hangs on
them), make the core loop real for voice, then generalize scoring, then expand channels and
enterprise. Each phase ends in something demo-able and sellable.

### Phase 0 — Prototype (DONE / today)
Single-domain voice tester (Twilio + Realtime + FastAPI + GPT-4o bug detector) and a proven
**domain-agnostic persona generator** (`persona_generator.py`). Validates the core loop works.

### Phase 1 — Productize the core (≈ 4–6 weeks)
*Goal: a web product a design partner can use on their own bot, safely.*
- **Consent gate + ownership verification** (doc 06 §1) — build first, it blocks real usage.
- Move secrets to a manager; remove committed creds (doc 06 §8).
- **Run Orchestrator** (durable workflow) + **job queue**; parallelize calls (kill the sequential CLI).
- Stateless **Conversation Worker + Realtime Bridge** (retire the in-memory `active_sessions`).
- Minimal **dashboard**: add target → verify → generate suite → run → scored report with audio +
  evidence spans.
- **Generalized evaluator** (doc 03 §4) deriving the rubric from the bot description (first judge).
- Deliverable: *connect a number → get a scored report.* The free-report GTM wedge (doc 08 §4).

### Phase 2 — Trustworthy scoring + regression (≈ 6–10 weeks)
*Goal: verdicts that are evidence, and the sticky CI use case.*
- **Statistics layer** (doc 04): Wilson CIs, tiered/adaptive repeats, flakiness, Health + Risk scores.
- **Judge ensemble + calibration** vs. a golden set (κ/F1 reported).
- **Regression diffing + gates** (two-proportion + FDR) and the **CLI/CI Action** (doc 05 §3).
- **Scheduling + monitoring + webhooks/alerting**.
- SOC 2 controls instrumented from here on.

### Phase 3 — Expand surface + enterprise (≈ Q3+)
*Goal: TAM expansion and the enterprise segment.*
- **Chat channel** adapters (HTTP/WS/web-widget) — 10× market, high margin (doc 03 §2).
- **HIPAA + BAA**, **in-VPC / single-tenant data plane**, SSO/SCIM, region pinning (doc 06, 07).
- **SIP telephony migration** + model cost negotiation (doc 07 §3) — halve COGS.
- Vertical **starter suites** (healthcare, fintech, ecommerce) seeding the data moat.

### Phase 4 — Platform & flywheel (≈ Year 2)
- Benchmarking (bot vs. bot, bot vs. human baseline), coverage-driven persona generation,
  bandit test-budget optimization (doc 04 §8), human-review tier, marketplace of suites,
  EU AI Act / ISO 27001, multi-region active-active.

## 2. Milestone → doc map (traceability)

| Milestone | Spec |
|---|---|
| Consent gate | doc 06 §1 |
| Orchestrator + queue | doc 02 §3, doc 03 §1 |
| Parallel workers / bridge | doc 03 §2, doc 07 §7 |
| Generalized evaluator | doc 03 §4 |
| Statistics + scores | doc 04 §1–4 |
| Judge ensemble/calibration | doc 04 §6 |
| Regression + CI gate | doc 04 §5, doc 05 §3 |
| Chat channel | doc 03 §2 |
| HIPAA / in-VPC | doc 06, doc 07 §4 |
| SIP migration | doc 07 §3 |

## 3. Org structure (how the company scales, FANG-style)

Early (≤10): one team, founder-led. As you grow, organize around the architecture's seams so teams
own clear service boundaries:

```
                         CEO / Founder
        ┌───────────────────┼─────────────────────┬────────────────────┐
     Eng (CTO)         Product/Design          GTM (Sales+Mktg)      Ops/Finance
        │
   ┌────┼───────────────┬────────────────┬──────────────────┐
 Platform/        Voice & Realtime   Eval/ML            Trust & Infra (SRE,
 Orchestration    (telephony,        (judges, scoring,   Security, Compliance)
 (control plane)  bridge, data plane) calibration, math)
```

- **Platform/Orchestration** owns control plane, API, run lifecycle.
- **Voice & Realtime** owns the hard telephony/audio moat and data-plane workers.
- **Eval/ML** owns persona generation, judges, the scoring math, and calibration (doc 04) — the
  intellectual core and data flywheel.
- **Trust & Infra** owns SRE/SLOs (doc 07), security + compliance (doc 06) — a first-class org, not
  a side task, because trust is the product.
- **Product/Design** owns the dashboard, report UX, and the self-serve PLG funnel.
- **GTM** runs the dual funnel (PLG + enterprise) and voice-platform partnerships (doc 08 §4).

## 4. First hires (in order)
1. Founding voice/realtime engineer (owns the moat).
2. ML/eval engineer (owns scoring + judge calibration).
3. Platform/backend engineer (orchestrator, API).
4. Design-partner-facing founder-led sales.
5. Security/compliance lead (ahead of the first enterprise deal).

## 5. Definition of done for "the complete product"
A customer can, self-serve: **verify a bot they own → describe it → get an auto-generated, tailored
test suite → run it across voice and chat → receive a statistically-grounded, evidence-backed scored
report → wire the regression gate into CI → schedule continuous monitoring → export an audit trail —
all under enforced consent, isolation, and retention policies.** That is Phases 1–3 delivered.
