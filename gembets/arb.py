"""Arbitrage detection — guaranteed-profit spots across books.

If you can back EVERY outcome of a market at different books such that the sum of
inverse odds is below 1, you lock a profit whatever happens:

    inv = sum(1 / best_odds_i)        # best price for each outcome, any book
    inv < 1  ->  guaranteed margin = (1/inv - 1),  stake_i proportional to 1/odds_i

Pure odds maths — no model, no opinion, can't be "wrong" (only stale: prices move
and arbs vanish in seconds, and hammering them gets soft accounts limited fast, so
treat as opportunistic). We reuse the multi-book snapshots Detector A already pulls.
Unit-tested.
"""
from __future__ import annotations

from .models import GemBet, MarketSnapshot
from .outlier import EXCHANGES


def find_arb(snap: MarketSnapshot, *, min_margin: float = 0.005) -> GemBet | None:
    """Best-price-per-outcome arb across BOOKMAKERS (exchanges excluded).

    Exchanges are left out because their commission-free back prices manufacture
    'arbs' that disappear once commission is paid — a cross-bookmaker arb is real
    and commission-free.
    """
    quotes = {b: d for b, d in snap.quotes_per_book().items() if b.lower() not in EXCHANGES}
    if len(quotes) < 2:
        return None
    best: list[tuple[float, str]] = []          # (best_odds, book) per outcome
    for idx in range(len(snap.labels)):
        cands = [(d[idx], b) for b, d in quotes.items() if len(d) > idx and d[idx] > 1.0]
        if not cands:
            return None
        best.append(max(cands, key=lambda c: c[0]))
    inv = sum(1.0 / o for o, _ in best)
    if inv >= 1.0 - min_margin:                  # not enough edge to be a real arb
        return None
    margin = 1.0 / inv - 1.0
    legs = []
    for (odds, book), label in zip(best, snap.labels):
        stake_pct = (1.0 / odds) / inv * 100.0   # % of total stake on this leg
        legs.append(f"{label} @ {odds:.2f} ({book}, {stake_pct:.0f}%)")
    return GemBet(
        fixture=snap.fixture,
        market=f"{snap.market} ARB",
        selection="ARB",
        book="multi",
        decimal_odds=round(1.0 / inv, 3),        # effective combined price
        implied_prob=inv,
        fair_prob=1.0,
        edge=margin,
        kind="arb",
        reason=(f"Arbitrage +{margin*100:.1f}% guaranteed: back " + "  +  ".join(legs)),
        notes=[f"books: {', '.join(b for _, b in best)}"],
        kickoff=snap.kickoff,
    )


def scan_arbs(snapshots: list[MarketSnapshot], *, min_margin: float = 0.005) -> list[GemBet]:
    out = [g for snap in snapshots if (g := find_arb(snap, min_margin=min_margin))]
    return sorted(out, key=lambda g: g.edge, reverse=True)
