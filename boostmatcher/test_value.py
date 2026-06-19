"""Tests for value-rating. Run: python -m unittest boostmatcher.test_value"""
from __future__ import annotations

import unittest

from .models import Boost, ExchangeQuote
from .value import fair_odds, rate_value


def _boost(b=2.5):
    return Boost(bookie="skybet", event="Czechia v South Africa", market="Boost",
                 selection="Patrik Schick to score 2+ goals", boosted_odds=b)


class FairOdds(unittest.TestCase):
    def test_midpoint_when_both_prices(self):
        # back 2.0 (p=0.5), lay 2.5 (p=0.4) -> mean p=0.45 -> fair=2.2222
        q = ExchangeQuote(exchange="betfair", lay_odds=2.5, available=100,
                          commission=0.05, back_odds=2.0)
        self.assertAlmostEqual(fair_odds(q), 2.2222, places=3)

    def test_falls_back_to_lay(self):
        q = ExchangeQuote(exchange="smarkets", lay_odds=2.4, available=100, commission=0.02)
        self.assertAlmostEqual(fair_odds(q), 2.4)


class RateValue(unittest.TestCase):
    def test_positive_edge_when_boost_beats_fair(self):
        # fair 2.0 (mid of back2.0/lay2.0), boost 2.5 -> EV = 2.5/2.0 - 1 = +25%
        q = ExchangeQuote(exchange="betfair", lay_odds=2.0, available=500,
                          commission=0.05, back_odds=2.0)
        v = rate_value(_boost(2.5), q, bankroll=1000)
        self.assertTrue(v.positive)
        self.assertAlmostEqual(v.edge_pct, 25.0, places=1)
        self.assertGreater(v.kelly_stake, 0)        # quarter-Kelly stake suggested

    def test_negative_edge_when_boost_below_fair(self):
        # fair 2.0, boost 1.8 -> EV = 1.8/2.0 - 1 = -10%  (boost is still a trap)
        q = ExchangeQuote(exchange="betfair", lay_odds=2.0, available=500,
                          commission=0.05, back_odds=2.0)
        v = rate_value(_boost(1.8), q, bankroll=1000)
        self.assertFalse(v.positive)
        self.assertAlmostEqual(v.edge_pct, -10.0, places=1)
        self.assertEqual(v.kelly_stake, 0.0)

    def test_small_edge_below_floor_stakes_nothing(self):
        # fair 2.0, boost 2.02 -> +1% edge, below the 2% noise floor -> no stake
        q = ExchangeQuote(exchange="betfair", lay_odds=2.0, available=500,
                          commission=0.05, back_odds=2.0)
        v = rate_value(_boost(2.02), q, bankroll=1000, min_edge_pct=2.0)
        self.assertTrue(v.positive)
        self.assertEqual(v.kelly_stake, 0.0)
        self.assertTrue(any("floor" in n for n in v.notes))

    def test_quarter_kelly_scaling(self):
        q = ExchangeQuote(exchange="betfair", lay_odds=2.0, available=500,
                          commission=0.05, back_odds=2.0)
        full = rate_value(_boost(2.5), q, bankroll=1000, kelly_fraction=1.0).kelly_stake
        quarter = rate_value(_boost(2.5), q, bankroll=1000, kelly_fraction=0.25).kelly_stake
        self.assertAlmostEqual(quarter, full / 4, places=2)

    def test_no_exchange_price_cant_verify(self):
        v = rate_value(_boost(2.5), None, bankroll=1000)
        self.assertFalse(v.positive)
        self.assertEqual(v.kelly_stake, 0.0)
        self.assertTrue(any("can't verify" in n for n in v.notes))


if __name__ == "__main__":
    unittest.main()
