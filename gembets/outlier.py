"""Detector A: consensus value betting.

A gem is flagged when a bookmaker's price for an outcome is enough HIGHER than the
typical price across the market — your "majority odds are 3.0, only tell me if a
book offers 4.0" rule. Concretely, for each outcome:

  * `typical`  = median offered odds across the (non-exchange) books — the price
                 you'd see at most bookmakers.
  * `lift`     = book_odds / typical - 1   (4.00 vs 3.00 -> +33%).
  * flag when  lift >= min_lift, the outcome isn't a longshot (odds <= max_odds),
               and the book is one you actually use (allowed_books).

We still de-vig the whole market to a fair probability for context in the alert
(implied vs fair, and the EV), but the GATE is the odds gap you asked for.

Honest read: a lone book far above the rest is often the book being *right*
(injury/lineup news) or a soft line cut within minutes. The cap + allowlist + a
fat lift threshold cut the noise; CLV (see README) proves the rest is real edge.
"""
from __future__ import annotations

from statistics import median

from .models import GemBet, MarketSnapshot
from .odds import consensus_fair_prob, decimal_to_implied

# Betting EXCHANGES, not soft bookmakers. Their commission-free back prices are
# the sharpest in the market, so they don't represent the "typical" bookmaker
# price and are never flagged as a gem (an exchange "outlier" is just its fair
# price). Kept out of the typical-price median and out of the flag set.
EXCHANGES = {"betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au", "betfair_ex_us",
             "smarkets", "matchbook"}


def scan_snapshot(snap: MarketSnapshot, *, min_lift: float = 0.33, min_books: int = 4,
                  max_odds: float = 5.0, allowed_books: set[str] | None = None) -> list[GemBet]:
    """Flag book prices that sit `min_lift` above the typical price (with caps)."""
    quotes = snap.quotes_per_book()
    if len(quotes) < min_books:        # too few books -> typical price isn't trustworthy
        return []
    allow = {b.lower() for b in allowed_books} if allowed_books else None

    gems: list[GemBet] = []
    for idx, label in enumerate(snap.labels):
        # The "typical" price = median across BOOKMAKERS (exchanges excluded).
        offered_all = [d[idx] for b, d in quotes.items()
                       if b.lower() not in EXCHANGES and len(d) > idx and d[idx] > 1.0]
        if len(offered_all) < min_books:
            continue
        typical = median(offered_all)
        try:
            fair = consensus_fair_prob(quotes, idx)     # de-vigged, for EV/context
        except ValueError:
            continue

        for book, decimals in quotes.items():
            if len(decimals) <= idx:
                continue
            blow = book.lower()
            if allow is not None:
                if blow not in allow:          # only books you actually use
                    continue
            elif blow in EXCHANGES:            # default: never flag an exchange
                continue
            offered = decimals[idx]
            if offered > max_odds:             # cap: outcome must be likely enough
                continue
            lift = offered / typical - 1.0
            if lift < min_lift:
                continue
            ev = fair * offered - 1.0
            gems.append(GemBet(
                fixture=snap.fixture,
                market=f"{snap.market} - {label}",
                selection=label,
                book=book,
                decimal_odds=offered,
                implied_prob=decimal_to_implied(offered),
                fair_prob=fair,
                edge=lift,                     # the odds gap drives sort/priority/dedup
                kind="outlier",
                reason=(f"{book} prices {label} at {offered:.2f}, {lift*100:.0f}% above the "
                        f"typical {typical:.2f} across {len(offered_all)} books "
                        f"(de-vig fair {fair*100:.0f}%, +{ev*100:.0f}% EV)"),
                notes=[f"typical {typical:.2f}, {len(offered_all)} books"],
                kickoff=snap.kickoff,
            ))
    return gems


def scan_all(snapshots: list[MarketSnapshot], *, min_lift: float = 0.33, min_books: int = 4,
             max_odds: float = 5.0, allowed_books: set[str] | None = None) -> list[GemBet]:
    gems: list[GemBet] = []
    for snap in snapshots:
        gems.extend(scan_snapshot(snap, min_lift=min_lift, min_books=min_books,
                                  max_odds=max_odds, allowed_books=allowed_books))
    return sorted(gems, key=lambda g: g.edge, reverse=True)
