"""Tests for cross-book cover (Dutching) maths + complement derivation.
Run: python -m unittest boostmatcher.test_cover
"""
from __future__ import annotations

import unittest

from .cover import CoverLeg, complement, rate_cover
from .models import Boost


def _boost(sel="Krejci 1+ shot on target", b=2.5):
    return Boost(bookie="skybet", event="Czechia v South Africa", market="Boost",
                 selection=sel, boosted_odds=b)


class RateCover(unittest.TestCase):
    def test_two_way_lock(self):
        # boost 2.5 (40%) + opposite 1.8 (55.6%) = 95.6% < 100% -> lock.
        legs = [CoverLeg(bookie="bet365", selection="0 shots", odds=1.8)]
        r = rate_cover(_boost(), legs, back_stake=25)
        self.assertTrue(r.lock)
        self.assertAlmostEqual(r.book_sum, 0.9556, places=3)
        # R=62.5; cover stake=62.5/1.8=34.72; total=59.72; profit=2.78
        self.assertAlmostEqual(r.leg_stakes[0], 34.72, places=2)
        self.assertAlmostEqual(r.total_stake, 59.72, places=2)
        self.assertAlmostEqual(r.guaranteed_profit, 2.78, places=2)
        self.assertAlmostEqual(r.roi_pct, 4.65, places=1)

    def test_two_way_no_lock(self):
        # opposite only 1.5 (66.7%) -> 106.7% > 100% -> no lock, negative profit.
        legs = [CoverLeg(bookie="bet365", selection="0 shots", odds=1.5)]
        r = rate_cover(_boost(), legs, back_stake=25)
        self.assertFalse(r.lock)
        self.assertLess(r.guaranteed_profit, 0)
        self.assertTrue(any("no lock" in n for n in r.notes))

    def test_three_way_dutch_lock(self):
        # England win 2.5 + Draw 3.5 + SA win 4.0 = 93.6% -> lock with two covers.
        b = _boost(sel="England to win", b=2.5)
        legs = [CoverLeg("bet365", "Draw", 3.5), CoverLeg("williamhill", "South Africa", 4.0)]
        r = rate_cover(b, legs, back_stake=25)
        self.assertTrue(r.lock)
        self.assertAlmostEqual(r.book_sum, 0.9357, places=3)
        self.assertEqual(len(r.leg_stakes), 2)
        # profit identical whichever wins -> positive
        self.assertGreater(r.guaranteed_profit, 0)

    def test_no_legs(self):
        r = rate_cover(_boost(), [], back_stake=25)
        self.assertFalse(r.lock)
        self.assertTrue(any("no opposite" in n for n in r.notes))


class Complement(unittest.TestCase):
    def test_n_plus(self):
        self.assertEqual(complement("Krejci 1+ shot on target"), ["under 1 shot on target"])
        self.assertEqual(complement("Schick 2+ goals"), ["under 2 goals"])

    def test_over_under(self):
        self.assertEqual(complement("Over 2.5 goals"), ["under 2.5 goals"])
        self.assertEqual(complement("under 3.5 cards"), ["over 3.5 cards"])

    def test_yes_no_and_btts(self):
        self.assertEqual(complement("Both teams to score - Yes"), ["both teams to score - no"])
        self.assertEqual(complement("both teams to score"), ["both teams to score - no"])

    def test_carded(self):
        self.assertEqual(complement("Mokoena to be carded"), ["not mokoena to be carded"])

    def test_no_clean_opposite(self):
        self.assertIsNone(complement("Lamine Yamal anytime scorer"))


if __name__ == "__main__":
    unittest.main()
