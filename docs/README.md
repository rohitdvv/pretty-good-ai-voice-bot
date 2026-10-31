# Proctor — Conversational AI Quality & Safety Assurance Platform

> **Working name: "Proctor."** A proctor administers and monitors tests. Rename freely.
> This `docs/` set is the authoritative design corpus for the company — written in the
> style of a FANG internal design-doc repository (PRD + RFCs). It is the single source
> of truth that engineering, GTM, and leadership build from.

---

## One-line thesis

**Point us at your AI agent. We stress-test it with thousands of realistic synthetic users across voice and chat, then hand you a scored, statistically-grounded, auditable report of every way it breaks — before your customers find out.**

Every company shipping a conversational AI agent (voice or chat) has the same unsolved
problem: they cannot know how it behaves across the long tail of real human inputs.
Manual QA does not scale, "vibe-checking" a few calls is not evidence, and a
mis-behaving agent is now a **legal, financial, and brand liability** (bad medical
advice, wrong refunds, leaked PII, successful jailbreaks). We are the automated QA,
evaluation, and continuous-assurance layer for the entire conversational-AI industry.

Category name we are coining: **CAIQA — Conversational AI Quality & Safety Assurance.**

---

## How to read this corpus

| # | Document | What it answers | Primary audience |
|---|----------|-----------------|------------------|
| 00 | **[README](README.md)** (this file) | What are we, why now, how the docs fit together | Everyone |
| 01 | **[Product & Use Cases](01-product-and-use-cases.md)** | Who buys, the end-to-end business use case, jobs-to-be-done, the full customer journey | Product, Sales, Founders |
| 02 | **[System Architecture](02-architecture.md)** | The whole system on one page, components, data flow, control plane vs. data plane | Engineering |
| 03 | **[Backend Systems](03-backend-systems.md)** | Every service in detail: orchestrator, telephony, realtime bridge, judge pipeline, queues | Engineering |
| 04 | **[Scoring & Math](04-scoring-and-math.md)** | **The math the platform does** — scoring model, statistics, regression detection, test-budget optimization, cost model | Eng, ML, Founders |
| 05 | **[Data Model & API](05-data-model-and-api.md)** | Entities, schemas, the public REST/SDK contract, webhooks | Engineering, Partners |
| 06 | **[Trust, Security & Compliance](06-trust-security-compliance.md)** | Consent, TCPA, HIPAA, SOC 2, PII handling, data retention, the trust policies | Legal, Security, Enterprise buyers |
| 07 | **[Reliability & Scale](07-reliability-and-scale.md)** | SLOs, capacity math, multi-region, failure modes, cost at scale | SRE, Engineering |
| 08 | **[Business Model & GTM](08-business-model-and-gtm.md)** | Pricing, unit economics, TAM, moat, go-to-market motion | Founders, Investors, Sales |
| 09 | **[Roadmap & Org](09-roadmap-and-org.md)** | Phased build plan, hiring, org structure, milestones | Founders, Leadership |

**If you read only two:** [04 Scoring & Math](04-scoring-and-math.md) (why our verdicts are
trustworthy, not vibes) and [08 Business Model](08-business-model-and-gtm.md) (why it's a company).

---

## The core product loop (the whole company in five steps)

```
   1. CONNECT          2. GENERATE           3. EXECUTE            4. EVALUATE           5. ASSURE
 ┌───────────┐      ┌──────────────┐      ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 │ Customer  │      │ Auto-persona │      │ Swarm of     │     │ Multi-judge  │     │ Scored report│
 │ points us │─────▶│ generator    │─────▶│ synthetic    │────▶│ scoring +    │────▶│ + regression │
 │ at a bot  │      │ builds the   │      │ users talk   │     │ statistics   │     │ gate in CI/CD│
 │ (# / URL) │      │ test suite   │      │ to the bot   │     │ + evidence   │     │ (continuous) │
 └───────────┘      └──────────────┘      └──────────────┘     └──────────────┘     └──────────────┘
      │                    │                     │                    │                    │
   consent &          domain-aware          Twilio + OpenAI       weighted rubric      pass/fail SLA,
   scoping            rubric derived        Realtime (voice)      + Wilson CIs +       trend lines,
                      from same spec        / HTTP (chat)         severity risk model  audit trail
```

Steps 1→3 are what today's prototype does for one domain. Steps 2, 4, 5 — generalized
persona generation, statistically-grounded scoring, and continuous regression assurance —
are what turn a demo into a **FANG-grade platform and a durable business.**

---

## What exists today (honest baseline, 2026-10-30)

A working single-domain prototype: a Python CLI that calls one medical-office voice agent
via Twilio, drives a live conversation with OpenAI's Realtime API, records/transcribes it,
and runs a GPT-4o post-call bug detector. Plus a new **domain-agnostic auto-persona
generator** (`persona_generator.py`) proven to generalize to e-commerce and banking.

Everything in docs 02–09 describes the target architecture we are building toward, with an
explicit migration path from this prototype called out in each doc under **"From prototype
to platform."**

---

## Design principles (our engineering values)

1. **Evidence over vibes.** Every verdict ships with a transcript span, audio, the judge's
   reasoning, and a confidence interval. If we can't show the receipt, we don't make the claim.
2. **Determinism where it matters, controlled stochasticity where it doesn't.** We embrace that
   LLMs and voice are non-deterministic and quantify it (variance, flakiness) rather than pretend.
3. **Consent-first.** We never test a bot the customer hasn't proven they own/authorize. Trust is
   the product; see [doc 06](06-trust-security-compliance.md).
4. **Control plane / data plane split.** Customer PII and raw audio live in an isolated, encrypted,
   short-retention data plane; the control plane never needs to see raw conversation content.
5. **Everything is an API.** The dashboard is a client of the same public API customers get.
   CI/CD integration is a first-class use case, not an afterthought.
