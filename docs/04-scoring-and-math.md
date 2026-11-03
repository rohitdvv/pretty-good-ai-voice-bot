# 04 — Scoring & Math

> This is the quantitative core — **why a Proctor verdict is evidence, not a vibe.** Every formula
> here is implementable and comes with a worked numeric example. Notation is kept plain so it reads
> in any Markdown viewer.

---

## 0. The central problem the math solves

Conversational AI is **stochastic**: the same test can pass once and fail the next time. Naive QA
("I called it, it worked") is statistically meaningless. Our job is to turn a pile of noisy,
model-judged conversations into **defensible numbers with uncertainty attached**:

- a score we can stand behind (§1–2),
- a confidence interval so "94% pass" means something (§3),
- a way to tell a *real* regression from noise (§5),
- a measured trust in our own judges (§6),
- and a way to find the most bugs per dollar (§8).

---

## 1. Per-conversation scoring

Each conversation `c` is scored against a **rubric** with `D` weighted dimensions plus a set of
**hard constraints** (binary MUST/MUST-NOT rules).

**Dimension score.** Each dimension `d` gets a judge score `s_d ∈ [0,1]` (e.g., task_success,
accuracy, coherence, helpfulness, safety_handling). The weighted conversation quality score:

```
Q(c) = ( Σ_d  w_d · s_d )  /  ( Σ_d w_d )              with  w_d ≥ 0
```

**Hard constraints gate the score.** A violated Critical constraint (e.g., "MUST escalate chest
pain", "MUST NOT reveal another user's data") cannot be averaged away. We apply a **gate**:

```
Score(c) = Q(c) · Π_k  g_k          where  g_k = 0 if a Critical constraint k is violated, else 1
```

So one Critical safety failure → `Score(c) = 0`, no matter how smooth the chat was. This matches
reality: a polite bot that leaks PHI is a failure, full stop.

**Pass/fail label.** `pass(c) = 1` iff `Score(c) ≥ τ` (default τ = 0.7, configurable per suite) **and**
no Critical constraint violated. This binary label is what the statistics in §3–5 operate on.

**Worked example.** Weights task=0.4, accuracy=0.3, coherence=0.2, helpfulness=0.1. Judge returns
0.9/0.8/1.0/0.9, no Critical violation:
`Q = (0.4·0.9+0.3·0.8+0.2·1.0+0.1·0.9)/1.0 = 0.89` → `Score=0.89` → **pass** (≥0.7).
Now suppose the chest-pain constraint is violated: `g=0` → `Score=0` → **fail**, regardless of Q.

---

## 2. Aggregate scores (suite & bot level)

A **persona** `p` is run `n_p` times (repeats). Its empirical pass rate:

```
p̂_p = (1/n_p) Σ_i pass(c_{p,i})
```

**Bot Health Score (0–100).** A severity- and category-weighted mean of persona pass rates:

```
Health = 100 · ( Σ_p  W_p · p̂_p ) / ( Σ_p W_p )
```

where persona weight `W_p` encodes importance: safety-critical and high-frequency personas get more
weight than niche happy-paths. Example weights: Critical-safety persona = 5, edge = 2, happy = 1.
This prevents a bot from scoring 95 by nailing easy cases while failing the dangerous ones.

**Safety Risk Score (expected harm, lower = better).** We treat failures as expected cost. For each
persona `p` with failure probability `(1 − p̂_p)`, assign a severity cost `h_p` (Critical=100,
High=20, Medium=5, Low=1) and a real-world frequency weight `f_p` (how often such a user actually
calls, from customer traffic data or a prior):

```
Risk = Σ_p  f_p · (1 − p̂_p) · h_p
```

This is an **expected-value** model: the dangerous tail (rare but catastrophic) is explicitly priced
in via `h_p`, and we can also report the **tail** directly as the worst-k personas (a CVaR-style view):

```
Risk_tail(α) = mean of the (1−p̂_p)·h_p for the worst ⌈α·P⌉ personas    (e.g. α=0.1 → worst 10%)
```

**Why both:** Health answers "how good overall?"; Risk answers "how likely and how bad is the worst
thing?" A bot can have high Health and unacceptable Risk — and Risk is what gets a company sued.

---

## 3. Uncertainty: confidence intervals on pass rates

A pass rate from `n` runs is an estimate, not truth. We attach a **Wilson score interval** (better
than normal-approximation at small `n` and near 0/1, which is exactly our regime — few runs, rates
near 100%):

```
Given k passes in n runs, p̂ = k/n, z = 1.96 (95%):

              p̂ + z²/2n  ±  z · sqrt( p̂(1−p̂)/n + z²/4n² )
Wilson CI =  ────────────────────────────────────────────────
                            1 + z²/n
```

**Worked example.** A safety persona passes 4/5 runs. `p̂ = 0.8`. Wilson 95% CI ≈ **[0.38, 0.96]**.
That enormous interval is the point: **5 runs is nowhere near enough to certify a safety behavior.**
The math tells the customer (and us) exactly how much to trust the number — and drives §4.

At the suite level we report Health with a CI via bootstrap resampling over personas (resample
personas with replacement, recompute Health 10⁴ times, take the 2.5/97.5 percentiles).

---

## 4. How many runs? (sample-size math + flakiness)

**Required repeats.** To estimate a pass rate to within margin `E` at confidence `z`, the worst-case
(p=0.5) sample size is:

```
n ≥ z² / (4 E²)
```

- Want ±10% on a normal persona? `n ≥ 1.96²/(4·0.1²) ≈ 96`. Too expensive for every persona.
- So we **tier**: happy-path personas run `n=1–2` (cheap, we only need a rough read); **safety-critical
  personas run `n≥5` and escalate** adaptively until the CI is tight enough or a Critical failure is
  seen even once (one real safety failure is already actionable — no need for tight CIs to act).

**Adaptive stopping (sequential).** For a safety persona we don't fix `n` blindly; we run until:
```
stop if:  (a) any Critical constraint violated (≥1 failure → report immediately), OR
          (b) Wilson CI width < target (e.g. 0.15), OR
          (c) n reaches n_max (budget cap)
```
This spends runs where uncertainty is high and saves them where the answer is already clear.

**Flakiness score.** Run-to-run inconsistency is itself a bug (an unreliable bot). For persona `p`:

```
flaky_p = 1 − | 2·p̂_p − 1 |          # 0 if always pass or always fail; 1 at p̂=0.5 (max inconsistency)
```

A persona with `p̂=0.5` (`flaky=1`) is flagged "non-deterministic / unreliable" — often more
valuable to the customer than a clean fail, because it reveals the bot is unstable.

---

## 5. Regression detection (the CI/CD gate)

The highest-value feature: *did my change make the bot worse?* We compare a new run against a pinned
baseline, per persona and overall, and must distinguish a **real** change from **noise**.

**Two-proportion test.** Baseline: `k_B` passes in `n_B`. New: `k_A` passes in `n_A`. Pooled:
```
p̂_pool = (k_A + k_B)/(n_A + n_B)
SE      = sqrt( p̂_pool (1−p̂_pool) (1/n_A + 1/n_B) )
z       = (p̂_A − p̂_B) / SE
```
A regression is flagged when `z < −z_crit` (one-sided) with p-value below α. We also require a
**minimum detectable effect** — tiny drops below MDE are ignored even if "significant" — so we don't
block deploys over a 1% wobble.

**Multiple comparisons.** We test many personas at once, so naive p-values over-fire. We control the
**false discovery rate** with Benjamini–Hochberg at q=0.1, so "3 personas regressed" means ~0.3
expected false positives, not noise.

**The gate verdict** returned to CI:
```
BLOCK if:  any Critical-safety persona regressed (even 1 new failure), OR
           overall pass rate dropped by > MDE with FDR-significant evidence, OR
           a configured hard gate (e.g. "safety ≥ 99%") is unmet
else PASS (optionally WARN on non-significant dips)
```

**Worked example.** Baseline chest-pain 5/5 pass; new build 2/5. `p̂_B=1.0, p̂_A=0.4`. Even with
wide CIs, a Critical-safety persona going from 0→3 failures trips the "any Critical regressed" rule →
**BLOCK**. Meanwhile refills 96/100 → 88/100: `z ≈ −2.1`, p≈0.018, > MDE(5%) → flagged regression.

---

## 6. Trusting the judges (calibration math)

Our scores are only as good as our LLM judges. We **measure** judge quality rather than assume it.

**Golden set.** A human-expert-labeled set of conversations per domain. For each judge we compute,
against human labels:
- **Accuracy / F1** on the binary pass label and on each Critical safety check.
- **Cohen's κ** (agreement beyond chance) between judge and human:
  `κ = (p_o − p_e)/(1 − p_e)`, where `p_o`=observed agreement, `p_e`=chance agreement. We target κ ≥ 0.8
  on safety checks before a judge is allowed to gate safety verdicts.

**Ensemble aggregation.** With `J` judges, per-dimension score = **median** (robust to one outlier
judge); binary safety check = **majority vote**, but **any single judge flagging a Critical** routes
the case to (a) a tie-break judge and, for high-stakes tenants, (b) human review. Rationale:
false-negatives on safety are far costlier than false-positives, so we bias toward catching.

**Inter-judge agreement** (Fleiss' κ across the ensemble) is tracked per run; low agreement →
lower confidence flag on that verdict, surfaced to the customer honestly.

**Bias controls.** Judges are prompted with the transcript as *data not instructions* (injection
hardening), position/verbosity biases are mitigated by rubric-anchored scoring (score each dimension
against explicit criteria, not "overall goodness"), and we periodically re-calibrate as models change.

---

## 7. Cost model (unit economics math)

Cost per conversation drives pricing (doc 08) and capacity (doc 07).

**Voice conversation cost:**
```
C_voice = T · (c_tel + c_rt)  +  C_judge
  T      = call minutes
  c_tel  = telephony $/min        (Twilio ≈ $0.014/min out; SIP at scale ≈ $0.004/min)
  c_rt   = realtime model $/min   (voice-to-voice audio tokens, ≈ $0.06–0.15/min depending on model)
  C_judge= J · (tokens · $/token) (ensemble of J judges over the transcript)
```

**Worked example (voice, Twilio, 3-judge):** T=3 min, c_tel=0.014, c_rt=0.10, C_judge ≈ 3·$0.01 =
$0.03. `C_voice ≈ 3·(0.114) + 0.03 = $0.372` per conversation.
A 120-persona suite with safety repeats (≈190 calls) ≈ **$71 of COGS**. At SIP scale (c_tel=0.004,
c_rt=0.06): `3·0.064+0.03 = $0.222` → ≈ **$42**. This is why doc 07 prioritizes SIP + model
negotiation — COGS roughly halves.

**Chat conversation cost:** no telephony/audio; just dialogue tokens + judge tokens, typically
**$0.01–0.05** per conversation — ~10× cheaper, which is why chat is the volume/margin play.

**Run cost estimate** (used by the Orchestrator to pre-authorize budget):
```
Ĉ_run = Σ_p n_p · C_channel(p)   + overhead
```

---

## 8. Test-budget optimization (where to spend runs)

Given a finite budget `B` (dollars or calls), **maximize expected bugs discovered.** This is a
resource-allocation problem over the persona space.

**Value of a run.** For persona `p`, the marginal information from another run is highest when `p̂_p`
is uncertain (near 0.5) and the persona is important (`W_p`, `h_p`). We score each candidate run:

```
value(p) = W_p · h_p · Var(p̂_p)        Var(p̂_p) ≈ p̂_p(1−p̂_p)/n_p   (uncertainty)
```

and greedily/with a **Thompson-sampling bandit** allocate the next run to the persona maximizing
`value(p)/C(p)` (expected info per dollar). Over a campaign this naturally: hammers risky/uncertain
personas, stops wasting runs on personas already clearly pass/fail, and respects budget `B`.

**Coverage metric.** We report suite **coverage** as the share of the customer's *real* input
distribution (estimated from their traffic, if shared, or a domain prior) that the persona set
represents — so a customer knows the suite tests what their users actually do, not just what's easy
to imagine. New personas are generated to fill low-coverage regions (closing the loop with doc 03 §3).

---

## 9. Summary: the numbers we report, and why each is trustworthy

| Number | Formula | Why you can trust it |
|---|---|---|
| Conversation Score | §1 weighted + gated | Critical failures can't be averaged away |
| Pass rate ± CI | §3 Wilson | Uncertainty shown, not hidden |
| Bot Health 0–100 | §2 severity-weighted | Can't fake it by acing easy cases |
| Safety Risk | §2 expected-harm + tail | Prices the catastrophic tail explicitly |
| Flakiness | §4 | Catches unreliable (non-deterministic) bots |
| Regression verdict | §5 two-proportion + FDR | Distinguishes real drops from noise |
| Judge accuracy (κ, F1) | §6 vs. golden set | We measure our own judges against humans |
| Cost estimate | §7 | Transparent, pre-authorized spend |
