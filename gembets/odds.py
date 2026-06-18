"""The maths core: odds conversion, margin removal, consensus, EV, and a small
Poisson for the goal/foul/card models. Pure stdlib — no numpy/scipy — so the
whole edge engine is unit-testable with no install and runs anywhere the bot does.

The one subtlety that trips people up: you can NEVER compare a book's raw implied
probability to anything, because it has the bookmaker's margin (vig/overround)
baked in. The flow is always:

    book prices --(devig)--> fair probs --(median across books)--> consensus
    consensus fair prob  vs  the offered price  -->  EV / edge

`evaluate_value` is the single chokepoint both detectors call to decide "is this
price generous enough to flag?".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median


# ---------------------------------------------------------------- conversions

def american_to_decimal(american: float) -> float:
    """+250 -> 3.50, -120 -> 1.833. (Odds APIs vary; normalise everything to decimal.)"""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_implied(decimal_odds: float) -> float:
    """Raw implied probability — STILL includes the book's margin. Don't compare raw."""
    return 1.0 / decimal_odds


def implied_to_decimal(prob: float) -> float:
    return 1.0 / prob


# ------------------------------------------------------------------- de-vig

def market_margin(decimals: list[float]) -> float:
    """Overround as a fraction: 0.052 == a 5.2% margin baked into this market."""
    return sum(decimal_to_implied(o) for o in decimals) - 1.0


def devig_proportional(decimals: list[float]) -> list[float]:
    """Strip a book's margin from a COMPLETE market so the probs sum to 1.0.

    Proportional ("multiplicative") method: divide each raw implied prob by the
    overround. Simple, robust, and unbiased enough for spotting outliers. (A
    `power`/Shin de-vig shaves favourite-longshot bias further; proportional is
    the right default and what we test against.)
    """
    raw = [decimal_to_implied(o) for o in decimals]
    overround = sum(raw)
    if overround <= 0:
        raise ValueError("non-positive overround")
    return [p / overround for p in raw]


def consensus_fair_prob(quotes_per_book: dict[str, list[float]], outcome_index: int) -> float:
    """A vig-free consensus probability for one outcome, robust to a bad book.

    De-vig EACH book independently (so one wide/erroring book can't poison the
    pool), then take the MEDIAN fair prob across books. Median, not mean, so a
    single fat-fingered or stale line doesn't drag the consensus — the very
    outlier we're hunting must not move the baseline it's measured against.
    """
    fair = []
    for decimals in quotes_per_book.values():
        if len(decimals) <= outcome_index or any(o <= 1.0 for o in decimals):
            continue
        fair.append(devig_proportional(decimals)[outcome_index])
    if not fair:
        raise ValueError("no usable quotes for consensus")
    return median(fair)


# ------------------------------------------------------------------- value / EV

@dataclass
class ValueSignal:
    has_edge: bool
    edge: float                 # EV per 1 unit staked = fair_prob*decimal - 1
    fair_prob: float
    offered_prob: float         # 1/offered_decimal (the book's implied)
    offered_decimal: float

    @property
    def lift_vs_market(self) -> float:
        """How much higher the payout is than a fair price would give (e.g. 0.14 = 14%)."""
        return (self.fair_prob - self.offered_prob) / self.offered_prob


def evaluate_value(offered_decimal: float, fair_prob: float, *, min_edge: float = 0.04) -> ValueSignal:
    """Is `offered_decimal` generous vs a `fair_prob` we believe?

    EV per unit = fair_prob * offered_decimal - 1. Positive EV means the price
    pays more than the true odds warrant. We require EV >= min_edge to flag, a
    noise floor that absorbs consensus/model error (4% is a sane default).
    """
    ev = fair_prob * offered_decimal - 1.0
    return ValueSignal(
        has_edge=ev >= min_edge,
        edge=ev,
        fair_prob=fair_prob,
        offered_prob=decimal_to_implied(offered_decimal),
        offered_decimal=offered_decimal,
    )


# ------------------------------------------------------------------- Poisson

def poisson_pmf(k: int, mu: float) -> float:
    """P(X = k) for a Poisson(mu) count. Stdlib; mu must be > 0."""
    if k < 0:
        return 0.0
    return math.exp(-mu) * mu ** k / math.factorial(k)


def poisson_cdf(k: int, mu: float) -> float:
    """P(X <= k)."""
    return sum(poisson_pmf(i, mu) for i in range(0, k + 1))


def prob_over_line(expected: float, line: float) -> float:
    """P(count > line) for a Poisson-distributed count of discrete events.

    Betting 'Over 1.5' wins on 2+; 'Over 4.5' wins on 5+. So with an integer
    threshold `k = floor(line)`, the over wins on X >= k+1, i.e. 1 - P(X <= k).
    """
    if expected <= 0:
        return 0.0
    k = math.floor(line)
    return 1.0 - poisson_cdf(k, expected)
