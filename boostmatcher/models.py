"""Data types for the boost matcher.

Three units flow through the pipeline:

  * Boost          -- one enhanced selection scraped off a bookie boost page.
  * ExchangeQuote  -- the best lay price + available liquidity for that
                      selection on one exchange, at one moment.
  * RatedBoost     -- a Boost paired with its best exchange quote and the EV
                      maths (lay stake, the two outcome profits, the rating).

Identity of a boost is (bookie, event, market, selection) lower-cased, so the
same superboost re-scraped on the next tick is recognised and not re-alerted.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Boost:
    """One enhanced-odds selection on a bookmaker's boost page."""

    bookie: str                 # "skybet", "bet365", ...
    event: str                  # "England v USA"
    market: str                 # "Match Result", "Anytime Scorer", ...
    selection: str              # "England to win"
    boosted_odds: float         # decimal price you BACK at (the enhanced one)
    original_odds: float | None = None   # pre-boost price, when the page shows it
    max_stake: float | None = None       # bookie cap on the boost, if stated
    url: str | None = None
    # Free-text the matcher uses to find the exchange runner. Often the same as
    # selection, but kept separate so a scraper can attach hints (team ids etc).
    match_hint: str | None = None

    def key(self) -> str:
        return "|".join(
            s.strip().lower() for s in (self.bookie, self.event, self.market, self.selection)
        )


@dataclass(frozen=True)
class ExchangeQuote:
    """Best available prices for a selection on one exchange, right now.

    `lay_odds` drives the matched-lay maths; `back_odds` (when present) lets the
    value mode estimate the margin-free fair price as the back/lay midpoint.
    """

    exchange: str               # "betfair" | "smarkets"
    lay_odds: float             # decimal price you LAY at
    available: float            # liquidity (£) offered at lay_odds (the backers' stake)
    commission: float           # exchange commission on net winnings, e.g. 0.02
    runner: str | None = None   # the exchange runner name we matched to (for audit)
    market_id: str | None = None
    back_odds: float | None = None   # best price available to BACK (for fair mid)


@dataclass
class RatedBoost:
    """A boost matched to its best exchange quote, with the EV maths attached."""

    boost: Boost
    quote: ExchangeQuote | None         # None => couldn't be matched/laid
    back_stake: float                   # the stake the maths was run for
    lay_stake: float = 0.0              # stake to lay so both outcomes are equal
    liability: float = 0.0              # exchange liability if the lay loses
    profit_if_wins: float = 0.0         # net £ if the backed selection wins
    profit_if_loses: float = 0.0        # net £ if it loses (lay side cashes)
    rating: float = 0.0                 # locked profit as % of back_stake (the rank key)
    notes: list[str] = field(default_factory=list)

    @property
    def lockable(self) -> bool:
        """True if BOTH outcomes are non-negative — a guaranteed (risk-free) lock."""
        return self.quote is not None and min(self.profit_if_wins, self.profit_if_loses) >= 0
