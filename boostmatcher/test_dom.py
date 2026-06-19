"""Tests for the tiny DOM + selector engine (dom.py).
Run: python -m unittest boostmatcher.test_dom
"""
from __future__ import annotations

import unittest

from . import dom

_HTML = """
<div class="card Boost_root__a1b2" id="c1" data-odds="2.5" data-state="live">
  <h3 class="title">Team A v Team B</h3>
  <span class="sel">Team A <em>to win</em></span>
  <span class="price" aria-label="4/1">4/1</span>
  <img src="x.png"/>
</div>
<div class="card Boost_root__c3d4">
  <span class="price" aria-label="evens">evens</span>
</div>
"""


class Selectors(unittest.TestCase):
    def setUp(self):
        self.root = dom.parse(_HTML)

    def test_exact_class(self):
        self.assertEqual(len(dom.find_all(self.root, ".card")), 2)

    def test_class_prefix(self):
        self.assertEqual(len(dom.find_all(self.root, ".Boost_root*")), 2)
        self.assertEqual(len(dom.find_all(self.root, ".Boost_root__a1b2")), 1)

    def test_tag_and_id_and_compound(self):
        self.assertEqual(len(dom.find_all(self.root, "h3.title")), 1)
        self.assertEqual(len(dom.find_all(self.root, "#c1")), 1)
        self.assertEqual(len(dom.find_all(self.root, "div.card#c1")), 1)

    def test_attribute_ops(self):
        self.assertEqual(len(dom.find_all(self.root, "[data-odds]")), 1)
        self.assertEqual(len(dom.find_all(self.root, "[data-odds=2.5]")), 1)
        self.assertEqual(len(dom.find_all(self.root, "[data-state^=li]")), 1)
        self.assertEqual(len(dom.find_all(self.root, "[data-state*=iv]")), 1)
        self.assertEqual(len(dom.find_all(self.root, "[data-odds=9.9]")), 0)

    def test_text_includes_descendants_collapsed(self):
        self.assertEqual(dom.first_value(self.root, ".sel"), "Team A to win")

    def test_attribute_extraction(self):
        self.assertEqual(dom.first_value(self.root, ".price::attr(aria-label)"), "4/1")

    def test_first_value_scoped_to_card(self):
        card = dom.find_all(self.root, ".card")[1]      # second card
        self.assertEqual(dom.first_value(card, ".price::attr(aria-label)"), "evens")

    def test_void_tag_does_not_break_tree(self):
        # The <img> is a void element; the first card must still close cleanly so
        # the second card is a sibling, not nested inside the first.
        self.assertEqual(len(dom.find_all(self.root, ".card")), 2)


if __name__ == "__main__":
    unittest.main()
