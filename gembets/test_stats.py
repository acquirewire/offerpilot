"""Tests for the Sportmonks parsing + live-matchup assembly, all with canned data
(no key, no network). Run: python -m unittest gembets.test_stats

These lock in the field-shape assumptions documented in stats_api. If `gembets
sportmonks-probe` ever shows a mismatch against the live API, fix the parser and
update the fixture here so the contract stays pinned.
"""
from __future__ import annotations

import unittest

from . import stats_api as S
from .statedge import cards_edge, foul_edge


def _fixture():
    return {
        "id": 1, "season_id": 2025, "lineups_confirmed": True,
        "participants": [
            {"id": 10, "name": "Brighton", "meta": {"location": "home"}},
            {"id": 20, "name": "Aston Villa", "meta": {"location": "away"}},
        ],
        "referees": [
            {"type": {"name": "Assistant Referee"}, "referee": {"id": 99, "name": "Linesman"}},
            {"type": {"name": "Referee"}, "referee": {"id": 7, "name": "M. Oliver"}},
        ],
        "lineups": [
            {"team_id": 10, "type_id": 11, "player_id": 100, "player_name": "K. Mitoma",
             "position": {"name": "Left Wing"}},
            {"team_id": 10, "type_id": 11, "player_id": 101, "player_name": "S. Adingra",
             "position": {"name": "Right Wing"}},
            {"team_id": 20, "type_id": 11, "player_id": 200, "player_name": "M. Cash",
             "position": {"name": "Right Back"}},
            {"team_id": 20, "type_id": 11, "player_id": 201, "player_name": "L. Digne",
             "position": {"name": "Left Back"}},
            {"team_id": 10, "type_id": 12, "player_id": 102, "player_name": "Sub Winger",
             "position": {"name": "Right Wing"}},     # bench -> must be ignored
        ],
    }


class Parsers(unittest.TestCase):
    def test_home_away_and_name(self):
        home, away = S.home_away(_fixture())
        self.assertEqual(home["id"], 10)
        self.assertEqual(away["name"], "Aston Villa")
        self.assertEqual(S.fixture_name(_fixture()), "Brighton vs Aston Villa")

    def test_main_referee_skips_assistant(self):
        self.assertEqual(S.main_referee(_fixture())["name"], "M. Oliver")

    def test_lineups_confirmed_flag(self):
        self.assertTrue(S.lineups_confirmed(_fixture()))
        self.assertFalse(S.lineups_confirmed({"lineups": []}))

    def test_starters_exclude_bench(self):
        starters = S.starters(_fixture(), 10)
        names = {S._player_name(e) for e in starters}
        self.assertEqual(names, {"K. Mitoma", "S. Adingra"})    # Sub Winger excluded

    def test_winger_fullback_pairing_mirrors_flanks(self):
        pairs = S.pair_wingers_to_fullbacks(_fixture(), 10, 20)
        got = {(p["attacker_name"], p["defender_name"]) for p in pairs}
        # Left winger faces opposing RIGHT back; right winger faces LEFT back.
        self.assertEqual(got, {("K. Mitoma", "M. Cash"), ("S. Adingra", "L. Digne")})


class StatValues(unittest.TestCase):
    def test_num_handles_shapes(self):
        self.assertEqual(S._num({"total": 7}), 7.0)
        self.assertEqual(S._num({"average": 2.5}), 2.5)
        self.assertEqual(S._num(3), 3.0)
        self.assertIsNone(S._num({"nope": 1}))

    def test_per90_from_details(self):
        details = [{"type_id": S.FOULS_DRAWN, "value": {"total": 10}},
                   {"type_id": S.MINUTES, "value": {"total": 900}}]
        self.assertAlmostEqual(S.per90_from_details(details, S.FOULS_DRAWN), 1.0)

    def test_per90_needs_minutes(self):
        details = [{"type_id": S.FOULS_DRAWN, "value": {"total": 10}}]
        self.assertIsNone(S.per90_from_details(details, S.FOULS_DRAWN))

    def test_team_cards_per_match_by_name(self):
        details = [
            {"type": {"name": "Yellowcards"}, "value": {"total": 50}},
            {"type": {"name": "Redcards"}, "value": {"total": 5}},
            {"type": {"name": "Appearances"}, "value": {"total": 30}},
        ]
        self.assertAlmostEqual(S.team_cards_per_match(details), 55 / 30, places=4)

    def test_season_details_picks_requested_season(self):
        entity = {"statistics": [
            {"season_id": 2024, "details": [{"type_id": 1}]},
            {"season_id": 2025, "details": [{"type_id": 2}]},
        ]}
        self.assertEqual(S._season_details(entity, 2025)[0]["type_id"], 2)


class _FakeClient:
    """Stand-in for Sportmonks: returns canned rates without any HTTP."""

    async def referee_cards_pg(self, referee_id, season_id):
        return 5.5

    async def team_cards_pg(self, team_id, season_id):
        return 1.8 if team_id == 10 else 1.9

    async def player_per90(self, player_id, season_id, type_id):
        # attackers (1xx) draw 1.9 fouls/90; defenders (2xx) commit 2.8/90.
        return 1.9 if type_id == S.FOULS_DRAWN else 2.8


class LiveAssembly(unittest.IsolatedAsyncioTestCase):
    async def test_builds_priced_matchups_that_flag(self):
        def price_lookup(fixture, market, line):
            return 2.10 if "Cards" in market else 1.90

        fouls, cards = await S.build_live_matchups(
            _FakeClient(), [_fixture()], price_lookup=price_lookup)

        self.assertEqual(len(cards), 1)
        self.assertEqual(len(fouls), 2)                 # both winger/fullback pairs
        # And the assembled matchups actually clear the detectors:
        self.assertIsNotNone(cards_edge(cards[0]))
        self.assertTrue(all(foul_edge(f) for f in fouls))

    async def test_no_price_lookup_emits_nothing(self):
        # Stats still compute (and log), but with no offered price there's no gem.
        fouls, cards = await S.build_live_matchups(_FakeClient(), [_fixture()])
        self.assertEqual((fouls, cards), ([], []))

    async def test_unconfirmed_lineups_skipped(self):
        fx = _fixture()
        fx["lineups_confirmed"] = False
        fouls, cards = await S.build_live_matchups(
            _FakeClient(), [fx], price_lookup=lambda *a: 2.0)
        self.assertEqual((fouls, cards), ([], []))


if __name__ == "__main__":
    unittest.main()
