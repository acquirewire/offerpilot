"""Tests for arbitrage detection. Run: python -m unittest gembets.test_arb"""
from __future__ import annotations

import unittest

from . import arb
from .models import BookLine, MarketSnapshot


class FindArb(unittest.TestCase):
    def test_flags_a_real_arb(self):
        # Best price per outcome across books sums to < 1 -> guaranteed profit.
        lines = (
            BookLine("a", (2.10, 3.40, 3.60)),
            BookLine("b", (2.05, 3.70, 3.50)),
            BookLine("c", (2.20, 3.50, 4.10)),   # best Away 4.10
        )
        # best: Home 2.20(c), Draw 3.70(b), Away 4.10(c): 1/2.2+1/3.7+1/4.1 = 0.957 < 1
        snap = MarketSnapshot("A vs B", "1X2", ("Home", "Draw", "Away"), lines)
        g = arb.find_arb(snap)
        self.assertIsNotNone(g)
        self.assertEqual(g.kind, "arb")
        self.assertGreater(g.edge, 0.0)
        self.assertIn("Arbitrage", g.reason)

    def test_no_arb_on_normal_market(self):
        lines = tuple(BookLine(f"b{i}", (2.0, 3.4, 3.6)) for i in range(3))
        snap = MarketSnapshot("A vs B", "1X2", ("Home", "Draw", "Away"), lines)
        self.assertIsNone(arb.find_arb(snap))

    def test_needs_two_books(self):
        snap = MarketSnapshot("A vs B", "1X2", ("Home", "Draw", "Away"),
                              (BookLine("a", (10.0, 10.0, 10.0)),))
        self.assertIsNone(arb.find_arb(snap))


if __name__ == "__main__":
    unittest.main()
