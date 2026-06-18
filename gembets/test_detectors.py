"""Tests for both detectors. Run: python -m unittest gembets.test_detectors"""
from __future__ import annotations

import unittest

from .models import BookLine, MarketSnapshot
from .outlier import scan_snapshot
from .statedge import CardsMatchup, FoulMatchup, cards_edge, foul_edge


def _snapshot():
    lines = [
        BookLine("pinnacle", (2.05, 3.60, 3.70)),
        BookLine("bet365", (2.00, 3.50, 3.60)),
        BookLine("williamhill", (2.10, 3.40, 3.55)),
        BookLine("unibet", (2.05, 3.55, 3.65)),
        BookLine("coral", (2.00, 3.40, 4.90)),     # outlier on Away: ~34% above typical
    ]
    return MarketSnapshot("Brighton vs Aston Villa", "1X2",
                          ("Home", "Draw", "Away"), tuple(lines))


class OutlierDetector(unittest.TestCase):
    def test_flags_the_away_outlier(self):
        gems = scan_snapshot(_snapshot(), min_lift=0.33)
        self.assertEqual(len(gems), 1)
        g = gems[0]
        self.assertEqual(g.book, "coral")
        self.assertEqual(g.selection, "Away")
        self.assertEqual(g.decimal_odds, 4.90)
        self.assertGreater(g.edge, 0.33)               # lift over the typical price
        self.assertIn("above the typical", g.reason)

    def test_small_gap_not_flagged(self):
        # Coral only ~15% above typical -> below the 33% bar.
        snap = _snapshot()
        small = MarketSnapshot(snap.fixture, snap.market, snap.labels,
                               snap.lines[:4] + (BookLine("coral", (2.00, 3.40, 4.20)),))
        self.assertEqual(scan_snapshot(small, min_lift=0.33), [])

    def test_odds_cap_skips_longshots(self):
        # A 33%+ gap, but the price is above max_odds -> skipped (chance too small).
        lines = [BookLine(f"b{i}", (1.05, 17.0, 6.0)) for i in range(4)]
        lines.append(BookLine("coral", (1.05, 17.0, 8.5)))   # 8.5 > max_odds 5.0
        snap = MarketSnapshot("Fav vs Minnow", "1X2", ("Home", "Draw", "Away"), tuple(lines))
        self.assertEqual(scan_snapshot(snap, max_odds=5.0), [])

    def test_allowlist_restricts_flagged_book(self):
        # The outlier is coral, but we only care about skybet -> nothing.
        self.assertEqual(scan_snapshot(_snapshot(), allowed_books={"skybet"}), [])
        # Put the same outlier on skybet and it flags.
        snap = _snapshot()
        with_sky = MarketSnapshot(snap.fixture, snap.market, snap.labels,
                                  snap.lines[:4] + (BookLine("skybet", (2.00, 3.40, 4.90)),))
        gems = scan_snapshot(with_sky, allowed_books={"skybet"})
        self.assertEqual([g.book for g in gems], ["skybet"])

    def test_too_few_books_returns_nothing(self):
        snap = _snapshot()
        trimmed = MarketSnapshot(snap.fixture, snap.market, snap.labels,
                                 snap.lines[:3])           # only 3 books
        self.assertEqual(scan_snapshot(trimmed, min_books=4), [])

    def test_efficient_market_no_flags(self):
        # All books agree -> no outlier.
        lines = tuple(BookLine(f"b{i}", (2.05, 3.50, 3.60)) for i in range(5))
        snap = MarketSnapshot("A vs B", "1X2", ("Home", "Draw", "Away"), lines)
        self.assertEqual(scan_snapshot(snap), [])

    def test_exchange_outlier_not_flagged(self):
        # Same generous Away price, but offered by an EXCHANGE -> never a gem.
        lines = [
            BookLine("pinnacle", (2.05, 3.60, 3.70)),
            BookLine("bet365", (2.00, 3.50, 3.60)),
            BookLine("williamhill", (2.10, 3.40, 3.55)),
            BookLine("unibet", (2.05, 3.55, 3.65)),
            BookLine("smarkets", (2.00, 3.40, 4.90)),     # exchange, not soft value
        ]
        snap = MarketSnapshot("A vs B", "1X2", ("Home", "Draw", "Away"), tuple(lines))
        self.assertEqual(scan_snapshot(snap), [])


class FoulEdge(unittest.TestCase):
    def _matchup(self, offered=1.90):
        return FoulMatchup(
            fixture="Brighton vs Aston Villa", player="K. Mitoma", opponent="M. Cash",
            line=1.5, offered_decimal=offered,
            player_fouls_won_p90=1.9, opp_defender_fouls_committed_p90=2.8,
            minutes_expected=85.0)

    def test_flags_when_fullback_inflates_expectation(self):
        g = foul_edge(self._matchup(), min_edge=0.06)
        self.assertIsNotNone(g)
        self.assertEqual(g.kind, "statedge")
        self.assertIn("fouls/90", g.reason)
        self.assertGreater(g.fair_prob, g.implied_prob)   # model beats the book

    def test_no_edge_when_price_is_short(self):
        # A miserly price (high implied prob) erases the edge.
        self.assertIsNone(foul_edge(self._matchup(offered=1.20), min_edge=0.06))


class CardsEdge(unittest.TestCase):
    def _matchup(self, offered=2.10):
        return CardsMatchup(
            fixture="Brighton vs Aston Villa", line=4.5, offered_decimal=offered,
            home_cards_p90=1.8, away_cards_p90=1.9,
            referee_cards_pg=5.5, league_avg_cards_pg=4.0, referee="M. Oliver")

    def test_referee_bias_flagged(self):
        g = cards_edge(self._matchup(), min_edge=0.06)
        self.assertIsNotNone(g)
        self.assertIn("Referee Bias", g.reason)
        self.assertGreater(g.edge, 0.06)

    def test_disciplined_ref_no_edge(self):
        # A lenient ref (below league avg) pulls expectation down -> no flag at short price.
        m = CardsMatchup("A vs B", 4.5, 2.10, 1.2, 1.1, 3.0, 4.0)
        self.assertIsNone(cards_edge(m, min_edge=0.06))


if __name__ == "__main__":
    unittest.main()
