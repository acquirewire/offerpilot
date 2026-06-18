"""Tests for the free player-fouls detector (Detector B).
Run: python -m unittest gembets.test_player_fouls
"""
from __future__ import annotations

import unittest

from . import betfair_odds as bf
from . import player_fouls as pf
from .player_fouls import PlayerFoulQuote, PlayerFoulRate


class ExpectedFouls(unittest.TestCase):
    def test_own_rate_scaled_to_minutes(self):
        r = PlayerFoulRate(fouls_p90=2.0, minutes_expected=90.0)
        self.assertAlmostEqual(pf.expected_fouls(r), 2.0)

    def test_matchup_lifts_above_baseline(self):
        # Foul-heavy fullback (2.0/90) facing a foul-drawing winger (3.0/90 drawn).
        base = PlayerFoulRate(fouls_p90=2.0, minutes_expected=90.0)
        lifted = PlayerFoulRate(fouls_p90=2.0, opp_draw_p90=3.0, minutes_expected=90.0)
        self.assertGreater(pf.expected_fouls(lifted), pf.expected_fouls(base))


class Scan(unittest.TestCase):
    def _rates(self):
        return {"m cash": PlayerFoulRate(fouls_p90=2.8, opp_draw_p90=2.5, minutes_expected=85.0)}

    def test_flags_overpriced_over(self):
        # expected ~2.5 fouls; a 2.6 price on Over 1.5 is well above fair -> gem.
        q = PlayerFoulQuote("Villa v Brighton", "M Cash", 1.5, over_decimal=2.6, under_decimal=1.5)
        gems = pf.scan_player_fouls([q], self._rates(), min_edge=0.06)
        self.assertTrue(gems)
        self.assertEqual(gems[0].kind, "player_fouls")
        self.assertIn("M Cash", gems[0].market)

    def test_unknown_player_skipped(self):
        q = PlayerFoulQuote("X v Y", "Nobody", 1.5, over_decimal=2.6)
        self.assertEqual(pf.scan_player_fouls([q], self._rates()), [])

    def test_cap_skips_longshot(self):
        q = PlayerFoulQuote("Villa v Brighton", "M Cash", 4.5, over_decimal=9.0)
        self.assertEqual(pf.scan_player_fouls([q], self._rates(), max_odds=5.0), [])


class BetfairNormalise(unittest.TestCase):
    def test_player_from_market(self):
        self.assertEqual(bf._player_from_market("M Cash Total Fouls"), "M Cash")
        self.assertEqual(bf._player_from_market("Bukayo Saka Fouls"), "Bukayo Saka")

    def test_normalise_player_fouls(self):
        cat = [{"marketId": "1.9", "marketName": "M Cash Total Fouls",
                "event": {"name": "Villa v Brighton"},
                "runners": [{"selectionId": 1, "runnerName": "Under 1.5"},
                            {"selectionId": 2, "runnerName": "Over 1.5"}]}]
        books = [{"marketId": "1.9", "runners": [
            {"selectionId": 1, "ex": {"availableToBack": [{"price": 1.8, "size": 50}]}},
            {"selectionId": 2, "ex": {"availableToBack": [{"price": 2.1, "size": 50}]}},
        ]}]
        quotes = bf.normalise_player_fouls(cat, books)
        self.assertEqual(len(quotes), 1)
        q = quotes[0]
        self.assertEqual((q.player, q.line), ("M Cash", 1.5))
        self.assertEqual((q.over_decimal, q.under_decimal), (2.1, 1.8))


if __name__ == "__main__":
    unittest.main()
