"""Tests for the goals model (Detector C). Run: python -m unittest gembets.test_goals"""
from __future__ import annotations

import unittest

from . import goals
from .models import BookLine, MarketSnapshot


class NameMatching(unittest.TestCase):
    def test_strips_suffix_and_punct(self):
        self.assertEqual(goals.normalise("Brighton & Hove Albion FC"), "brighton  hove albion")

    def test_aliases(self):
        self.assertEqual(goals.normalise("Man City"), "manchester city")
        self.assertEqual(goals.normalise("Spurs"), "tottenham")


class Fit(unittest.TestCase):
    def _results(self):
        return [
            ("Alpha", "Bravo", 4, 0), ("Bravo", "Alpha", 0, 3),
            ("Alpha", "Charlie", 3, 1), ("Charlie", "Alpha", 1, 2),
            ("Bravo", "Charlie", 1, 1), ("Charlie", "Bravo", 2, 0),
        ]

    def test_fit_rates_strong_team_higher(self):
        m = goals.fit(self._results())
        self.assertGreater(m.ratings["alpha"].attack, m.ratings["bravo"].attack)
        self.assertLess(m.ratings["alpha"].defence, m.ratings["bravo"].defence)

    def test_expected_goals_favours_strong_home(self):
        m = goals.fit(self._results())
        lam = m.expected_goals("Alpha", "Bravo")
        self.assertIsNotNone(lam)
        self.assertGreater(lam[0], lam[1])

    def test_unknown_team_returns_none(self):
        m = goals.fit(self._results())
        self.assertIsNone(m.expected_goals("Alpha", "Nobody"))


class MarketProbs(unittest.TestCase):
    def test_1x2_sums_to_one(self):
        p = goals.market_probs(1.6, 1.1)["1X2"]
        self.assertAlmostEqual(sum(p), 1.0, places=4)

    def test_over_and_btts_in_range(self):
        probs = goals.market_probs(1.6, 1.1)
        over = probs["Over/Under 2.5"][0]
        btts = probs["BTTS"][0]
        self.assertTrue(0 < over < 1 and 0 < btts < 1)

    def test_high_scoring_lifts_over(self):
        low = goals.market_probs(0.7, 0.6)["Over/Under 2.5"][0]
        high = goals.market_probs(2.4, 2.0)["Over/Under 2.5"][0]
        self.assertGreater(high, low)


class Scan(unittest.TestCase):
    def _model(self):
        # Hand-built so the maths is deterministic: Alpha crushes Bravo.
        return goals.GoalsModel(
            ratings={"alpha": goals.TeamRating(2.0, 0.5, 10),
                     "bravo": goals.TeamRating(0.5, 2.0, 10)},
            home_avg=1.5, away_avg=1.2)

    def test_flags_value_vs_model(self):
        # lambda ~ 6.0 / 0.3 -> Home ~ certain; a 1.30 home price is big value.
        lines = (BookLine("skybet", (1.30, 9.0, 12.0)),
                 BookLine("paddypower", (1.28, 9.0, 12.0)),
                 BookLine("williamhill", (1.29, 9.0, 12.0)),
                 BookLine("unibet", (1.30, 9.0, 12.0)))
        snap = MarketSnapshot("Alpha vs Bravo", "1X2", ("Home", "Draw", "Away"), lines)
        gems = goals.scan_snapshot(snap, self._model(), min_edge=0.05)
        self.assertTrue(gems)
        self.assertTrue(all(g.selection == "Home" and g.kind == "goals" for g in gems))

    def test_respects_allowlist_and_cap(self):
        lines = (BookLine("skybet", (1.30, 9.0, 12.0)),
                 BookLine("betfred", (1.30, 9.0, 12.0)),
                 BookLine("paddypower", (1.30, 9.0, 12.0)),
                 BookLine("unibet", (1.30, 9.0, 12.0)))
        snap = MarketSnapshot("Alpha vs Bravo", "1X2", ("Home", "Draw", "Away"), lines)
        gems = goals.scan_snapshot(snap, self._model(), min_edge=0.05,
                                   allowed_books={"skybet"})
        self.assertEqual({g.book for g in gems}, {"skybet"})

    def test_unknown_fixture_skipped(self):
        lines = (BookLine("skybet", (1.30, 9.0, 12.0)),) * 1
        snap = MarketSnapshot("X vs Y", "1X2", ("Home", "Draw", "Away"), lines)
        self.assertEqual(goals.scan_snapshot(snap, self._model()), [])


class CsvParse(unittest.TestCase):
    def test_parse_footballdata(self):
        csv = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
               "E0,10/08/2025,Arsenal,Chelsea,2,1,H\n"
               "E0,10/08/2025,Spurs,Everton,0,0,D\n"
               "E0,11/08/2025,Bad,Row,,,\n")          # unplayed -> skipped
        rows = goals.parse_footballdata_csv(csv)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ("Arsenal", "Chelsea", 2, 1))


if __name__ == "__main__":
    unittest.main()
