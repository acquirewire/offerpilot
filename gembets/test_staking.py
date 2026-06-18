"""Tests for Kelly staking. Run: python -m unittest gembets.test_staking"""
from __future__ import annotations

import unittest

from .staking import kelly_stake


class Kelly(unittest.TestCase):
    def test_no_stake_without_edge(self):
        # fair 0.50, odds 2.0 -> EV 0 -> no bet.
        self.assertEqual(kelly_stake(0.50, 2.0, 1000).stake, 0.0)
        self.assertEqual(kelly_stake(0.40, 2.0, 1000).stake, 0.0)   # negative EV

    def test_full_kelly_formula(self):
        # fair 0.60, odds 2.0: full f = (0.6*2 - 1)/(2-1) = 0.20.
        plan = kelly_stake(0.60, 2.0, 1000, fraction=1.0, max_fraction=1.0)
        self.assertAlmostEqual(plan.full_kelly, 0.20, places=4)
        self.assertAlmostEqual(plan.stake, 200.0, places=2)

    def test_quarter_kelly_scales(self):
        plan = kelly_stake(0.60, 2.0, 1000, fraction=0.25, max_fraction=1.0)
        self.assertAlmostEqual(plan.stake, 50.0, places=2)          # 200 * 0.25

    def test_max_fraction_cap(self):
        # Big edge would want a big stake; capped at 5% of bankroll.
        plan = kelly_stake(0.90, 2.0, 1000, fraction=1.0, max_fraction=0.05)
        self.assertEqual(plan.stake, 50.0)
        self.assertEqual(plan.capped_by, "max_fraction")

    def test_max_stake_cap(self):
        plan = kelly_stake(0.60, 2.0, 10000, fraction=1.0, max_fraction=1.0, max_stake=100.0)
        self.assertEqual(plan.stake, 100.0)
        self.assertEqual(plan.capped_by, "max_stake")


if __name__ == "__main__":
    unittest.main()
