"""Cross-book cover mode: lock a boost by backing the OPPOSITE side(s) at other
bookies, instead of laying on an exchange.

When no exchange market exists (player props), you can still lock a boost by
backing every *other* outcome at a second bookmaker so that exactly one bet
wins whatever happens. With the boost at odds B (stake s0) and the cover
outcomes at odds C1..Ck, you stake each cover so all outcomes return the same R:

    R = s0 * B ;  cover_stake_i = R / C_i

Then profit = R - total_staked, identical whichever outcome wins. Writing the
combined book percentage as

    book_sum = 1/B + Σ 1/C_i

profit is positive  <=>  book_sum < 1  (a genuine arbitrage). The return on total
outlay is exactly (1/book_sum - 1). The boost pushes 1/B down; the lock exists
only if the other book's prices on the remaining outcomes are generous enough to
keep the whole sum under 1.

Pure/stdlib, unit-tested. The hard part (finding the opposite selection at
another book) lives in `complement()` + the matching layer; this is just the
maths that decides whether a given set of legs locks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Boost


@dataclass(frozen=True)
class CoverLeg:
    """One opposite-outcome bet at another bookie."""

    bookie: str
    selection: str
    odds: float


@dataclass
class CoverResult:
    """A boost + its cover legs, with the Dutching maths attached."""

    boost: Boost
    legs: list[CoverLeg]
    back_stake: float
    leg_stakes: list[float] = field(default_factory=list)
    total_stake: float = 0.0
    guaranteed_profit: float = 0.0      # same whichever outcome wins
    roi_pct: float = 0.0                # profit as % of total staked
    book_sum: float = 0.0               # Σ implied prob; < 1 => lock
    notes: list[str] = field(default_factory=list)

    @property
    def lock(self) -> bool:
        return bool(self.legs) and self.book_sum < 1.0


def rate_cover(boost: Boost, legs: list[CoverLeg], back_stake: float) -> CoverResult:
    """Stake the boost at `back_stake`; stake each cover to equalise the return."""
    if not legs:
        return CoverResult(boost=boost, legs=[], back_stake=back_stake,
                           notes=["no opposite price found at another book"])
    B = boost.boosted_odds
    R = back_stake * B                              # target return for every outcome
    leg_stakes = [R / leg.odds for leg in legs]
    total = back_stake + sum(leg_stakes)
    profit = R - total
    book_sum = 1.0 / B + sum(1.0 / leg.odds for leg in legs)

    res = CoverResult(
        boost=boost, legs=legs, back_stake=round(back_stake, 2),
        leg_stakes=[round(s, 2) for s in leg_stakes],
        total_stake=round(total, 2), guaranteed_profit=round(profit, 2),
        roi_pct=round(100.0 * profit / total, 2), book_sum=round(book_sum, 4),
    )
    if not res.lock:
        res.notes.append(f"book sum {book_sum*100:.1f}% > 100% -- no lock")
    return res


# --- complement: the opposite outcome(s) of a boost selection -----------------

_SUFFIX = {"yes": "no", "no": "yes"}


def complement(selection: str) -> list[str] | None:
    """Best-effort opposite selection text(s) to look up at other books.

    Returns a list because some markets need two covers (e.g. a 3-way result is
    covered by the two other results — but those we can't name without the teams,
    so we return None there). None means "couldn't derive a clean opposite".
    Heuristics cover the common BINARY props/markets where cover betting applies.
    """
    s = selection.strip().lower()

    # "... - yes" / "... - no"
    for k, v in _SUFFIX.items():
        if s.endswith(f"- {k}") or s.endswith(f"-{k}"):
            return [re.sub(rf"-\s*{k}$", f"- {v}", s)]

    # "both teams to score" (implicit yes) -> "both teams to score - no"
    if s in ("both teams to score", "btts"):
        return ["both teams to score - no"]

    # "N+ <thing>"  (1+ shot on target, 2+ goals, 3+ fouls) -> "under N <thing>"
    m = re.search(r"(\d+)\+\s+(.*)", s)
    if m:
        n, rest = int(m.group(1)), m.group(2)
        return [f"under {n} {rest}"]

    # "over X.5 <thing>" <-> "under X.5 <thing>"
    m = re.search(r"\bover\s+([\d.]+)\s+(.*)", s)
    if m:
        return [f"under {m.group(1)} {m.group(2)}"]
    m = re.search(r"\bunder\s+([\d.]+)\s+(.*)", s)
    if m:
        return [f"over {m.group(1)} {m.group(2)}"]

    # "to be carded" / "to be booked" -> "not ..."
    if "to be carded" in s or "to be booked" in s or "to be shown" in s:
        return ["not " + s]

    return None       # e.g. "anytime scorer", 3-way results -> no clean binary opposite
