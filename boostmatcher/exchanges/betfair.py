"""Betfair Exchange client — deepest liquidity, more setup.

API: https://developer.betfair.com/  (Betting + Accounts API, JSON-RPC).

Setup cost: a DELAYED app key is free (data is ~1–60s delayed — fine for
spotting boosts, not for the final click); a LIVE app key is a one-off ~£299.
Auth is a session token from non-interactive (certificate) login, refreshed
via keep-alive.

Flow:
  1. Cert login -> SSOID session token (X-Authentication header) + X-Application
     app key. https://identitysso-cert.betfair.com/api/certlogin
  2. listMarketCatalogue (filter by event name + MarketType, e.g. MATCH_ODDS,
     BOTH_TEAMS_TO_SCORE) -> marketId + runner names/ids.
  3. listMarketBook with priceProjection EX_BEST_OFFERS -> per-runner best
     'availableToLay' price + size. We lay at the best available lay price.

Betfair commission is market-base-rate * (1 - discount); default 5%, can be 2%.
Not live-tested: needs BETFAIR_APP_KEY + cert session. Offline path covers maths.
"""
from __future__ import annotations

import os

import logging

import httpx

from .base import pick_lay
from ..models import ExchangeQuote

log = logging.getLogger(__name__)

_BETTING = "https://api.betfair.com/exchange/betting/rest/v1.0"

# Boost market text -> Betfair marketTypeCodes filter (None = rely on textQuery).
_MARKET_TYPES = {
    "match result": ["MATCH_ODDS"],
    "match odds": ["MATCH_ODDS"],
    "both teams to score": ["BOTH_TEAMS_TO_SCORE"],
    "over/under 2.5 goals": ["OVER_UNDER_25"],
    "correct score": ["CORRECT_SCORE"],
}


_CERTLOGIN = "https://identitysso-cert.betfair.com/api/certlogin"
_LOGIN = "https://identitysso.betfair.com/api/login"


def interactive_login() -> str:
    """Simplest login -> session token: username + password, NO certificate.

    Best for getting started with the free delayed app key. Reads BETFAIR_APP_KEY,
    BETFAIR_USERNAME, BETFAIR_PASSWORD from env. Run locally by the user; this
    code only reads the env vars and never stores them.
    """
    app_key = os.getenv("BETFAIR_APP_KEY", "")
    user = os.getenv("BETFAIR_USERNAME", "")
    pw = os.getenv("BETFAIR_PASSWORD", "")
    if not (app_key and user and pw):
        raise RuntimeError("set BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD in .env")
    resp = httpx.post(
        _LOGIN,
        data={"username": user, "password": pw},
        headers={"X-Application": app_key, "Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "SUCCESS":
        raise RuntimeError(f"Betfair login failed: {body.get('status')} / {body.get('error')}")
    return body["token"]


def cert_login() -> str:
    """Non-interactive cert login -> session token, reading creds from env.

    Needs BETFAIR_APP_KEY, BETFAIR_USERNAME, BETFAIR_PASSWORD and a client cert
    pair (BETFAIR_CERT_FILE / BETFAIR_KEY_FILE) uploaded to your Betfair account.
    Run by the user locally; this code never sees credentials beyond the env.
    Returns the sessionToken string (also printed by the `betfair-login` command).
    """
    app_key = os.getenv("BETFAIR_APP_KEY", "")
    user = os.getenv("BETFAIR_USERNAME", "")
    pw = os.getenv("BETFAIR_PASSWORD", "")
    cert = (os.getenv("BETFAIR_CERT_FILE", ""), os.getenv("BETFAIR_KEY_FILE", ""))
    if not (app_key and user and pw and all(cert)):
        raise RuntimeError("set BETFAIR_APP_KEY/USERNAME/PASSWORD/CERT_FILE/KEY_FILE in .env")
    resp = httpx.post(
        _CERTLOGIN,
        data={"username": user, "password": pw},
        headers={"X-Application": app_key,
                 "Content-Type": "application/x-www-form-urlencoded"},
        cert=cert, timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("loginStatus") != "SUCCESS":
        raise RuntimeError(f"Betfair login failed: {body.get('loginStatus')}")
    return body["sessionToken"]


class Betfair:
    name = "betfair"

    def __init__(self, commission: float = 0.05, app_key: str | None = None,
                 session_token: str | None = None) -> None:
        self.commission = commission
        self._app_key = app_key or os.getenv("BETFAIR_APP_KEY", "")
        self._token = session_token or os.getenv("BETFAIR_SESSION_TOKEN", "")

    def _headers(self) -> dict[str, str]:
        return {
            "X-Application": self._app_key,
            "X-Authentication": self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def quote(self, event: str, market: str, selection: str) -> ExchangeQuote | None:
        if not (self._app_key and self._token):
            log.warning("betfair: missing BETFAIR_APP_KEY / session token")
            return None
        try:
            async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
                market_id, runners = await self._resolve(client, event, market)
                if not runners:
                    return None
        except Exception as exc:  # noqa: BLE001
            log.warning("betfair quote failed for %s: %s", event, exc)
            return None
        return pick_lay(self.name, self.commission, runners, selection, market_id=market_id)

    async def market_runners(self, event: str, market: str):
        """Probe helper: open a client and return (market_id, {runner: (lay, size)})
        for one market, so the CLI `probe` can print every runner's lay price."""
        if not (self._app_key and self._token):
            return "", {}
        async with httpx.AsyncClient(timeout=15, headers=self._headers()) as client:
            return await self._resolve(client, event, market)

    async def _resolve(self, client, event, market):
        """Resolve event+market -> (marketId, {runner: (best_lay, size)}).

        listMarketCatalogue (textQuery=event, marketTypeCodes from the boost
        market) gives marketId + runner names; listMarketBook with EX_BEST_OFFERS
        gives each runner's best availableToLay price + size. Verify live before
        trusting figures with real money.
        """
        types = _MARKET_TYPES.get(market.lower())
        cat = await self._post(client, "/listMarketCatalogue/", {
            "filter": {"textQuery": event, **({"marketTypeCodes": types} if types else {})},
            "marketProjection": ["RUNNER_DESCRIPTION"],
            "maxResults": 5, "sort": "MAXIMUM_TRADED",
        })
        if not cat:
            return "", {}
        cat0 = cat[0]
        market_id = cat0["marketId"]
        names = {r["selectionId"]: r.get("runnerName", "") for r in cat0.get("runners", [])}

        books = await self._post(client, "/listMarketBook/", {
            "marketIds": [market_id],
            "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
        })
        if not books:
            return market_id, {}
        runners: dict[str, tuple[float, float]] = {}
        for r in books[0].get("runners", []):
            ex = r.get("ex") or {}
            lay = ex.get("availableToLay") or []
            if not lay:
                continue
            name = names.get(r.get("selectionId"), str(r.get("selectionId")))
            back_list = ex.get("availableToBack") or []
            back = round(float(back_list[0]["price"]), 3) if back_list else None
            runners[name] = (round(float(lay[0]["price"]), 3),
                             round(float(lay[0]["size"]), 2), back)
        return market_id, runners

    async def _post(self, client, path, body):
        resp = await client.post(_BETTING + path, json=body)
        resp.raise_for_status()
        return resp.json()
