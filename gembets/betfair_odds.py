"""Free odds source for Detector E: the Betfair Exchange API.

The Betfair Exchange (free, self-serve delayed app key — you already have the
auth in boostmatcher) lists the markets the totals model prices: Over/Under
**Goals**, **Corners** and **Bookings (booking points)**. We pull those, read
each side's best back price, and hand them to `totals.scan_quotes` to spot
mispriced lines. Same auth/env as boostmatcher's Betfair client
(BETFAIR_APP_KEY + BETFAIR_SESSION_TOKEN; mint a token with
`python -m boostmatcher betfair-login`).

The normalisation (Betfair JSON -> TotalQuote) is pure and unit-tested. The live
calls are written to the documented Betting API but, like boostmatcher's exchange
layer, need your key to verify — use `gembets betfair-probe` to confirm which
market-type codes your account returns, then put them in `betfair_market_types`.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from .player_fouls import PlayerFoulQuote
from .totals import TotalQuote

log = logging.getLogger(__name__)

_BETTING = "https://api.betfair.com/exchange/betting/rest/v1.0"
_SOCCER = "1"            # Betfair eventTypeId for football/soccer

# Player-fouls market types (confirmed present via betfair-probe: PLAYER_FOULS_1
# = home side, _2 = away). Structure assumed: one market per player named after
# the player, with Over/Under runners at a line — verify with betfair-probe.
PLAYER_FOUL_TYPES = ["PLAYER_FOULS_1", "PLAYER_FOULS_2"]

# Real Betfair codes (confirmed via betfair-probe). We deliberately EXCLUDE goals
# over/under here — goals are Detector C's job, and their huge volume would crowd
# the low-volume cards/corners markets out of a single sorted catalogue call.
# Detector E focuses on the markets goals-feeds don't carry: cards, corners, shots.
DEFAULT_MARKET_TYPES = [
    # corners
    "OVER_UNDER_85_CORNR", "OVER_UNDER_95_CORNR", "OVER_UNDER_105_CORNR",
    "OVER_UNDER_115_CORNR", "OVER_UNDER_125_CORNR", "CORNER_ODDS",
    # cards (count) + bookings (points)
    "OVER_UNDER_25_CARDS", "OVER_UNDER_35_CARDS", "OVER_UNDER_45_CARDS", "BOOKING_ODDS",
    # shots
    "MATCH_SHOTS", "MATCH_SHOTS_TARGET",
]


# ------------------------------------------------------------ pure normalisation

def classify_market(name: str) -> str | None:
    """Map a Betfair market name to our model market kind.

    Cards markets are CARD COUNT (e.g. 'Over/Under 3.5 Cards'); 'Bookings' markets
    are booking POINTS (10/yellow, 25/red) — different scales, different models.
    """
    n = name.lower()
    if "corner" in n:
        return "corners"
    if "booking" in n:
        return "booking_points"
    if "card" in n:
        return "cards"
    if "shot" in n:
        return "shots_on_target" if "target" in n else "shots"
    if "goal" in n or "over/under" in n:      # generic O/U markets are goals
        return "goals"
    return None


def parse_line(name: str) -> float | None:
    """Pull the over/under line out of a market name, e.g. '...10.5 Corners' -> 10.5."""
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else None


def _best_back(runner: dict) -> float | None:
    back = (runner.get("ex") or {}).get("availableToBack") or []
    return round(float(back[0]["price"]), 3) if back else None


def normalise_markets(catalogue: list[dict], books: list[dict]) -> list[TotalQuote]:
    """Combine listMarketCatalogue + listMarketBook into TotalQuotes."""
    book_by_id = {b.get("marketId"): b for b in books}
    quotes: list[TotalQuote] = []
    for cat in catalogue:
        name = cat.get("marketName", "")
        kind = classify_market(name)
        line = parse_line(name)
        if kind is None or line is None:
            continue
        fixture = (cat.get("event") or {}).get("name", "")
        names = {r["selectionId"]: r.get("runnerName", "") for r in cat.get("runners", [])}
        book = book_by_id.get(cat.get("marketId"))
        if not (fixture and book):
            continue
        over = under = None
        for r in book.get("runners", []):
            label = names.get(r.get("selectionId"), "").lower()
            price = _best_back(r)
            if "over" in label:
                over = price
            elif "under" in label:
                under = price
        if over or under:
            quotes.append(TotalQuote(fixture=fixture, market=kind, line=line,
                                     over_decimal=over, under_decimal=under, source="betfair"))
    return quotes


def _player_from_market(name: str) -> str:
    """'Bukayo Saka Total Fouls' -> 'Bukayo Saka' (strip the market suffix)."""
    return re.sub(r"(?i)\b(total\s+)?fouls?\b", "", name).strip(" -")


def normalise_player_fouls(catalogue: list[dict], books: list[dict]) -> list[PlayerFoulQuote]:
    """Betfair PLAYER_FOULS markets -> PlayerFoulQuotes (one market per player)."""
    book_by_id = {b.get("marketId"): b for b in books}
    out: list[PlayerFoulQuote] = []
    for cat in catalogue:
        name = cat.get("marketName", "")
        book = book_by_id.get(cat.get("marketId"))
        if not book:
            continue
        fixture = (cat.get("event") or {}).get("name", "")
        labels = {r["selectionId"]: r.get("runnerName", "") for r in cat.get("runners", [])}
        over = under = line = None
        for r in book.get("runners", []):
            label = labels.get(r.get("selectionId"), "").lower()
            price = _best_back(r)
            if "over" in label:
                over, line = price, parse_line(label) or line
            elif "under" in label:
                under, line = price, parse_line(label) or line
        if line is None:
            line = parse_line(name)
        player = _player_from_market(name)
        if fixture and player and line is not None and (over or under):
            out.append(PlayerFoulQuote(fixture=fixture, player=player, line=line,
                                       over_decimal=over, under_decimal=under, source="betfair"))
    return out


# ------------------------------------------------------------------- live client

class BetfairOdds:
    """Minimal read-only Betfair Betting API client for totals markets."""

    def __init__(self, app_key: str | None = None, session_token: str | None = None):
        self._app_key = app_key or os.getenv("BETFAIR_APP_KEY", "")
        self._token = session_token or os.getenv("BETFAIR_SESSION_TOKEN", "")

    @property
    def ready(self) -> bool:
        return bool(self._app_key and self._token)

    def _headers(self) -> dict[str, str]:
        return {"X-Application": self._app_key, "X-Authentication": self._token,
                "Content-Type": "application/json", "Accept": "application/json"}

    async def _post(self, client, path, body):
        resp = await client.post(_BETTING + path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def list_total_markets(self, *, market_types: list[str] | None = None,
                                 hours_ahead: int = 48, max_results: int = 100) -> list[TotalQuote]:
        """Fetch upcoming goals/corners/bookings O/U markets as TotalQuotes."""
        if not self.ready:
            log.warning("betfair: missing BETFAIR_APP_KEY / BETFAIR_SESSION_TOKEN")
            return []
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            catalogue = await self._catalogue(
                client, market_types or DEFAULT_MARKET_TYPES, hours_ahead, max_results)
            if not catalogue:
                return []
            books = await self._books(client, [c["marketId"] for c in catalogue])
        quotes = normalise_markets(catalogue, books)
        log.info("betfair: %d total-market quote(s) from %d markets", len(quotes), len(catalogue))
        return quotes

    async def _books(self, client, ids: list[str]) -> list[dict]:
        """listMarketBook in chunks of 25 (the API caps markets per call -> 400)."""
        books: list[dict] = []
        for i in range(0, len(ids), 25):
            res = await self._post(client, "/listMarketBook/", {
                "marketIds": ids[i:i + 25],
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
            })
            books.extend(res or [])
        return books

    async def _catalogue(self, client, market_types, hours_ahead, max_results):
        now = datetime.now(timezone.utc)
        return await self._post(client, "/listMarketCatalogue/", {
            "filter": {"eventTypeIds": [_SOCCER], "marketTypeCodes": market_types,
                       "marketStartTime": {"from": now.isoformat(),
                                           "to": (now + timedelta(hours=hours_ahead)).isoformat()}},
            "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
            "sort": "MAXIMUM_TRADED", "maxResults": max_results,
        })

    async def list_player_foul_markets(self, *, hours_ahead: int = 48,
                                       max_results: int = 200) -> list[PlayerFoulQuote]:
        """Fetch upcoming Betfair PLAYER_FOULS markets as PlayerFoulQuotes."""
        if not self.ready:
            return []
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            catalogue = await self._catalogue(client, PLAYER_FOUL_TYPES, hours_ahead, max_results)
            if not catalogue:
                return []
            books = await self._books(client, [c["marketId"] for c in catalogue])
        quotes = normalise_player_fouls(catalogue, books)
        log.info("betfair: %d player-foul quote(s) from %d markets", len(quotes), len(catalogue))
        return quotes

    async def probe_market_types(self, *, hours_ahead: int = 48) -> dict[str, int]:
        """List the soccer marketType codes available now (to calibrate config)."""
        if not self.ready:
            return {}
        now = datetime.now(timezone.utc)
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            res = await self._post(client, "/listMarketTypes/", {"filter": {
                "eventTypeIds": [_SOCCER],
                "marketStartTime": {"from": now.isoformat(),
                                    "to": (now + timedelta(hours=hours_ahead)).isoformat()},
            }})
        return {r["marketType"]: r.get("marketCount", 0) for r in (res or [])}
