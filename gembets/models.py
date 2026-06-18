"""Data types for the gem-bet finder.

The market snapshot flows in from the odds API; the GemBet flows out to ntfy.

  * BookLine        -- one bookmaker's full price set for ONE market on a
                       fixture (e.g. [2.10, 3.40, 3.55] for Home/Draw/Away).
                       We need the *whole* market per book to remove that book's
                       margin (de-vig) before anything can be compared.
  * MarketSnapshot  -- every book's BookLine for one fixture+market at one
                       moment, plus the outcome labels they line up with.
  * GemBet          -- the unified alert emitted by EITHER detector: the
                       selection, the price, both probabilities, the edge, and
                       the specific quantitative reason it was flagged.

Identity of a gem is (fixture, market, selection, book, rounded-odds) lower-
cased, so the same edge re-seen on the next tick is recognised and not re-spammed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookLine:
    """One bookmaker's decimal prices for every outcome of a single market.

    `decimals` is positional and lines up with the snapshot's `labels`, e.g.
    labels ("Home","Draw","Away") -> decimals (2.10, 3.40, 3.55).
    """

    book: str                       # "pinnacle", "bet365", ...
    decimals: tuple[float, ...]     # decimal odds, one per outcome, in label order


@dataclass(frozen=True)
class MarketSnapshot:
    """All books' prices for one fixture+market, captured together."""

    fixture: str                    # "Brighton vs Aston Villa"
    market: str                     # "1X2" | "Over/Under 2.5" | "BTTS"
    labels: tuple[str, ...]         # ("Home","Draw","Away") | ("Over","Under") | ("Yes","No")
    lines: tuple[BookLine, ...]
    kickoff: str | None = None      # ISO time, for context in the alert

    def quotes_per_book(self) -> dict[str, list[float]]:
        """{book: [decimal per outcome]} — the shape the maths core consumes."""
        return {ln.book: list(ln.decimals) for ln in self.lines
                if len(ln.decimals) == len(self.labels)}


@dataclass
class GemBet:
    """A flagged value/mispriced bet, ready to format into a notification."""

    fixture: str
    market: str                     # e.g. "1X2 - Away" or "K. Mitoma Over 1.5 Fouls Won"
    selection: str                  # the human outcome, e.g. "Away" / "Over 1.5"
    book: str                       # which bookmaker offers the gem price
    decimal_odds: float             # the price you'd take
    implied_prob: float             # the book's margin-free-equivalent prob (1/decimal)
    fair_prob: float                # our estimate of the TRUE prob (consensus or model)
    edge: float                     # EV per 1 unit staked = fair_prob*decimal - 1
    kind: str                       # "outlier" | "statedge"
    reason: str                     # the quantitative justification shown in the push
    notes: list[str] = field(default_factory=list)
    kickoff: str | None = None

    def key(self) -> str:
        return "|".join(s.strip().lower() for s in (
            self.fixture, self.market, self.selection, self.book,
            f"{self.decimal_odds:.2f}"))

    @property
    def edge_pct(self) -> float:
        return self.edge * 100.0
