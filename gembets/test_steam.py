"""Tests for the line-movement / steam detector (Detector D).
Run: python -m unittest gembets.test_steam
"""
from __future__ import annotations

import unittest

from . import steam
from .models import BookLine, MarketSnapshot


def _snap(bf_home, sm_home, sky_home):
    """1X2 snapshot with two exchanges + Sky Bet; only Home odds vary per test."""
    lines = (
        BookLine("betfair_ex_uk", (bf_home, 3.6, 3.8)),
        BookLine("smarkets", (sm_home, 3.6, 3.8)),
        BookLine("skybet", (sky_home, 3.5, 3.6)),
    )
    return MarketSnapshot("Alpha vs Bravo", "1X2", ("Home", "Draw", "Away"), lines)


class History(unittest.TestCase):
    def test_record_and_earliest(self):
        h = steam.OddsHistory(window=10_000)
        h.record([_snap(2.5, 2.5, 2.5)], now=1000)
        h.record([_snap(2.0, 2.0, 2.4)], now=1001)
        # earliest Home implied for a sharp book stays the first sample (1/2.5).
        self.assertAlmostEqual(h.earliest("Alpha vs Bravo", "1X2", 0, "betfair_ex_uk"), 0.4)

    def test_prunes_outside_window(self):
        h = steam.OddsHistory(window=5)
        h.record([_snap(2.5, 2.5, 2.5)], now=1000)
        h.record([_snap(2.0, 2.0, 2.4)], now=1010)        # 10s later, window 5s
        # old sample pruned -> earliest is now the second one (1/2.0 = 0.5).
        self.assertAlmostEqual(h.earliest("Alpha vs Bravo", "1X2", 0, "betfair_ex_uk"), 0.5)


class Detect(unittest.TestCase):
    def _warm(self, window=10_000):
        h = steam.OddsHistory(window=window)
        h.record([_snap(2.5, 2.5, 2.5)], now=1000)        # sharp Home implied 0.40
        return h

    def test_flags_soft_book_lagging_a_steam_move(self):
        h = self._warm()
        # Sharp shortens Home to 2.0 (implied 0.50); Sky Bet still 2.5 (0.40).
        snaps = [_snap(2.0, 2.0, 2.5)]
        h.record(snaps, now=1001)
        gems = steam.detect(h, snaps, move_threshold=0.03, gap_threshold=0.05,
                            allowed_books={"skybet"})
        self.assertEqual(len(gems), 1)
        g = gems[0]
        self.assertEqual((g.book, g.selection, g.kind), ("skybet", "Home", "steam"))
        self.assertGreater(g.edge, 0)

    def test_no_flag_when_soft_already_moved(self):
        h = self._warm()
        # Sharp moved to 0.50, but Sky Bet also moved to 2.05 (~0.49) -> caught up.
        snaps = [_snap(2.0, 2.0, 2.05)]
        h.record(snaps, now=1001)
        gems = steam.detect(h, snaps, gap_threshold=0.05, allowed_books={"skybet"})
        self.assertEqual(gems, [])

    def test_no_flag_without_enough_movement(self):
        h = self._warm()
        # Sharp barely moved (2.5 -> 2.45, ~+1pt) < 3pt threshold.
        snaps = [_snap(2.45, 2.45, 2.5)]
        h.record(snaps, now=1001)
        gems = steam.detect(h, snaps, move_threshold=0.03, allowed_books={"skybet"})
        self.assertEqual(gems, [])

    def test_silent_on_first_tick(self):
        # No prior history -> nothing to compare against.
        h = steam.OddsHistory()
        snaps = [_snap(2.0, 2.0, 2.5)]
        h.record(snaps, now=1000)
        self.assertEqual(steam.detect(h, snaps, allowed_books={"skybet"}), [])


if __name__ == "__main__":
    unittest.main()
