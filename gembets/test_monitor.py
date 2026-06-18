"""Tests for the poll loop with fake fetchers (no network, no ntfy).
Run: python -m unittest gembets.test_monitor
"""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from . import monitor
from .config import Config
from .models import BookLine, MarketSnapshot
from .statedge import CardsMatchup, FoulMatchup


def _snaps():
    lines = (
        BookLine("pinnacle", (2.05, 3.60, 3.70)),
        BookLine("bet365", (2.00, 3.50, 3.60)),
        BookLine("williamhill", (2.10, 3.40, 3.55)),
        BookLine("unibet", (2.05, 3.55, 3.65)),
        BookLine("coral", (2.00, 3.40, 4.90)),     # the gem: ~34% above typical
    )
    return [MarketSnapshot("Brighton vs Aston Villa", "1X2",
                           ("Home", "Draw", "Away"), lines)]


class Tick(unittest.IsolatedAsyncioTestCase):
    async def _run_tick(self, cfg, *, fouls=None, cards=None):
        async def fetch_odds():
            return _snaps()

        async def fetch_stats():
            return (fouls or [], cards or [])

        seen: dict[str, float] = {}
        with mock.patch.object(monitor.notify, "alert") as alert:
            gems = await monitor.tick(cfg, fetch_odds, fetch_stats, seen)
        return gems, seen, alert

    async def test_outlier_alerts_once_then_dedupes(self):
        cfg = Config(ntfy_topic="t", enable_statedge=False, enable_arb=False)
        gems, seen, alert = await self._run_tick(cfg)
        self.assertEqual(len(gems), 1)
        self.assertEqual(alert.await_count, 1)            # fired once

        # Second pass over the SAME state: no new alert (deduped on key+edge).
        async def fetch_odds():
            return _snaps()
        with mock.patch.object(monitor.notify, "alert") as alert2:
            await monitor.tick(cfg, fetch_odds, None, seen)
        self.assertEqual(alert2.await_count, 0)

    async def test_statedge_off_by_default(self):
        cfg = Config(ntfy_topic="t", enable_statedge=False, enable_arb=False)
        foul = FoulMatchup("Brighton vs Aston Villa", "K. Mitoma", 1.5, 1.90, 1.9, 2.8)
        gems, _, _ = await self._run_tick(cfg, fouls=[foul])
        # Only the outlier; the foul edge is skipped because statedge is disabled.
        self.assertTrue(all(g.kind == "outlier" for g in gems))

    async def test_statedge_on_adds_model_gems(self):
        cfg = Config(ntfy_topic="t", enable_statedge=True)
        foul = FoulMatchup("Brighton vs Aston Villa", "K. Mitoma", 1.5, 1.90, 1.9, 2.8)
        card = CardsMatchup("Brighton vs Aston Villa", 4.5, 2.10, 1.8, 1.9, 5.5, 4.0)
        gems, _, _ = await self._run_tick(cfg, fouls=[foul], cards=[card])
        kinds = {g.kind for g in gems}
        self.assertIn("statedge", kinds)
        self.assertIn("outlier", kinds)

    async def test_dead_odds_feed_does_not_crash(self):
        cfg = Config(ntfy_topic="t", enable_statedge=False)

        async def boom():
            raise RuntimeError("feed down")

        seen: dict[str, float] = {}
        with mock.patch.object(monitor.notify, "alert"):
            gems = await monitor.tick(cfg, boom, None, seen)
        self.assertEqual(gems, [])                          # swallowed, loop survives


class DetectorCD(unittest.IsolatedAsyncioTestCase):
    """Detector C (goals) and D (steam) wired through tick()."""

    async def test_goals_detector_via_tick(self):
        from gembets import goals
        model = goals.GoalsModel(
            ratings={"alpha": goals.TeamRating(2.0, 0.5, 10),
                     "bravo": goals.TeamRating(0.5, 2.0, 10)},
            home_avg=1.5, away_avg=1.2)
        snap = MarketSnapshot("Alpha vs Bravo", "1X2", ("Home", "Draw", "Away"), (
            BookLine("skybet", (1.30, 9.0, 12.0)), BookLine("paddypower", (1.28, 9.0, 12.0)),
            BookLine("williamhill", (1.29, 9.0, 12.0)), BookLine("unibet", (1.30, 9.0, 12.0))))

        async def fetch_odds():
            return [snap]

        cfg = Config(ntfy_topic="t", enable_goals=True, min_lift=0.99)  # A muted
        with mock.patch.object(monitor.notify, "alert"):
            gems = await monitor.tick(cfg, fetch_odds, None, {}, goals_model=model)
        self.assertTrue(any(g.kind == "goals" for g in gems))

    async def test_steam_detector_via_tick(self):
        from gembets import steam

        def snap(bf, sky):
            return MarketSnapshot("Alpha vs Bravo", "1X2", ("Home", "Draw", "Away"), (
                BookLine("betfair_ex_uk", (bf, 3.6, 3.8)), BookLine("smarkets", (bf, 3.6, 3.8)),
                BookLine("skybet", (sky, 3.5, 3.6))))

        cfg = Config(ntfy_topic="t", enable_steam=True, min_lift=0.99)
        hist = steam.OddsHistory(window=10_000)
        seen: dict[str, float] = {}

        async def fetch1():
            return [snap(2.5, 2.5)]      # sharp Home 0.40

        async def fetch2():
            return [snap(2.0, 2.5)]      # sharp steams to 0.50, Sky Bet lags at 0.40

        with mock.patch.object(monitor.notify, "alert"):
            await monitor.tick(cfg, fetch1, None, seen, history=hist)
            gems = await monitor.tick(cfg, fetch2, None, seen, history=hist)
        self.assertTrue(any(g.kind == "steam" for g in gems))


if __name__ == "__main__":
    unittest.main()
