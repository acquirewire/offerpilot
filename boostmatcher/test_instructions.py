"""Tests for the £ lay-plan builder. Run: python -m unittest boostmatcher.test_instructions"""
from __future__ import annotations

import unittest

from .instructions import plan
from .models import Boost, ExchangeQuote
from .rating import best_of, rate


def _rated(b=2.5, lay=2.32, comm=0.02, stake=25.0):
    boost = Boost(bookie="skybet", event="England v USA", market="Match Result",
                  selection="England to win", boosted_odds=b, original_odds=2.1)
    q = ExchangeQuote(exchange="smarkets", lay_odds=lay, available=900,
                      commission=comm, runner="England")
    return rate(boost, q, stake)


class PlanMaths(unittest.TestCase):
    def test_back_returns_and_lay_amounts(self):
        p = plan(_rated())
        self.assertAlmostEqual(p.back_returns, 62.50, places=2)   # 25 * 2.5
        # lay = 2.5*25/(2.32-0.02) = 62.5/2.30 = 27.17
        self.assertAlmostEqual(p.lay_stake, 27.17, places=2)
        # liability = 27.17 * 1.32 = 35.87
        self.assertAlmostEqual(p.liability, 35.87, places=2)

    def test_guaranteed_is_min_of_outcomes(self):
        p = plan(_rated())
        self.assertAlmostEqual(p.guaranteed, min(p.profit_if_wins, p.profit_if_loses), places=2)
        self.assertGreater(p.guaranteed, 0)        # this boost is a genuine lock

    def test_steps_mention_pounds_and_lay_amount(self):
        steps = plan(_rated()).steps()
        self.assertEqual(len(steps), 5)
        self.assertIn("BACK £25.00", steps[0])
        self.assertIn("LAY", steps[1])
        self.assertIn("Guaranteed profit", steps[4])

    def test_unmatched_boost_has_no_plan(self):
        boost = Boost(bookie="skybet", event="x", market="Anytime Scorer",
                      selection="Player anytime scorer", boosted_odds=4.0)
        self.assertIsNone(plan(best_of(boost, [], 25.0)))


if __name__ == "__main__":
    unittest.main()
