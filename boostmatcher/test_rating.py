"""Penny-exact tests for the rating core. Run: python -m unittest boostmatcher.test_rating

Each case is worked by hand in the docstring so the maths can be audited without
trusting the code it tests.
"""
from __future__ import annotations

import unittest

from .models import Boost, ExchangeQuote
from .rating import best_of, compute_lay, rate


def _boost(b: float, orig: float | None = None, cap: float | None = None) -> Boost:
    return Boost(bookie="skybet", event="England v USA", market="Match Result",
                 selection="England to win", boosted_odds=b, original_odds=orig, max_stake=cap)


class ComputeLay(unittest.TestCase):
    def test_clean_zero_commission_lock(self):
        # Back £10 @ 3.0, lay @ 2.0, 0% comm.
        #   lay = 30/2 = 15 ; liability = 15*1 = 15
        #   win  = 10*2 - 15 = 5 ; lose = 15 - 10 = 5  -> equal, rating 50%
        lay, liab, win, lose = compute_lay(10, 3.0, 2.0, 0.0)
        self.assertAlmostEqual(lay, 15.0, places=4)
        self.assertAlmostEqual(liab, 15.0, places=4)
        self.assertAlmostEqual(win, 5.0, places=4)
        self.assertAlmostEqual(lose, 5.0, places=4)

    def test_realistic_boost_with_commission(self):
        # Back £10 @ 4.0 (boosted), lay @ 3.2, 2% comm (Smarkets).
        #   lay = 40/3.18 = 12.5786 ; liability = 12.5786*2.2 = 27.6730
        #   win  = 30 - 27.6730 = 2.3270 ; lose = 12.5786*0.98 - 10 = 2.3270
        lay, liab, win, lose = compute_lay(10, 4.0, 3.2, 0.02)
        self.assertAlmostEqual(lay, 12.5786, places=3)
        self.assertAlmostEqual(win, 2.3270, places=3)
        self.assertAlmostEqual(lose, 2.3270, places=3)
        self.assertAlmostEqual(win, lose, places=6)   # the equal-profit invariant

    def test_profits_are_always_equal(self):
        # The whole point of the equal-profit lay: win == lose for any inputs.
        for B, L, c in [(5.0, 4.5, 0.05), (2.5, 2.1, 0.02), (10.0, 6.0, 0.0)]:
            _, _, win, lose = compute_lay(25, B, L, c)
            self.assertAlmostEqual(win, lose, places=6, msg=f"B={B} L={L} c={c}")

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            compute_lay(10, 3.0, 1.0, 0.0)        # lay odds must be > 1
        with self.assertRaises(ValueError):
            compute_lay(10, 3.0, 2.0, 1.5)        # commission out of range


class Rate(unittest.TestCase):
    def test_positive_boost_is_lockable(self):
        q = ExchangeQuote(exchange="smarkets", lay_odds=3.2, available=500, commission=0.02)
        r = rate(_boost(4.0, orig=3.0), q, back_stake=10)
        self.assertTrue(r.lockable)
        self.assertAlmostEqual(r.rating, 23.27, places=1)
        self.assertTrue(any("vs pre-boost" in n for n in r.notes))

    def test_bad_boost_not_lockable(self):
        # Lay price ABOVE back price => you lose on both legs.
        q = ExchangeQuote(exchange="smarkets", lay_odds=2.5, available=500, commission=0.02)
        r = rate(_boost(2.0), q, back_stake=10)
        self.assertFalse(r.lockable)
        self.assertLess(r.rating, 0)

    def test_thin_liquidity_flagged(self):
        q = ExchangeQuote(exchange="betfair", lay_odds=3.2, available=5, commission=0.05)
        r = rate(_boost(4.0), q, back_stake=10)
        self.assertTrue(any("thin" in n for n in r.notes))

    def test_stake_cap_flagged(self):
        q = ExchangeQuote(exchange="smarkets", lay_odds=3.2, available=500, commission=0.02)
        r = rate(_boost(4.0, cap=5), q, back_stake=10)
        self.assertTrue(any("exceeds boost cap" in n for n in r.notes))


class BestOf(unittest.TestCase):
    def test_picks_highest_rating_exchange(self):
        # Betfair lays tighter (3.1) but charges 5%; Smarkets 3.2 @ 2%.
        # Lower lay odds AND lower commission both help -> Smarkets here wins on
        # price, but we just assert it returns the better of the two ratings.
        bf = ExchangeQuote(exchange="betfair", lay_odds=3.1, available=500, commission=0.05)
        sm = ExchangeQuote(exchange="smarkets", lay_odds=3.2, available=500, commission=0.02)
        r = best_of(_boost(4.0), [bf, sm], back_stake=10)
        best = max(rate(_boost(4.0), bf, 10).rating, rate(_boost(4.0), sm, 10).rating)
        self.assertEqual(r.rating, best)

    def test_no_quotes_returns_unmatched(self):
        r = best_of(_boost(4.0), [], back_stake=10)
        self.assertIsNone(r.quote)
        self.assertFalse(r.lockable)


if __name__ == "__main__":
    unittest.main()
