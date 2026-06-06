"""Milkshake parser.

Milkshake event pages are usually lighter than Fatsoma — the ticket widget is
often present in the served HTML, so the plain HTTP fetcher tends to work.

# =====================================================================
# TODO: VERIFY AGAINST LIVE PAGE
#   Inspect the ticket section and set the selectors below. If the tiers are
#   injected by an embedded widget (e.g. an iframe to a ticketing provider),
#   point the target `url` at the widget/provider endpoint instead.
# =====================================================================
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from ..models import Snapshot, Tier
from .base import Parser, status_from_keywords

# --- placeholders to verify ---
TIER_SELECTOR = ".ticket, .ticket-row, [data-ticket]"
TIER_NAME_SELECTOR = ".ticket-title, .name, h4"
TIER_BUTTON_SELECTOR = "button, .status, .cta"
TIER_PRICE_SELECTOR = ".price"
# ------------------------------


class MilkshakeParser(Parser):
    site = "milkshake"

    def parse(self, target_name: str, raw: str) -> Snapshot:
        tree = HTMLParser(raw)
        tiers: list[Tier] = []
        for row in tree.css(TIER_SELECTOR):
            name_node = row.css_first(TIER_NAME_SELECTOR)
            btn_node = row.css_first(TIER_BUTTON_SELECTOR)
            price_node = row.css_first(TIER_PRICE_SELECTOR)
            name = name_node.text(strip=True) if name_node else "ticket"
            label = btn_node.text(strip=True) if btn_node else ""
            tiers.append(
                Tier(
                    name=name,
                    status=status_from_keywords(label),
                    price=price_node.text(strip=True) if price_node else None,
                )
            )
        return Snapshot(target_name=target_name, tiers=tiers)
