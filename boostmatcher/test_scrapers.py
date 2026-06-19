"""Tests for boost-page parsing + odds conversion + the selector engine.
Run: python -m unittest boostmatcher.test_scrapers
"""
from __future__ import annotations

import os
import unittest

from .scrapers import SelectorSpec, parse_oddschecker, parse_skybet, parse_with, to_decimal

_DIR = os.path.join(os.path.dirname(__file__), "examples")


def _read(name: str) -> str:
    with open(os.path.join(_DIR, name), encoding="utf-8") as fh:
        return fh.read()


class OddsConversion(unittest.TestCase):
    def test_fractional(self):
        self.assertAlmostEqual(to_decimal("4/1"), 5.0)
        self.assertAlmostEqual(to_decimal("10/3"), 4.3333, places=4)
        self.assertAlmostEqual(to_decimal("11/8"), 2.375)

    def test_decimal_and_evens(self):
        self.assertAlmostEqual(to_decimal("2.5"), 2.5)
        self.assertAlmostEqual(to_decimal("evens"), 2.0)
        self.assertAlmostEqual(to_decimal(" 3.75 "), 3.75)

    def test_garbage_is_none(self):
        self.assertIsNone(to_decimal(""))
        self.assertIsNone(to_decimal(None))
        self.assertIsNone(to_decimal("n/a"))
        self.assertIsNone(to_decimal("1/0"))


class SkyBetParse(unittest.TestCase):
    """Real Sky Bet card markup (Flutter hashed CSS modules) captured 2026-06-18.

    Selectors match the stable class suffixes ([class*=-runnerName] etc.) so they
    survive the hash prefix changing per deploy. Odds are decimal in the page
    (boosted in -label, struck original in -oddsboostStruckThrough). The match
    name is not on the card, so event is blank.
    """

    def setUp(self):
        self.html = _read("skybet_card_sample.html")

    def test_card_class_matches_only_the_root(self):
        # CamelCase '...Container' siblings must NOT be mistaken for card roots;
        # only the lowercase '-container' root matches -> one card each.
        self.assertEqual(len(parse_skybet(self.html)), 2)

    def test_selection_and_boosted_and_struck_odds(self):
        b = parse_skybet(self.html)[0]
        self.assertEqual(b.bookie, "skybet")
        self.assertEqual(b.selection, "Ladislav Krejci 1+ shot on target")
        self.assertAlmostEqual(b.boosted_odds, 2.5)        # -label
        self.assertAlmostEqual(b.original_odds, 2.25)      # struck-through
        self.assertEqual(b.event, "")                       # no match name on card

    def test_second_card(self):
        b = parse_skybet(self.html)[1]
        self.assertIn("England to win", b.selection)
        self.assertAlmostEqual(b.boosted_odds, 5.0)
        self.assertAlmostEqual(b.original_odds, 4.0)


class HashedClassesAndAttributeOdds(unittest.TestCase):
    """The hard real-world cases: build-hashed class names + odds in attributes."""

    def setUp(self):
        self.html = _read("hashed_boost_sample.html")

    def test_class_prefix_matches_hashed_names(self):
        spec = SelectorSpec(
            card=".PriceBoost_card*", event=".PriceBoost_event*",
            selection=".PriceBoost_selection*", now_odds=".PriceBoost_odds*")
        boosts = parse_with(self.html, "paddypower", spec)
        self.assertEqual(len(boosts), 2)
        self.assertEqual(boosts[0].event, "France v Argentina")
        self.assertIn("Mbappe", boosts[0].selection)
        self.assertAlmostEqual(boosts[0].boosted_odds, 2.5)        # 6/4 from text

    def test_odds_from_data_attribute(self):
        spec = SelectorSpec(
            card=".PriceBoost_card*", event=".PriceBoost_event*",
            selection=".PriceBoost_selection*",
            now_odds="[data-odds]::attr(data-odds)")
        boosts = parse_with(self.html, "x", spec)
        self.assertAlmostEqual(boosts[0].boosted_odds, 2.5)        # data-odds="2.5"

    def test_odds_from_aria_label(self):
        spec = SelectorSpec(
            card=".PriceBoost_card*", event=".PriceBoost_event*",
            selection=".PriceBoost_selection*",
            now_odds="span::attr(aria-label)")
        boosts = parse_with(self.html, "x", spec)
        self.assertAlmostEqual(boosts[0].boosted_odds, 2.5)        # aria-label="6/4"
        self.assertAlmostEqual(boosts[1].boosted_odds, 3.75)       # aria-label="3.75"


class OddscheckerParse(unittest.TestCase):
    """Real oddschecker structure (aggregates many books on one page).

    Hashed classes, prefix-stable. The bookie is in each logo's alt text; the
    odds use `oddBtn_*` in featured cards and `boostOddBtn_*` in list cards (the
    comma-separated now_odds selector covers both); the same boost appears in
    both layouts and is deduped.
    """

    def setUp(self):
        self.html = _read("oddschecker_sample.html")

    def test_dedupes_hero_and_list_copies(self):
        boosts = parse_oddschecker(self.html)
        self.assertEqual(len(boosts), 2)        # 3 cards, one is a hero/list dup

    def test_per_card_bookie_from_logo_alt(self):
        by_sel = {b.selection: b for b in parse_oddschecker(self.html)}
        self.assertEqual(by_sel["Score with a Header - Jovo Lukic"].bookie, "bet365")
        self.assertEqual(by_sel["Derek Cornelius to commit 2 or more fouls"].bookie, "paddy power")

    def test_both_odds_button_classes_parse(self):
        by_sel = {b.selection: b for b in parse_oddschecker(self.html)}
        self.assertAlmostEqual(by_sel["Score with a Header - Jovo Lukic"].boosted_odds, 17.0)  # 16/1
        self.assertAlmostEqual(by_sel["Derek Cornelius to commit 2 or more fouls"].boosted_odds, 2.0)  # evens


if __name__ == "__main__":
    unittest.main()
