"""Tests for the free odds path: scrape parsing + the api/scrape router.
Run: python -m unittest gembets.test_sources

The scraper's LIVE selectors need calibration against a real oddschecker page,
but the PARSING LOGIC is pinned here against a synthetic grid shaped like the
placeholder SPEC (rows carrying data-bk, odds in data-o attributes).
"""
from __future__ import annotations

import unittest
from unittest import mock

from . import odds_api, scrape, sources
from .config import Config
from .models import MarketSnapshot

# A minimal oddschecker-shaped grid: one row per book, 3 cells = Home/Draw/Away.
_GRID = """
<table>
  <tr data-bk="bet365">
    <td class="bk">Bet365</td>
    <td data-o="2/1"></td><td data-o="13/5"></td><td data-o="11/8"></td>
  </tr>
  <tr data-bk="williamhill">
    <td class="bk">William Hill</td>
    <td data-o="21/10"></td><td data-o="5/2"></td><td data-o="7/5"></td>
  </tr>
  <tr data-bk="unibet">
    <td class="bk">Unibet</td>
    <td data-o="2/1"></td><td data-o="12/5"></td><td data-o="11/8"></td>
  </tr>
  <tr data-bk="coral">
    <td class="bk">Coral</td>
    <td data-o="15/8"></td><td data-o="5/2"></td><td data-o="6/4"></td>
  </tr>
</table>
"""


class GridParsing(unittest.TestCase):
    def test_parses_books_and_decimals(self):
        snap = scrape.parse_oddschecker(_GRID, fixture="Brighton vs Aston Villa")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.market, "1X2")
        self.assertEqual(snap.labels, ("Home", "Draw", "Away"))
        self.assertEqual(len(snap.lines), 4)
        bet365 = next(l for l in snap.lines if l.book == "bet365")
        # 2/1 -> 3.0, 13/5 -> 3.6, 11/8 -> 2.375
        self.assertEqual(bet365.decimals, (3.0, 3.6, 2.375))

    def test_too_few_books_returns_none(self):
        one_row = "<table><tr data-bk=x><td data-o='2/1'></td><td data-o='3/1'></td>" \
                  "<td data-o='3/1'></td></tr></table>"
        self.assertIsNone(scrape.parse_oddschecker(one_row, fixture="A vs B"))

    def test_fixture_from_url(self):
        url = "https://www.oddschecker.com/football/english/premier-league/brighton-v-aston-villa/winner"
        self.assertEqual(scrape.fixture_from_url(url), "Brighton vs Aston Villa")

    def test_grid_feeds_the_detector(self):
        # The scraped snapshot must be a drop-in for Detector A.
        from .outlier import scan_snapshot
        snap = scrape.parse_oddschecker(_GRID, fixture="Brighton vs Aston Villa")
        gems = scan_snapshot(snap, min_lift=0.0, min_books=2)   # threshold 0 just to prove flow
        self.assertIsInstance(gems, list)


class Router(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        odds_api._last_credits.update(remaining=None, used=None)   # reset between tests

    async def test_api_only_source(self):
        cfg = Config(odds_source="api")
        router = sources.OddsRouter(cfg)
        sentinel = [mock.Mock(spec=MarketSnapshot)]
        with mock.patch.object(router, "_api_fetch",
                               new=mock.AsyncMock(return_value=sentinel)) as api:
            out = await router.fetch()
        self.assertIs(out, sentinel)
        api.assert_awaited_once()

    async def test_both_prefers_api_when_credits_ok(self):
        cfg = Config(odds_source="both", credit_floor=25)
        router = sources.OddsRouter(cfg)
        router._api_fetch = mock.AsyncMock(return_value=["api"])
        with mock.patch.object(odds_api, "last_credits", return_value=(400, 100)), \
             mock.patch.object(scrape, "fetch_scrape", new=mock.AsyncMock(return_value=["scrape"])):
            out = await router.fetch()
        self.assertEqual(out, ["api"])

    async def test_both_falls_back_to_scrape_when_credits_low(self):
        cfg = Config(odds_source="both", credit_floor=25)
        router = sources.OddsRouter(cfg)
        router._api_fetch = mock.AsyncMock(return_value=["api"])
        with mock.patch.object(odds_api, "last_credits", return_value=(10, 490)), \
             mock.patch.object(scrape, "fetch_scrape",
                               new=mock.AsyncMock(return_value=["scrape"])) as scr:
            out = await router.fetch()
        self.assertEqual(out, ["scrape"])
        router._api_fetch.assert_not_awaited()        # API skipped — budget protected
        scr.assert_awaited_once()

    async def test_both_falls_back_on_api_error(self):
        cfg = Config(odds_source="both")
        router = sources.OddsRouter(cfg)
        router._api_fetch = mock.AsyncMock(side_effect=RuntimeError("503"))
        with mock.patch.object(odds_api, "last_credits", return_value=(None, None)), \
             mock.patch.object(scrape, "fetch_scrape",
                               new=mock.AsyncMock(return_value=["scrape"])) as scr:
            out = await router.fetch()
        self.assertEqual(out, ["scrape"])
        scr.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
