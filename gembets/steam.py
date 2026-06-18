"""Detector D: line-movement / "steam" — a free, time-series gem.

When sharp money moves a price and the soft books haven't caught up yet, the
stale soft price is value. We don't need Pinnacle for the sharp reference: the
betting EXCHANGES (Betfair/Smarkets/Matchbook) are the sharpest prices in the
market and they're in the UK feed already.

Per outcome, across ticks:
  * track the sharp (exchange) implied probability over a time window;
  * if it has STEAMED — risen by >= move_threshold (the line shortened toward
    this outcome) — the market now thinks the outcome is likelier;
  * if one of YOUR books still offers a price implying >= gap_threshold LESS than
    the sharp price now (i.e. it hasn't moved), flag it before it corrects.

Needs at least two ticks of history to see movement, so it's silent on the first
poll and warms up from there. Pure stdlib; state is the in-memory `OddsHistory`
the monitor carries across ticks.
"""
from __future__ import annotations

import time
from collections.abc import Iterable
from statistics import median

from .models import GemBet, MarketSnapshot
from .odds import decimal_to_implied, evaluate_value

# Sharpest prices available in the UK feed — the reference the soft books chase.
SHARP_BOOKS = {"betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au", "smarkets", "matchbook"}


class OddsHistory:
    """Per-(fixture, market, outcome, book) time series of implied probability.

    Samples older than `window` seconds are pruned on every record(), so "the
    start of the window" is just the oldest sample still held.
    """

    def __init__(self, window: float = 1800.0):
        self.window = window
        self._series: dict[tuple, list[tuple[float, float]]] = {}

    def record(self, snapshots: Iterable[MarketSnapshot], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        cutoff = now - self.window
        for snap in snapshots:
            for book, decimals in snap.quotes_per_book().items():
                for idx, _ in enumerate(snap.labels):
                    if idx >= len(decimals) or decimals[idx] <= 1.0:
                        continue
                    key = (snap.fixture, snap.market, idx, book.lower())
                    s = self._series.setdefault(key, [])
                    s.append((now, decimal_to_implied(decimals[idx])))
                    self._series[key] = [(t, p) for t, p in s if t >= cutoff]

    def earliest(self, fixture: str, market: str, idx: int, book: str) -> float | None:
        s = self._series.get((fixture, market, idx, book.lower()))
        return s[0][1] if s else None


def _sharp_implied(quotes: dict[str, list[float]], idx: int) -> list[float]:
    return [decimal_to_implied(d[idx]) for b, d in quotes.items()
            if b.lower() in SHARP_BOOKS and len(d) > idx and d[idx] > 1.0]


def detect(history: OddsHistory, snapshots: list[MarketSnapshot], *,
           move_threshold: float = 0.03, gap_threshold: float = 0.05,
           max_odds: float = 5.0, allowed_books: set[str] | None = None) -> list[GemBet]:
    """Flag soft books still offering a price the sharp market has moved past."""
    allow = {b.lower() for b in allowed_books} if allowed_books else None
    gems: list[GemBet] = []
    for snap in snapshots:
        quotes = snap.quotes_per_book()
        for idx, label in enumerate(snap.labels):
            sharp_now = _sharp_implied(quotes, idx)
            if not sharp_now:
                continue
            s_now = median(sharp_now)
            then = [p for b in SHARP_BOOKS
                    if (p := history.earliest(snap.fixture, snap.market, idx, b)) is not None]
            if not then:
                continue
            move = s_now - median(then)
            if move < move_threshold:          # sharp line hasn't steamed enough
                continue
            for book, decimals in quotes.items():
                blow = book.lower()
                if blow in SHARP_BOOKS:
                    continue
                if allow is not None and blow not in allow:
                    continue
                if len(decimals) <= idx:
                    continue
                offered = decimals[idx]
                if offered > max_odds:
                    continue
                soft_implied = decimal_to_implied(offered)
                if s_now - soft_implied < gap_threshold:   # soft already caught up
                    continue
                sig = evaluate_value(offered, s_now, min_edge=0.0)   # EV vs sharp-now
                gems.append(GemBet(
                    fixture=snap.fixture,
                    market=f"{snap.market} - {label}",
                    selection=label,
                    book=book,
                    decimal_odds=offered,
                    implied_prob=soft_implied,
                    fair_prob=s_now,
                    edge=sig.edge,
                    kind="steam",
                    reason=(f"Steam: sharp money moved {label} to {s_now*100:.0f}% "
                            f"(+{move*100:.0f}pts) but {book} still {offered:.2f} "
                            f"({soft_implied*100:.0f}%) -> +{sig.edge*100:.0f}% EV"),
                    notes=[f"sharp +{move*100:.0f}pts, gap {(s_now-soft_implied)*100:.0f}pts"],
                    kickoff=snap.kickoff,
                ))
    return sorted(gems, key=lambda g: g.edge, reverse=True)
