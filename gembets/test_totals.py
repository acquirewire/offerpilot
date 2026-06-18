"""Tests for the multi-market team-totals model (Detector E).
Run: python -m unittest gembets.test_totals
"""
from __future__ import annotations

import unittest

from . import totals
from .totals import RefereeModel, StatModel, TeamRate, TotalsModel

_CSV = (
    "Div,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,Referee\n"
    "E0,Alpha,Bravo,1,1,12,8,5,3,11,10,10,3,3,3,0,1,Strict\n"
    "E0,Bravo,Alpha,0,2,8,14,2,6,12,9,2,9,2,4,0,0,Strict\n"
    "E0,Alpha,Charlie,3,1,15,7,7,2,9,13,11,4,1,1,0,0,Lenient\n"
    "E0,Charlie,Alpha,1,2,9,12,3,5,10,11,5,8,0,1,0,0,Lenient\n"
    "E0,Bravo,Charlie,1,1,10,10,4,4,14,12,3,5,2,3,1,0,Strict\n"
    "E0,Charlie,Bravo,2,0,11,9,5,3,13,11,6,2,1,0,0,0,Lenient\n"
)


class Parsing(unittest.TestCase):
    def test_parses_all_stats(self):
        matches = totals.parse_matches(_CSV)
        self.assertEqual(len(matches), 6)
        m = matches[0]
        self.assertEqual(m.referee, "Strict")
        self.assertEqual(m.stats["corners"], (10.0, 3.0))
        # cards = yellows + reds per side: home 3+0, away 3+1
        self.assertEqual(m.stats["cards"], (3.0, 4.0))
        self.assertIn("shots_on_target", m.stats)


class StatFitting(unittest.TestCase):
    def test_corner_heavy_team_rated_higher(self):
        model = totals.build(totals.parse_matches(_CSV))
        corners = model.stats["corners"]
        self.assertGreater(corners.rates["alpha"].for_rate, corners.rates["bravo"].for_rate)

    def test_expected_total_is_two_sided_sum(self):
        model = totals.build(totals.parse_matches(_CSV))
        exp = model.expected_total("corners", "Alpha", "Bravo")
        self.assertIsNotNone(exp)
        self.assertGreater(exp, 0)

    def test_unknown_team_returns_none(self):
        model = totals.build(totals.parse_matches(_CSV))
        self.assertIsNone(model.expected_total("corners", "Alpha", "Nobody"))


class Referees(unittest.TestCase):
    def test_factor_scales_by_strictness(self):
        rm = RefereeModel(cards_pg={"strict": 6.0, "lenient": 2.0},
                          games={"strict": 10, "lenient": 10}, league_avg=4.0)
        self.assertAlmostEqual(rm.factor("Strict"), 1.5)
        self.assertAlmostEqual(rm.factor("Lenient"), 0.5)

    def test_unknown_or_thin_referee_is_neutral(self):
        rm = RefereeModel(cards_pg={"strict": 6.0}, games={"strict": 2}, league_avg=4.0)
        self.assertEqual(rm.factor("Nobody"), 1.0)        # unknown
        self.assertEqual(rm.factor("Strict"), 1.0)        # < min_games

    def test_card_total_multiplied_by_referee(self):
        sm = StatModel(rates={"alpha": TeamRate(1.0, 1.0, 5), "bravo": TeamRate(1.0, 1.0, 5)},
                       home_avg=2.0, away_avg=2.0)
        rm = RefereeModel(cards_pg={"strict": 6.0}, games={"strict": 10}, league_avg=4.0)
        tm = TotalsModel(stats={"cards": sm}, referees=rm)
        base = tm.expected_total("cards", "Alpha", "Bravo")
        strict = tm.expected_total("cards", "Alpha", "Bravo", referee="Strict")
        self.assertAlmostEqual(base, 4.0)                 # 2.0 + 2.0
        self.assertAlmostEqual(strict, 6.0)               # x1.5 referee factor


class Pricing(unittest.TestCase):
    def _model(self):
        return totals.build(totals.parse_matches(_CSV))

    def test_fair_lines_cover_markets(self):
        rows = totals.fair_lines(self._model(), "Alpha", "Bravo")
        markets = {r.market for r in rows}
        self.assertIn("corners", markets)
        self.assertIn("cards", markets)
        for r in rows:
            self.assertAlmostEqual(r.fair_over, 1.0 / r.prob_over, places=6)

    def test_check_flags_value_against_model(self):
        # Alpha are corner-heavy; offering a generous Over price should be a gem.
        model = self._model()
        exp = model.expected_total("corners", "Alpha", "Bravo")
        res = totals.check(model, "Alpha", "Bravo", "corners", exp - 2.0, 2.5)
        self.assertIsNotNone(res)
        self.assertTrue(res["has_edge"])      # line below expected + a fat price

    def test_check_unknown_market_none(self):
        self.assertIsNone(totals.check(self._model(), "X", "Y", "corners", 9.5, 2.0))


if __name__ == "__main__":
    unittest.main()
