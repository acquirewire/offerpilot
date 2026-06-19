"""Turn a RatedBoost into a step-by-step "what to actually do" in pounds.

The rater says a boost is worth placing; this module says *exactly how*: how
much to stake, how much to lay, the liability to have in your exchange wallet,
and the profit in £ under each outcome. Pure/stdlib so it's unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import RatedBoost


@dataclass(frozen=True)
class LayPlan:
    """Concrete, pounds-and-pence betting instructions for one rated boost."""

    back_stake: float       # £ to back at the bookie
    back_odds: float        # boosted price
    back_returns: float     # £ returned if the back wins (stake * odds)
    lay_stake: float        # £ to lay on the exchange
    lay_odds: float
    liability: float        # £ the exchange ringfences if the lay loses
    profit_if_wins: float   # net £ across both bets if the selection wins
    profit_if_loses: float  # net £ across both bets if it loses
    guaranteed: float       # the locked figure (min of the two)
    exchange: str
    runner: str | None

    def steps(self) -> list[str]:
        """Human-readable numbered steps, all amounts in £."""
        return [
            f"1. BACK £{self.back_stake:,.2f} on the boost @ {self.back_odds:.2f} "
            f"at the bookie  (returns £{self.back_returns:,.2f} if it wins)",
            f"2. LAY  £{self.lay_stake:,.2f} on \"{self.runner or 'the selection'}\" "
            f"@ {self.lay_odds:.2f} on {self.exchange}  "
            f"(needs £{self.liability:,.2f} liability in your wallet)",
            f"3a. If it WINS:  bookie pays you, exchange takes the lay  -> "
            f"net £{self.profit_if_wins:+,.2f}",
            f"3b. If it LOSES: you lose the back, exchange pays the lay  -> "
            f"net £{self.profit_if_loses:+,.2f}",
            f"=> Guaranteed profit either way: £{self.guaranteed:+,.2f}"
            + ("" if self.guaranteed >= 0 else "  (value bet, not risk-free)"),
        ]

    def as_text(self) -> str:
        return "\n".join(self.steps())


def plan(rated: RatedBoost) -> LayPlan | None:
    """Build a LayPlan from a rated boost, or None if it couldn't be matched."""
    if rated.quote is None:
        return None
    return LayPlan(
        back_stake=round(rated.back_stake, 2),
        back_odds=rated.boost.boosted_odds,
        back_returns=round(rated.back_stake * rated.boost.boosted_odds, 2),
        lay_stake=rated.lay_stake,
        lay_odds=rated.quote.lay_odds,
        liability=rated.liability,
        profit_if_wins=rated.profit_if_wins,
        profit_if_loses=rated.profit_if_loses,
        guaranteed=round(min(rated.profit_if_wins, rated.profit_if_loses), 2),
        exchange=rated.quote.exchange,
        runner=rated.quote.runner,
    )
