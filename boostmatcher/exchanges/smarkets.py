"""Smarkets exchange client — the simpler of the two to wire up.

API: https://docs.smarkets.com/  (free, REST + JSON, no per-key fee).

Flow:
  1. POST https://api.smarkets.com/v3/sessions/  with API credentials -> session
     token (also supports an Authorization: ... header from the dashboard).
  2. Resolve the boost's event+market to a Smarkets market_id. Browse via
     /v3/events/?type_domain=football&... then /v3/events/<id>/markets/.
  3. GET /v3/markets/<id>/quotes/  -> per-contract best back/lay + volume.
     For a LAY we read the best 'offer' (what's available to lay against).

Smarkets commission is a flat 2% on net winnings -> ExchangeQuote.commission.
Prices come in integer odds units (e.g. ten-thousandths); convert to decimal.

Not live-tested: needs SMARKETS_API_TOKEN in the environment. Until then the
offline rate/demo path covers the rating logic.
"""
from __future__ import annotations

import os

import logging

import httpx

from .base import pick_lay
from ..models import ExchangeQuote

log = logging.getLogger(__name__)

_BASE = "https://api.smarkets.com/v3"


class Smarkets:
    name = "smarkets"

    def __init__(self, commission: float = 0.02, token: str | None = None) -> None:
        self.commission = commission
        self._token = token or os.getenv("SMARKETS_API_TOKEN", "")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token, "Accept": "application/json"}

    async def quote(self, event: str, market: str, selection: str) -> ExchangeQuote | None:
        if not self._token:
            log.warning("smarkets: no SMARKETS_API_TOKEN set")
            return None
        try:
            async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
                market_id, runners = await self._resolve(client, event, market)
                if not runners:
                    return None
        except Exception as exc:  # noqa: BLE001 — a dead quote must not kill the loop
            log.warning("smarkets quote failed for %s: %s", event, exc)
            return None
        return pick_lay(self.name, self.commission, runners, selection, market_id=market_id)

    async def market_runners(self, event: str, market: str):
        """Probe helper: open a client and return (market_id, {runner: (lay, liq)})
        for one market, so the CLI `probe` can print every runner's lay price."""
        if not self._token:
            return "", {}
        async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
            return await self._resolve(client, event, market)

    async def _resolve(self, client, event, market):
        """Resolve event+market -> (market_id, {runner_name: (lay_odds, liquidity)}).

        Walks events -> markets -> contracts -> quotes. Smarkets quotes prices as
        integer probability points (price 2000 = 20.00% => decimal 10000/price),
        and to LAY a contract you take the best BID (a backer's offer) on it.
        Verify against a live token before trusting the numbers with real money.
        """
        from ..matcher import score

        ev = await self._get(client, "/events/",
                             params={"states": "upcoming,live", "type_domains": "football",
                                     "sort": "start_datetime", "limit": 200})
        events = ev.get("events", [])
        best = max(events, key=lambda e: score(event, e.get("name", "")), default=None)
        if not best or score(event, best.get("name", "")) < 0.5:
            return "", {}
        event_id = best["id"]

        mk = await self._get(client, f"/events/{event_id}/markets/")
        markets = mk.get("markets", [])
        mkt = max(markets, key=lambda m: score(market, m.get("name", "")), default=None)
        if not mkt:
            return "", {}
        market_id = mkt["id"]

        ct = await self._get(client, f"/markets/{market_id}/contracts/")
        names = {str(c["id"]): c.get("name", "") for c in ct.get("contracts", [])}

        qz = await self._get(client, f"/markets/{market_id}/quotes/")
        quotes = qz.get(str(market_id), qz)        # keyed by market then contract id
        runners: dict[str, tuple[float, float]] = {}
        for cid, name in names.items():
            q = quotes.get(cid) or {}
            bids = q.get("bids") or []                  # backers' offers -> lay against
            if not bids:
                continue
            price = bids[0].get("price")
            qty = bids[0].get("quantity", 0)
            if not price:
                continue
            offers = q.get("offers") or []              # layers' offers -> back at
            back = round(10000.0 / offers[0]["price"], 3) if offers and offers[0].get("price") \
                else None
            runners[name] = (round(10000.0 / price, 3), round(qty / 10000.0, 2), back)
        return str(market_id), runners

    async def _get(self, client, path, *, params=None):
        resp = await client.get(_BASE + path, params=params or {})
        resp.raise_for_status()
        return resp.json()
