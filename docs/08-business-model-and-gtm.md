# 08 — Business Model & Go-To-Market

## 1. How we make money

A **usage + subscription hybrid**, because our COGS is usage-driven (calls/tokens) but our value is
continuous (regression assurance = a subscription reason to stay).

| Plan | Price (illustrative) | Includes | Target |
|---|---|---|---|
| **Free / PLG** | $0 | 1 target, chat only, 50 conversations/mo, community suites | Developers, trials |
| **Starter** | $99/mo | Chat + limited voice, 1k conversations/mo, 3 targets, CI gate | Small teams, self-serve |
| **Growth** | $499–$1.5k/mo | Voice + chat, 10k convos/mo, scheduling/monitoring, webhooks, SSO | Scaling startups |
| **Enterprise** | $30k–$250k/yr | In-VPC data plane, HIPAA/BAA, SLA, human-review tier, custom suites, support | Regulated enterprises |
| **Overage** | metered | per-conversation above plan (voice ~$0.75, chat ~$0.08) | All paid plans |

Pricing is anchored to **value, not COGS**: catching one bad-refund bug or one HIPAA disclosure is
worth far more than a month's subscription. Overage prices (voice ~$0.75) sit ~2× COGS (~$0.37→$0.22),
preserving **75–85% gross margin** once SIP + model migrations land (doc 07 §3).

## 2. Unit economics (illustrative)

- **COGS/voice conversation:** ~$0.22 at scale; chat ~$0.02 (doc 04 §7).
- **Gross margin:** ~80% blended (chat-heavy customers push it higher).
- **ACV targets:** self-serve $1–6k; mid-market $15–40k; enterprise $50–250k.
- **CAC payback:** < 12 months target; PLG + voice-platform partnerships keep CAC low.
- **Net revenue retention:** target >120% — land on one bot, expand to every bot + more channels +
  continuous monitoring. The regression/assurance use case is inherently expansionary.

## 3. TAM / SAM / SOM (sizing logic)

- **TAM:** every organization deploying a conversational AI agent — millions of bots across support,
  sales, healthcare, fintech, etc. Software-testing + conversational-AI platform spend is a
  multi-billion-dollar envelope and growing with AI-agent adoption.
- **SAM (3–5 yr):** regulated/high-stakes voice + chat agents in US/EU — tens of thousands of orgs,
  each with multiple bots and recurring assurance spend.
- **SOM (24 mo):** AI voice-agent platforms + their healthcare/fintech customers (the beachhead) —
  a few hundred logos is a strong early business given $15–40k ACVs.

(Keep these as logic, not false precision; refine with bottoms-up data as design partners land.)

## 4. Go-to-market motion

**Wedge: AI voice-agent platforms (Vapi, Retell, Bland, Synthflow, etc.) and their customers.**
- They feel the pain daily (their customers churn when bots break) and can't easily build rigorous
  eval themselves. Partner/embed: "QA powered by Proctor" as a value-add they resell.
- Land with a **free, jaw-dropping pre-launch report** (connect a number, 10 minutes, here's every
  way your bot breaks). The report *is* the sales pitch — evidence sells itself.

**Expand:**
1. One bot → all their bots.
2. Pre-launch test → **continuous regression gate in CI** (the sticky, recurring value).
3. Voice → chat → new channels.
4. Team seats → org-wide + compliance/audit buyers.

**Two parallel funnels:**
- **PLG self-serve** (free → Starter → Growth) for the long tail of chatbot teams.
- **Enterprise sales** (design partners in healthcare/fintech, land on compliance + liability).

## 5. Moat (why this compounds, recap of doc 01 §7)

1. **Voice engineering** barrier (real-time telephony is hard; we start at the hard end).
2. **Data flywheel** — failure taxonomies per domain improve persona generation and judge
   calibration; more runs → better product → more runs.
3. **Trust/compliance** — SOC 2 + HIPAA + clean consent/audit is a 12–18 mo moat gating enterprise.
4. **Workflow lock-in** — once we're the CI gate blocking bad deploys, ripping us out means shipping
   blind. That's the stickiest position in dev tooling.

## 6. Key risks & honest mitigations

| Risk | Mitigation |
|---|---|
| Foundation-model vendors ship their own eval tooling | We're cross-provider, voice-first, and own the trust/compliance + CI-gate workflow they won't prioritize |
| "LLM-judge isn't trustworthy" objection | We *measure* judge accuracy vs. humans (κ, F1) and show it — turning the objection into a differentiator (doc 04 §6) |
| COGS (voice is expensive) | SIP + model migration halves it; chat is the high-margin volume play (doc 07 §3) |
| Legal exposure from calling | Hard consent gate + ownership verification + rate limits (doc 06) |
| Long enterprise sales cycles | PLG + voice-platform partnerships fund the business while enterprise matures |
