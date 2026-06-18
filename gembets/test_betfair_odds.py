"""Tests for the Betfair totals adapter + the totals quote-scanner.
Run: python -m unittest gembets.test_betfair_odds

The live Betfair calls need your key (verify with `gembets betfair-probe`); the
JSON->TotalQuote normalisation and the mispricing scan are pinned here offline.
"""
from __future__ import annotations

import unittest

from . import betfair_odds as bf
from . import totals
from .totals import StatModel, TeamRate, TotalQuote, TotalsModel, RefereeModel


class Classify(unittest.TestCase):
    def test_market_kinds(self):
        self.assertEqual(bf.classify_market("Over/Under 10.5 Corners"), "corners")
        self.assertEqual(bf.classify_market("Over/Under 30.5 Bookings"), "booking_points")
        self.assertEqual(bf.classify_market("Over/Under 3.5 Cards"), "cards")  # count, not points
        self.assertEqual(bf.classify_market("Match Shots"), "shots")
        self.assertEqual(bf.classify_market("Match Shots on Target"), "shots_on_target")
        self.assertEqual(bf.classify_market("Over/Under 2.5 Goals"), "goals")
        self.assertIsNone(bf.classify_market("Match Odds"))

    def test_parse_line(self):
        self.assertEqual(bf.parse_line("Over/Under 10.5 Corners"), 10.5)
        self.assertEqual(bf.parse_line("Over/Under 2.5 Goals"), 2.5)
        self.assertIsNone(bf.parse_line("Match Odds"))


class Normalise(unittest.TestCase):
    def _catalogue(self):
        return [{
            "marketId": "1.1", "marketName": "Over/Under 10.5 Corners",
            "event": {"name": "Arsenal v Chelsea"},
            "runners": [{"selectionId": 1, "runnerName": "Under 10.5"},
                        {"selectionId": 2, "runnerName": "Over 10.5"}],
        }]

    def _books(self):
        return [{"marketId": "1.1", "runners": [
            {"selectionId": 1, "ex": {"availableToBack": [{"price": 1.95, "size": 100}]}},
            {"selectionId": 2, "ex": {"availableToBack": [{"price": 2.02, "size": 100}]}},
        ]}]

    def test_builds_total_quote(self):
        quotes = bf.normalise_markets(self._catalogue(), self._books())
        self.assertEqual(len(quotes), 1)
        q = quotes[0]
        self.assertEqual((q.fixture, q.market, q.line), ("Arsenal v Chelsea", "corners", 10.5))
        self.assertEqual((q.over_decimal, q.under_decimal), (2.02, 1.95))

    def test_skips_unmodellable_market(self):
        cat = [{"marketId": "1.2", "marketName": "Match Odds",
                "event": {"name": "A v B"}, "runners": []}]
        self.assertEqual(bf.normalise_markets(cat, []), [])


class ScanQuotes(unittest.TestCase):
    def _model(self):
        # Corner-heavy fixture: expected total ~ 12 corners.
        sm = StatModel(rates={"alpha": TeamRate(1.5, 1.0, 10), "bravo": TeamRate(1.5, 1.0, 10)},
                       home_avg=4.0, away_avg=4.0)
        return TotalsModel(stats={"corners": sm}, referees=RefereeModel({}, {}, 0.0))

    def test_flags_overpriced_over(self):
        # expected = 4*1.5 + 4*1.5 = 12 corners; Over 9.5 is very likely. A 2.5
        # price on Over 9.5 is way above fair -> gem.
        q = TotalQuote("Alpha v Bravo", "corners", 9.5, over_decimal=2.5, under_decimal=1.5)
        gems = totals.scan_quotes(self._model(), [q], min_edge=0.05)
        self.assertTrue(gems)
        self.assertEqual(gems[0].selection, "Over 9.5")
        self.assertEqual(gems[0].kind, "totals")

    def test_no_gem_on_fair_price(self):
        q = TotalQuote("Alpha v Bravo", "corners", 9.5, over_decimal=1.05, under_decimal=15.0)
        self.assertEqual(totals.scan_quotes(self._model(), [q], min_edge=0.05), [])

    def test_unknown_team_skipped(self):
        q = TotalQuote("X v Y", "corners", 9.5, over_decimal=2.5)
        self.assertEqual(totals.scan_quotes(self._model(), [q]), [])

    def test_respects_max_odds(self):
        # Over priced 8.0 (longshot) is skipped even if value, by the cap.
        q = TotalQuote("Alpha v Bravo", "corners", 15.5, over_decimal=8.0)
        self.assertEqual(totals.scan_quotes(self._model(), [q], max_odds=5.0), [])


if __name__ == "__main__":
    unittest.main()
