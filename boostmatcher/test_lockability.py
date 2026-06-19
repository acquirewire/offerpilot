"""Tests for the lockability classifier.
Run: python -m unittest boostmatcher.test_lockability
"""
from __future__ import annotations

import unittest

from .lockability import classify


class Lockable(unittest.TestCase):
    def test_match_result(self):
        l = classify("France to win")
        self.assertTrue(l.lockable)
        self.assertEqual(l.market, "Match Odds")
        self.assertEqual(l.lay, "France")

    def test_over_under(self):
        l = classify("Over 2.5 goals")
        self.assertTrue(l.lockable)
        self.assertEqual(l.market, "Over/Under 2.5 Goals")

    def test_btts(self):
        l = classify("Both teams to score")
        self.assertTrue(l.lockable)
        self.assertEqual(l.market, "Both Teams to Score")

    def test_anytime_scorer(self):
        l = classify("Anytime Goalscorer - Liam Millar")
        self.assertTrue(l.lockable)
        self.assertEqual(l.market, "Anytime Goalscorer")
        self.assertIn("Millar", l.lay)


class NotLockable(unittest.TestCase):
    def test_shots_prop(self):
        self.assertFalse(classify("Lyle Foster 2+ Shots On Target").lockable)

    def test_fouls_prop(self):
        self.assertFalse(classify("Derek Cornelius to commit 2 or more fouls").lockable)

    def test_header_prop(self):
        self.assertFalse(classify("Score with a Header - Jovo Lukic").lockable)

    def test_combo(self):
        self.assertFalse(classify("Canada & Mexico Both To Win To Nil").lockable)

    def test_both_halves_special(self):
        self.assertFalse(classify("Czechia To Score In Both Halves").lockable)

    def test_htft_special(self):
        self.assertFalse(classify("Canada HT/FT").lockable)

    def test_carded_prop(self):
        self.assertFalse(classify("Teboho Mokoena to be carded").lockable)


if __name__ == "__main__":
    unittest.main()
