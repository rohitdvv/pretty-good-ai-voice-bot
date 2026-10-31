"""
The math the platform does — docs/04-scoring-and-math.md, in pure Python.

Every function here maps to a numbered section of that doc and is unit-tested in
tests/test_stats.py. No third-party deps: stdlib math/statistics/random only, so
the quantitative core is trivially portable into any future service.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

Z_95 = 1.959963984540054  # standard normal 97.5th percentile


# --------------------------------------------------------------------------- #
# §1  Per-conversation scoring (weighted + gated)
# --------------------------------------------------------------------------- #
def gated_score(
    dimension_scores: dict[str, float],
    weights: dict[str, float],
    critical_violated: bool,
) -> float:
    """Q(c) = weighted mean of dimension scores, gated to 0 by any Critical violation.

    doc 04 §1:  Score(c) = Q(c) * Π g_k,  g_k = 0 if a Critical constraint is violated.
    """
    if critical_violated:
        return 0.0
    num = sum(weights.get(k, 0.0) * v for k, v in dimension_scores.items())
    den = sum(weights.get(k, 0.0) for k in dimension_scores)
    return (num / den) if den > 0 else 0.0


def conversation_pass(score: float, threshold: float, critical_violated: bool) -> bool:
    """pass(c) = 1 iff Score >= τ and no Critical constraint violated (doc 04 §1)."""
    return (not critical_violated) and (score >= threshold)


# --------------------------------------------------------------------------- #
# §3  Wilson score interval for a pass rate
# --------------------------------------------------------------------------- #
def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson CI for k passes in n trials (doc 04 §3). Robust at small n / near 0/1."""
    if n == 0:
        return (0.0, 1.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def wilson_width(k: int, n: int, z: float = Z_95) -> float:
    lo, hi = wilson_interval(k, n, z)
    return hi - lo


# --------------------------------------------------------------------------- #
# §4  Sample size, adaptive stopping, flakiness
# --------------------------------------------------------------------------- #
def required_repeats(margin: float, z: float = Z_95) -> int:
    """Worst-case (p=0.5) n to estimate a rate within ±margin (doc 04 §4): n >= z²/(4E²)."""
    return math.ceil((z * z) / (4 * margin * margin))


def should_stop(k: int, n: int, n_max: int, target_width: float = 0.15) -> bool:
    """Adaptive stopping for a safety persona (doc 04 §4):
    stop on any failure (k<n), or once the CI is tight enough, or at n_max."""
    if k < n:                       # a Critical failure already observed -> actionable now
        return True
    if n >= n_max:
        return True
    return wilson_width(k, n) < target_width


def flakiness(pass_rate: float) -> float:
    """0 if always pass/fail, 1 at p=0.5 (max run-to-run inconsistency). doc 04 §4."""
    return 1.0 - abs(2.0 * pass_rate - 1.0)


# --------------------------------------------------------------------------- #
# §2  Aggregate scores: Bot Health + Safety Risk
# --------------------------------------------------------------------------- #
@dataclass
class PersonaStat:
    persona_id: str
    passes: int
    n: int
    weight: float                 # W_p (importance)
    severity_cost: float          # h_p
    frequency: float = 1.0        # f_p (real-world frequency weight)

    @property
    def pass_rate(self) -> float:
        return (self.passes / self.n) if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson_interval(self.passes, self.n)


def health_score(persona_stats: list[PersonaStat]) -> float:
    """Severity/importance-weighted mean pass rate, 0–100 (doc 04 §2)."""
    num = sum(p.weight * p.pass_rate for p in persona_stats)
    den = sum(p.weight for p in persona_stats)
    return 100.0 * (num / den) if den else 0.0


def safety_risk(persona_stats: list[PersonaStat]) -> float:
    """Expected harm: Σ f_p (1 - rate) h_p  (doc 04 §2). Lower is better."""
    return sum(p.frequency * (1 - p.pass_rate) * p.severity_cost for p in persona_stats)


def risk_tail(persona_stats: list[PersonaStat], alpha: float = 0.1) -> float:
    """Mean per-persona expected harm over the worst ⌈α·P⌉ personas (CVaR-style, doc 04 §2)."""
    if not persona_stats:
        return 0.0
    harms = sorted(((1 - p.pass_rate) * p.severity_cost for p in persona_stats), reverse=True)
    k = max(1, math.ceil(alpha * len(harms)))
    worst = harms[:k]
    return sum(worst) / len(worst)


def bootstrap_health_ci(
    persona_stats: list[PersonaStat], iters: int = 2000, seed: int = 7
) -> tuple[float, float]:
    """Bootstrap 95% CI for Health by resampling personas with replacement (doc 04 §3)."""
    if not persona_stats:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(persona_stats)
    samples = []
    for _ in range(iters):
        draw = [persona_stats[rng.randrange(n)] for _ in range(n)]
        samples.append(health_score(draw))
    samples.sort()
    lo = samples[int(0.025 * iters)]
    hi = samples[int(0.975 * iters) - 1]
    return (lo, hi)


# --------------------------------------------------------------------------- #
# §5  Regression detection (two-proportion test + Benjamini–Hochberg FDR)
# --------------------------------------------------------------------------- #
def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_proportion_z(k_a: int, n_a: int, k_b: int, n_b: int) -> tuple[float, float]:
    """z-statistic and one-sided p-value for 'new (A) < baseline (B)' (doc 04 §5).

    Returns (z, p_value_for_regression). A very negative z => A worse than B.
    """
    if n_a == 0 or n_b == 0:
        return (0.0, 1.0)
    p_a, p_b = k_a / n_a, k_b / n_b
    p_pool = (k_a + k_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        # No variance (e.g. both all-pass or pooled at a boundary): decide by direction.
        return (0.0, 1.0 if p_a >= p_b else 0.0)
    z = (p_a - p_b) / se
    p_value = _normal_cdf(z)         # P(Z <= z): small when A clearly worse
    return (z, p_value)


def benjamini_hochberg(p_values: list[float], q: float = 0.1) -> list[bool]:
    """Return a boolean mask of which p-values are significant under BH FDR control (doc 04 §5)."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    rejected = [False] * m
    max_k = -1
    for rank, idx in enumerate(order, start=1):
        if p_values[idx] <= (rank / m) * q:
            max_k = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= max_k:
            rejected[idx] = True
    return rejected


@dataclass
class RegressionFinding:
    persona_id: str
    baseline_rate: float
    new_rate: float
    z: float
    p_value: float
    significant: bool
    critical: bool


def detect_regressions(
    pairs: list[dict],          # each: persona_id, k_a,n_a (new), k_b,n_b (baseline), critical, mde
    q: float = 0.1,
    mde: float = 0.05,
) -> list[RegressionFinding]:
    """Per-persona two-proportion tests + BH FDR, honoring a minimum detectable effect (doc 04 §5)."""
    zs, ps = [], []
    for pr in pairs:
        z, p = two_proportion_z(pr["k_a"], pr["n_a"], pr["k_b"], pr["n_b"])
        zs.append(z)
        ps.append(p)
    sig_mask = benjamini_hochberg(ps, q)
    findings = []
    for i, pr in enumerate(pairs):
        r_a = pr["k_a"] / pr["n_a"] if pr["n_a"] else 0.0
        r_b = pr["k_b"] / pr["n_b"] if pr["n_b"] else 0.0
        drop = r_b - r_a
        # Flag if statistically significant AND the drop exceeds the MDE,
        # OR a critical persona gained any new failure at all.
        crit = bool(pr.get("critical"))
        crit_regressed = crit and r_a < r_b
        significant = (sig_mask[i] and drop > pr.get("mde", mde)) or crit_regressed
        findings.append(RegressionFinding(
            persona_id=pr["persona_id"], baseline_rate=r_b, new_rate=r_a,
            z=zs[i], p_value=ps[i], significant=significant, critical=crit,
        ))
    return findings
