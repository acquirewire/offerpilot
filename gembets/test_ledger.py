"""Tests for the CLV/P&L ledger. Run: python -m unittest gembets.test_ledger"""
from __future__ import annotations

import unittest

from . import ledger
from .models import GemBet


def _gem(book="coral", odds=4.0, fair=0.30, edge=0.20, kind="outlier"):
    return GemBet(fixture="A vs B", market="1X2 - Away", selection="Away", book=book,
                  decimal_odds=odds, implied_prob=1 / odds, fair_prob=fair, edge=edge,
                  kind=kind, reason="r")


class Ledger(unittest.TestCase):
    def setUp(self):
        self.conn = ledger.connect(":memory:")

    def test_record_is_idempotent(self):
        g = _gem()
        self.assertTrue(ledger.record_bet(self.conn, g, 25.0))
        self.assertFalse(ledger.record_bet(self.conn, g, 25.0))   # same key -> ignored

    def test_clv_is_ev_at_closing_prob(self):
        g = _gem(odds=4.0)
        ledger.record_bet(self.conn, g, 25.0)
        # Closing consensus prob 0.28 -> CLV = 4.0*0.28 - 1 = +0.12.
        ledger.update_closing(self.conn, g.key(), 0.28)
        row = self.conn.execute("SELECT clv_pct FROM bets WHERE key=?", (g.key(),)).fetchone()
        self.assertAlmostEqual(row["clv_pct"], 0.12, places=6)

    def test_settle_pnl(self):
        g = _gem(odds=4.0)
        ledger.record_bet(self.conn, g, 25.0)
        self.assertAlmostEqual(ledger.settle(self.conn, g.key(), "win"), 75.0)   # 25*(4-1)
        g2 = _gem(book="bet365")
        ledger.record_bet(self.conn, g2, 25.0)
        self.assertAlmostEqual(ledger.settle(self.conn, g2.key(), "loss"), -25.0)

    def test_report_aggregates_per_kind(self):
        ledger.record_bet(self.conn, _gem(book="a"), 10.0)
        ledger.record_bet(self.conn, _gem(book="b"), 10.0)
        ledger.settle(self.conn, _gem(book="a").key(), "win")
        stats = {s.kind: s for s in ledger.report(self.conn)}
        self.assertEqual(stats["outlier"].bets, 2)
        self.assertEqual(stats["outlier"].settled, 1)
        self.assertEqual(stats["outlier"].wins, 1)

    def test_clv_by_kind_needs_sample(self):
        g = _gem()
        ledger.record_bet(self.conn, g, 10.0)
        ledger.update_closing(self.conn, g.key(), 0.30)
        self.assertEqual(ledger.clv_by_kind(self.conn, min_n=20), {})   # only 1 bet
        self.assertIn("outlier", ledger.clv_by_kind(self.conn, min_n=1))


if __name__ == "__main__":
    unittest.main()
