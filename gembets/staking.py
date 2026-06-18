"""Kelly stake sizing — turn "+X% edge" into "bet £Y".

The Kelly fraction for a bet at decimal odds `o` with true win prob `p` is:

    f* = (p*o - 1) / (o - 1) = edge / (o - 1)      (edge = EV per unit = p*o - 1)

Full Kelly maximises long-run growth but is wildly volatile and unforgiving of
probability error, so we stake a FRACTION of it (quarter by default) and cap the
result at a small share of bankroll. A noisy model + a single-bet sample means
under-betting is far cheaper than over-betting — hence the conservative defaults.
Pure stdlib, unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StakePlan:
    stake: float              # £ to bet (rounded), after fraction + caps
    full_kelly: float         # full-Kelly fraction of bankroll
    fraction_used: float      # fraction of bankroll actually staked
    capped_by: str            # "", "max_fraction", "max_stake" or "min_stake"


def kelly_stake(fair_prob: float, decimal_odds: float, bankroll: float, *,
                fraction: float = 0.25, max_fraction: float = 0.05,
                max_stake: float | None = None, min_stake: float = 0.0) -> StakePlan:
    """Recommended stake for a value bet. Returns 0 stake if not +EV."""
    b = decimal_odds - 1.0
    if b <= 0 or bankroll <= 0:
        return StakePlan(0.0, 0.0, 0.0, "")
    full = (fair_prob * decimal_odds - 1.0) / b        # full-Kelly fraction
    if full <= 0:
        return StakePlan(0.0, max(full, 0.0), 0.0, "")  # no edge -> no bet

    frac = full * fraction
    capped = ""
    if frac > max_fraction:                            # never risk more than this share
        frac, capped = max_fraction, "max_fraction"
    stake = bankroll * frac
    if max_stake is not None and stake > max_stake:
        stake, capped = max_stake, "max_stake"
    if stake < min_stake:
        return StakePlan(0.0, full, 0.0, "min_stake")  # too small to bother
    return StakePlan(round(stake, 2), full, frac, capped)
