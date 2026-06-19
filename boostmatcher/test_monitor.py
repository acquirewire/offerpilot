"""Offline test of the monitor tick: fake fetcher + fake exchange, no network.
Run: python -m unittest boostmatcher.test_monitor
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from . import monitor
from .config import BookieTarget, Config, ExchangeCfg
from .models import ExchangeQuote

_FIXTURE = os.path.join(os.path.dirname(__file__), "examples", "skybet_card_sample.html")


class FakeExchange:
    name = "fake"

    async def quote(self, event, market, selection):
        # Lay only the BTTS card; the player-prop card returns no runner (as in
        # real life — props can't be laid).
        if "both teams" in selection.lower():
            return ExchangeQuote(exchange="fake", lay_odds=1.9, available=500,
                                 commission=0.02, runner="Both teams to score")
        return None


async def _fetch(_url: str) -> str:
    with open(_FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def _cfg() -> Config:
    return Config(
        bookies=[BookieTarget(name="skybet", url="http://x", scraper="skybet")],
        exchanges=[ExchangeCfg(name="fake", commission=0.02)],
        back_stake=25.0, alert_rating=2.0, ntfy_topic=None,
    )


class Tick(unittest.TestCase):
    def test_rates_and_writes_dashboard(self):
        cfg, seen = _cfg(), {}
        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "out.html")
            rated = asyncio.run(monitor.tick(cfg, [FakeExchange()], _fetch, seen, html_path=html))
            self.assertTrue(os.path.exists(html))
        # 2 cards scraped; the BTTS one is matched+lockable, the prop unmatched.
        self.assertEqual(len(rated), 2)
        matched = [r for r in rated if r.quote]
        self.assertEqual(len(matched), 1)
        self.assertTrue(matched[0].lockable)
        # First pass alerts the qualifying boost -> recorded in `seen`.
        self.assertEqual(len(seen), 1)

    def test_no_duplicate_alert_second_pass(self):
        cfg, seen = _cfg(), {}
        asyncio.run(monitor.tick(cfg, [FakeExchange()], _fetch, seen))
        first = dict(seen)
        asyncio.run(monitor.tick(cfg, [FakeExchange()], _fetch, seen))   # same prices
        self.assertEqual(seen, first)        # nothing re-alerted, rating unchanged


if __name__ == "__main__":
    unittest.main()
