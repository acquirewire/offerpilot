"""Odds source router: free-tier API primary, scrape fallback.

Keeps the consensus detector fed for free. Strategy per tick:

  * source "api"    -> The Odds API only.
  * source "scrape" -> oddschecker only.
  * source "both"   -> API while free credits remain above `credit_floor`; when
                       they're exhausted (or the API errors) fall back to scraping.

The Odds API free tier is 500 credits/MONTH and each call costs ~len(markets) x
len(regions). The router refuses to call the API once the reported remaining
credit count is at/under the floor, so the loop can run indefinitely without
silently burning the month's budget — it just leans on the scraper instead.
"""
from __future__ import annotations

import logging

from . import odds_api, scrape
from .config import Config
from .models import MarketSnapshot

log = logging.getLogger(__name__)


class OddsRouter:
    """Stateful chooser between the API and the scraper for one running loop."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._api_fetch = odds_api.PROVIDERS[cfg.odds_provider][0]

    def _credits_ok(self) -> bool:
        remaining, _ = odds_api.last_credits()
        if remaining is None:
            return True                       # not yet known — allow the first call
        return remaining > self.cfg.credit_floor

    async def _from_api(self) -> list[MarketSnapshot]:
        return await self._api_fetch(self.cfg.sport_key, self.cfg.regions, self.cfg.markets)

    async def _from_scrape(self) -> list[MarketSnapshot]:
        return await scrape.fetch_scrape(self.cfg.scrape_scraper, self.cfg.scrape_urls)

    async def fetch(self) -> list[MarketSnapshot]:
        src = self.cfg.odds_source
        if src == "scrape":
            return await self._from_scrape()

        if src == "api":
            return await self._from_api()

        # "both": API first while credits last; on low credits or error -> scrape.
        if self._credits_ok():
            try:
                snaps = await self._from_api()
                log.info("odds source: api (%d snapshot(s))", len(snaps))
                return snaps
            except Exception as exc:  # noqa: BLE001 — fall back rather than die
                log.warning("api fetch failed (%s) - falling back to scrape", exc)
        else:
            remaining, _ = odds_api.last_credits()
            log.info("odds api credits low (%s <= %d) - using scrape fallback",
                     remaining, self.cfg.credit_floor)
        snaps = await self._from_scrape()
        log.info("odds source: scrape (%d snapshot(s))", len(snaps))
        return snaps


def make_odds_fetcher(cfg: Config):
    """Zero-arg async fetcher the monitor binds to (router holds the state)."""
    router = OddsRouter(cfg)

    async def fetch() -> list[MarketSnapshot]:
        return await router.fetch()

    return fetch
