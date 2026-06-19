"""Value-rating: is a bookie boost genuinely +EV vs the true price?

The matched-lay approach (rating.py) only works on boosts you can lay. Most
bookie "price boosts" are player props/combos you CAN'T lay — but you can still
ask whether the boosted price beats the *true* probability. The cleanest source
of a margin-free true price is the exchange: it's a market, so its price carries
no bookmaker overround. We take the exchange back/lay MIDPOINT as fair.

For a boost at decimal price B with fair price F (=> true prob p = 1/F):

    EV per £1 staked = p*B - 1 = B/F - 1          (the edge)
    Kelly fraction   = (p*B - 1) / (B - 1)        (fraction of bankroll, full Kelly)

We stake a FRACTION of Kelly (quarter by default) because: the fair estimate is
noisy, and a single tournament is a tiny sample where variance dominates. A
boost is only flagged when the edge clears a margin big enough to survive the
fair-price uncertainty. Pure/stdlib — unit-tested.

Honest limits: this is NOT risk-free (you lose individual bets; profit only
emerges over many genuinely-+EV bets), it needs the exchange to actually price
the selection (many props it won't), and +EV betting still gets accounts limited.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Boost, ExchangeQuote


def fair_odds(quote: ExchangeQuote) -> float:
    """Margin-free fair decimal odds = inverse of the mean back/lay probability.

    Uses the back/lay midpoint when both are present (best estimate); falls back
    to the lay price alone, which is slightly ABOVE fair and so understates the
    edge — a safe, conservative bias.
    """
    if quote.back_odds and quote.back_odds > 1.0:
        p = (1.0 / quote.back_odds + 1.0 / quote.lay_odds) / 2.0
        return 1.0 / p
    return quote.lay_odds


@dataclass
class ValueBet:
    """A boost judged against the exchange's fair price."""

    boost: Boost
    fair: float                 # fair decimal odds used
    edge_pct: float             # (B/F - 1) * 100; >0 means genuinely +EV
    ev_per_pound: float         # expected £ profit per £1 staked
    kelly_stake: float          # suggested stake (fractional Kelly, rounded)
    exchange: str | None
    notes: list[str]

    @property
    def positive(self) -> bool:
        return self.edge_pct > 0


def rate_value(boost: Boost, quote: ExchangeQuote | None, *, bankroll: float,
               kelly_fraction: float = 0.25, min_edge_pct: float = 2.0) -> ValueBet:
    """Rate a boost's value vs the exchange fair price.

    `kelly_fraction` scales the full-Kelly stake (0.25 = quarter Kelly).
    `min_edge_pct` is the edge below which we stake nothing (noise floor).
    A None quote => the exchange couldn't price it: edge unknown, stake 0.
    """
    B = boost.boosted_odds
    if quote is None:
        return ValueBet(boost=boost, fair=0.0, edge_pct=0.0, ev_per_pound=0.0,
                        kelly_stake=0.0, exchange=None,
                        notes=["no exchange price -- can't verify value"])

    F = fair_odds(quote)
    p = 1.0 / F
    ev = p * B - 1.0                       # expected profit per £1
    edge_pct = 100.0 * ev
    notes: list[str] = [f"fair {F:.2f} vs boost {B:.2f}"]

    stake = 0.0
    if edge_pct >= min_edge_pct and B > 1.0:
        kelly = (p * B - 1.0) / (B - 1.0)          # full-Kelly fraction
        stake = max(0.0, bankroll * kelly * kelly_fraction)
    elif 0 < edge_pct < min_edge_pct:
        notes.append(f"edge +{edge_pct:.1f}% below {min_edge_pct:.0f}% floor -- skip")

    return ValueBet(boost=boost, fair=round(F, 3), edge_pct=round(edge_pct, 2),
                    ev_per_pound=round(ev, 4), kelly_stake=round(stake, 2),
                    exchange=quote.exchange, notes=notes)
