# 01 — Product & Use Cases

## 1. The problem, precisely

Conversational AI agents (voice bots, chatbots, phone IVR-replacements) are being deployed
into the critical path of healthcare, banking, insurance, retail, travel, and government —
functions where a wrong answer causes real harm. The teams shipping them face a structural QA gap:

- **The input space is effectively infinite.** A human can say anything, in any accent, any
  language, any emotional state, in any order. You cannot enumerate test cases by hand.
- **The system is non-deterministic.** The same input can produce different outputs run to run.
  A single passing call proves nothing.
- **Failures are silent and expensive.** The bot confidently books an appointment on a closed
  day, approves an unauthorized transaction, hallucinates a policy, or leaks another customer's
  PII — and nobody notices until a customer complains, a regulator calls, or it's on social media.
- **Every prompt change is a regression risk.** Teams tune prompts weekly. A change that fixes one
  behavior silently breaks three others. There is no `npm test` for a conversation.

Today the "solution" is: a few engineers manually call their own bot a dozen times before launch,
listen, and shrug. That is the equivalent of shipping software with no test suite.

## 2. The solution

**Proctor is the automated test harness, evaluation engine, and continuous-assurance layer for
conversational AI.** We provide:

1. **Auto-generated, domain-tailored test suites** — describe your bot, we synthesize hundreds of
   realistic users (happy-path, edge, adversarial) tuned to your domain.
2. **Massively parallel execution** across voice (real phone calls) and chat (API/webhook).
3. **Statistically-grounded scoring** — not one run, but N runs with confidence intervals, so a
   "pass" is evidence, not luck.
4. **Regression gating** — wire us into CI/CD; every prompt/model change is scored against a
   baseline and blocked if it regresses safety or task success.
5. **An auditable trust record** — every result has transcript + audio + judge reasoning, retained
   per your compliance policy, exportable for regulators.

## 3. Who buys (segments & ICP)

| Segment | Example buyer | Pain | Willingness to pay |
|---|---|---|---|
| **Voice-agent platforms** (wedge) | Vapi, Retell, Bland, Synthflow + their customers | Their customers churn when bots break; they need QA to sell up-market | **High** — technical, feel pain daily |
| **Regulated enterprises** | Hospital systems, banks, insurers | Compliance & liability; a bad bot is a lawsuit | **Very high** — buy on risk reduction |
| **Contact-center AI buyers** | Enterprises replacing BPO with AI agents | Need to prove the AI is as good/safe as humans before cutover | High |
| **Horizontal chatbot teams** | Any SaaS shipping a support/sales bot | Prompt changes break things; no regression safety net | Medium (self-serve, land-and-expand) |

**Ideal Customer Profile (initial):** a company with ≥1 production conversational agent in a
**regulated or high-stakes** domain, a team actively iterating on prompts/models, and an existing
notion that "we really don't know how this behaves at scale." Beachhead = **AI voice-agent
vendors and their healthcare/fintech customers**, because (a) voice is our technical moat and
(b) they feel the pain most acutely and can't easily build this themselves.

## 4. Jobs-to-be-done

- **"Before I launch, prove my bot is safe and competent."** → Pre-launch certification run.
- **"Tell me what broke after my last prompt change."** → Regression run in CI.
- **"Give me something I can show my compliance officer / a regulator."** → Audit report.
- **"Continuously watch my production bot for drift."** → Scheduled monitoring + alerting.
- **"Benchmark my bot against competitors / against the human baseline."** → Benchmarking.

## 5. End-to-end business use case (fully worked)

**Customer:** *Northwind Health*, a telehealth company with an AI phone agent that schedules
appointments, handles refills, and triages symptoms. They push prompt changes weekly.

**Day 0 — Onboarding & consent.**
Northwind signs up. Because testing involves calling their own phone line and (optionally)
processing PHI, they complete **ownership verification** (we place a one-time code call to the
target number; an admin reads it back) and sign a **BAA** and a **Test Authorization** attesting
they own/control the target agent. This is the trust gate — see [doc 06](06-trust-security-compliance.md).

**Day 0 — Describe the bot.**
In the dashboard (or via API) they paste: *"Telehealth scheduling + triage voice agent. Books,
reschedules, cancels. Handles refills. Must triage urgent symptoms and advise ER/911 when
appropriate. Office hours Mon–Fri 8–5. Must never give diagnoses or dosages."* They attach an
optional **spec**: hard rules ("MUST escalate chest pain", "MUST NOT state a diagnosis").

**Day 0 — Generate suite.**
Proctor's persona generator produces a **120-persona suite** tailored to telehealth: scheduling
happy-paths, Spanish speakers, elderly/slow callers, rambling symptom-dumps, after-hours requests,
and adversarial probes (chest-pain triage, requests for a diagnosis, prompt injection, someone
trying to access another patient's record). The evaluator derives a **rubric** from the same
description + spec.

**Day 0 — Execute.**
Proctor places ~120 real calls to Northwind's agent (throttled, consented), each driven by a
synthetic patient. To get statistical confidence on the high-risk personas, the 15 safety-critical
ones are run **5× each** (see [doc 04 §4](04-scoring-and-math.md)). Total ≈ 190 calls, completed
in ~25 minutes across a concurrency pool.

**Minutes later — Evaluate.**
Each transcript is scored by an **ensemble of 3 judge models** against the rubric. Verdicts are
aggregated with **Wilson confidence intervals**; flaky personas (pass sometimes, fail sometimes)
are flagged. The system computes a **Bot Health Score (0–100)**, a **Safety Risk Score** (expected
harm cost), and a **per-dimension breakdown**.

**Result — The report.**
Northwind sees: *Overall Health 82/100 (±3). Task success 94% (CI 90–97%). **Safety: 2 Critical
failures** — in 2 of 5 chest-pain runs the agent booked a next-day appointment instead of advising
911. Here is the audio and transcript span for each. 1 High: agent disclosed appointment details
after weak identity verification. Coherence 9.1/10.* Every claim links to evidence.

**Day 7 — Regression.**
Northwind changes the triage prompt to fix the chest-pain bug. They push to staging; their CI calls
`POST /v1/runs` with the same suite pinned to the baseline. Proctor re-runs, computes a
**two-proportion test** vs. baseline, and reports: *chest-pain safety 0/5 → 5/5 fixed (significant,
p<0.01); BUT refill task-success dropped 96%→88% (significant regression).* CI **blocks the deploy**
because a safety gate and a task-success gate are configured. Northwind catches a self-inflicted
regression before it ships.

**Ongoing — Assurance.**
A nightly scheduled run (lightweight, 30 personas) monitors the production agent for drift and model
provider changes. If the health score drops >5 points or any Critical appears, PagerDuty fires.

**This loop — connect, generate, execute, evaluate, assure — is the product. Everything in the
other docs exists to make this loop fast, trustworthy, cheap, and scalable.**

## 6. Why now

- Conversational agents crossed from demo to production in 2024–2026; voice agents especially exploded.
- Regulators (FTC, EU AI Act, state consumer-protection) are starting to hold companies liable for AI behavior.
- Foundation-model providers push breaking changes; "my bot changed and I didn't touch it" is now common.
- LLM-as-judge matured enough to be a credible (and improvable) evaluation substrate.

## 7. Why us / why defensible

- **Voice is hard.** Real-time telephony + barge-in + turn-taking + accent handling is a serious
  engineering moat most QA tools won't cross. We start there and move down to chat (easy), not up.
- **Data compounds.** Every run teaches us failure taxonomies per domain, improving persona
  generation and judge calibration — a flywheel competitors can't copy without the data.
- **Trust is a moat.** SOC 2 + HIPAA + a clean consent/audit story is a 12–18 month barrier that
  gates the enterprise segment. We build it in from day one.
