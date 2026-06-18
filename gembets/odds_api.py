"""Odds feed: fetch multi-book football odds and normalise them to MarketSnapshot.

Implemented against **The Odds API** v4 (cheap, great 1X2/totals coverage, free
tier to validate). The normaliser is the contract the detectors rely on; the
fetch is a thin httpx GET gated on ODDS_API_KEY. Swap in OpticOdds/TheStatsAPI by
writing another `normalise_*` + `fetch_*` pair and registering it in PROVIDERS —
the rest of the pipeline doesn't change.

1X2/Over-Under are universally covered. BTTS and player props are sparser: this
maps them when the provider returns them, and silently skips them when it doesn't.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from .models import BookLine, MarketSnapshot

log = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"

# The Odds API market keys -> our internal market name + canonical label order.
_MARKET_MAP = {
    "h2h": "1X2",
    "totals": "Over/Under 2.5",
    "btts": "BTTS",
}
# Our internal market name -> the API market key (inverse of _MARKET_MAP).
_API_MARKET = {v: k for k, v in _MARKET_MAP.items()}

# Credits the free tier reports back, updated after each live call. The router
# reads this to decide whether to keep using the API or fall back to scraping.
_last_credits: dict[str, int | None] = {"remaining": None, "used": None}


class QuotaExhausted(RuntimeError):
    """Raised when The Odds API free credits are at/under the configured floor."""


def last_credits() -> tuple[int | None, int | None]:
    """(remaining, used) credits from the most recent API call, or (None, None)."""
    return _last_credits["remaining"], _last_credits["used"]


def _order_h2h(outcomes: list[dict], home: str, away: str) -> tuple[tuple[str, ...], list[float]] | None:
    """Map an h2h outcome list to (Home, Draw, Away) in that fixed order."""
    by_name = {o["name"]: float(o["price"]) for o in outcomes}
    if home not in by_name or away not in by_name or "Draw" not in by_name:
        return None
    return ("Home", "Draw", "Away"), [by_name[home], by_name["Draw"], by_name[away]]


def _order_totals(outcomes: list[dict], point: float = 2.5) -> tuple[tuple[str, ...], list[float]] | None:
    """Map a totals outcome list at the given line to (Over, Under)."""
    sel = {o["name"]: float(o["price"]) for o in outcomes if float(o.get("point", point)) == point}
    if "Over" not in sel or "Under" not in sel:
        return None
    return ("Over", "Under"), [sel["Over"], sel["Under"]]


def _order_btts(outcomes: list[dict]) -> tuple[tuple[str, ...], list[float]] | None:
    sel = {o["name"]: float(o["price"]) for o in outcomes}
    if "Yes" not in sel or "No" not in sel:
        return None
    return ("Yes", "No"), [sel["Yes"], sel["No"]]


def normalise_theoddsapi(events: list[dict]) -> list[MarketSnapshot]:
    """Turn The Odds API /odds JSON into one MarketSnapshot per (fixture, market)."""
    snaps: list[MarketSnapshot] = []
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        fixture = f"{home} vs {away}"
        kickoff = ev.get("commence_time")
        # Group each book's prices by our market name, then assemble per market.
        per_market: dict[str, tuple[tuple[str, ...], list[BookLine]]] = {}
        for bk in ev.get("bookmakers", []):
            book = bk.get("key", "?")
            for mk in bk.get("markets", []):
                name = _MARKET_MAP.get(mk.get("key"))
                if not name:
                    continue
                outs = mk.get("outcomes", [])
                if name == "1X2":
                    parsed = _order_h2h(outs, home, away)
                elif name == "Over/Under 2.5":
                    parsed = _order_totals(outs)
                elif name == "BTTS":
                    parsed = _order_btts(outs)
                else:
                    parsed = None
                if not parsed:
                    continue
                labels, decimals = parsed
                slot = per_market.setdefault(name, (labels, []))
                slot[1].append(BookLine(book=book, decimals=tuple(decimals)))
        for name, (labels, lines) in per_market.items():
            if lines:
                snaps.append(MarketSnapshot(fixture=fixture, market=name, labels=labels,
                                            lines=tuple(lines), kickoff=kickoff))
    return snaps


async def fetch_theoddsapi(sport_key: str, regions: list[str],
                           markets: list[str] | None = None) -> list[MarketSnapshot]:
    """Live pull. Needs ODDS_API_KEY in the environment (.env).

    `markets` are our internal names (e.g. ["1X2", "Over/Under 2.5"]); mapped to
    the API's keys. Updates the module credit counter from the response headers —
    free-tier cost is roughly len(markets) x len(regions) per call.
    """
    key = os.getenv("ODDS_API_KEY", "")
    if not key:
        raise RuntimeError("ODDS_API_KEY not set - add it to .env (the-odds-api.com)")
    market_keys = [_API_MARKET[m] for m in (markets or list(_API_MARKET)) if m in _API_MARKET]
    params = {
        "apiKey": key,
        "regions": ",".join(regions),
        "markets": ",".join(market_keys or ["h2h"]),
        "oddsFormat": "decimal",
    }
    url = f"{_BASE}/sports/{sport_key}/odds"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        _record_credits(resp.headers)
        return normalise_theoddsapi(resp.json())


def _record_credits(headers) -> None:
    def _int(name):
        v = headers.get(name)
        return int(v) if v not in (None, "") else None
    rem, used = _int("x-requests-remaining"), _int("x-requests-used")
    if rem is not None:
        _last_credits["remaining"] = rem
    if used is not None:
        _last_credits["used"] = used
    if rem is not None:
        log.info("odds api credits remaining: %s (used %s)", rem, used)


def load_sample(path: str) -> list[MarketSnapshot]:
    """Offline: read a saved The Odds API JSON dump and normalise it (for `demo`)."""
    with open(path, encoding="utf-8") as fh:
        return normalise_theoddsapi(json.load(fh))


# Registry: provider key -> (async fetch, raw-json normaliser).
PROVIDERS = {
    "theoddsapi": (fetch_theoddsapi, normalise_theoddsapi),
}
