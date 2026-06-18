"""Tests for the maths core. Run: python -m unittest gembets.test_odds"""
from __future__ import annotations

import unittest

from .odds import (american_to_decimal, consensus_fair_prob, decimal_to_implied,
                   devig_proportional, evaluate_value, market_margin, poisson_cdf,
                   poisson_pmf, prob_over_line)


class Conversions(unittest.TestCase):
    def test_american_positive(self):
        self.assertAlmostEqual(american_to_decimal(250), 3.50, places=4)

    def test_american_negative(self):
        self.assertAlmostEqual(american_to_decimal(-120), 1.8333, places=3)

    def test_decimal_to_implied(self):
        self.assertAlmostEqual(decimal_to_implied(4.0), 0.25)


class Devig(unittest.TestCase):
    def test_probs_sum_to_one(self):
        fair = devig_proportional([2.0, 3.5, 4.0])
        self.assertAlmostEqual(sum(fair), 1.0, places=9)

    def test_margin_is_overround_minus_one(self):
        # 1/2 + 1/4 + 1/4 = 1.0 exactly -> a 0% (theoretical) margin
        self.assertAlmostEqual(market_margin([2.0, 4.0, 4.0]), 0.0, places=9)
        # tighter prices -> positive margin
        self.assertGreater(market_margin([1.9, 3.5, 3.8]), 0.0)


class Consensus(unittest.TestCase):
    def _books(self):
        # Home, Draw, Away. One book (idx -> "coral") is a fat outlier on Away.
        return {
            "pinnacle": [2.05, 3.60, 3.70],
            "bet365": [2.00, 3.50, 3.60],
            "williamhill": [2.10, 3.40, 3.55],
            "unibet": [2.05, 3.55, 3.65],
            "coral": [2.00, 3.40, 4.20],
        }

    def test_median_is_robust_to_outlier(self):
        # The away outlier (coral, 4.20) must NOT drag the consensus it's judged against.
        fair_away = consensus_fair_prob(self._books(), outcome_index=2)
        # Median of the five de-vigged away probs sits ~0.26, near the tight books.
        self.assertTrue(0.255 < fair_away < 0.27, fair_away)

    def test_raises_without_quotes(self):
        with self.assertRaises(ValueError):
            consensus_fair_prob({}, 0)


class Value(unittest.TestCase):
    def test_positive_ev_flagged(self):
        # fair 26%, price 4.20 -> EV = 0.26*4.20 - 1 = +9.2%
        sig = evaluate_value(4.20, 0.26, min_edge=0.04)
        self.assertTrue(sig.has_edge)
        self.assertAlmostEqual(sig.edge, 0.092, places=3)

    def test_below_threshold_not_flagged(self):
        sig = evaluate_value(3.70, 0.26, min_edge=0.04)   # EV = -3.8%
        self.assertFalse(sig.has_edge)

    def test_lift_vs_market(self):
        # offered implied 1/4.0 = 25%, fair 30% -> 20% payout lift
        sig = evaluate_value(4.0, 0.30)
        self.assertAlmostEqual(sig.lift_vs_market, 0.20, places=6)


class Poisson(unittest.TestCase):
    def test_pmf_known_value(self):
        # Poisson(2) at k=0 is e^-2 = 0.13534
        self.assertAlmostEqual(poisson_pmf(0, 2.0), 0.135335, places=5)

    def test_cdf_monotone_and_bounded(self):
        self.assertAlmostEqual(poisson_cdf(0, 2.0), poisson_pmf(0, 2.0))
        self.assertTrue(0 < poisson_cdf(3, 2.0) < 1)

    def test_over_line_uses_floor(self):
        # Over 1.5 wins on X>=2 == 1 - P(X<=1). For mu=2.0: 1 - (0.1353+0.2707)=0.5940
        self.assertAlmostEqual(prob_over_line(2.0, 1.5), 0.593994, places=5)

    def test_zero_expected_is_zero(self):
        self.assertEqual(prob_over_line(0.0, 1.5), 0.0)


if __name__ == "__main__":
    unittest.main()
