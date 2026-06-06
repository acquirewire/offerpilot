"""Fatsoma parser.

Verified against live pages (June 2026). Fatsoma server-renders the ticket
widget into the HTML, so the fast HTTP fetcher is enough -- no browser needed.

Each ticket tier is a table row:

    <tr class="_row_xxxx" disabled>            <- `disabled` = not buyable
      <td class="_name_xxxx">Early Bird Tickets <a class="_toggle_xxxx">More</a></td>
      <td>
        <span>Sold Out</span>                  <- status text (or absent)
        <span class="_price_xxxx">£4.00 +</span>
      </td>
      <td> ...qty selector... </td>
    </tr>

Status logic:
  * status text contains "sold out"     -> SOLD_OUT
  * status text contains "coming soon"  -> COMING_SOON
  * row has the `disabled` attribute    -> SOLD_OUT (not yet buyable)
  * otherwise (price shown, not disabled) -> AVAILABLE  <- the thing we alert on

Class names carry a build hash suffix (e.g. `_row_1ci0w8`) that can change when
Fatsoma redeploys, so we match on the stable prefix via [class*="_row_"].
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..models import Snapshot, Status, Tier
from .base import Parser

ROW_SELECTOR = 'tr[class*="_row_"]'
NAME_SELECTOR = 'td[class*="_name_"]'
PRICE_SELECTOR = '[class*="_price_"]'


class FatsomaParser(Parser):
    site = "fatsoma"

    def parse(self, target_name: str, raw: str) -> Snapshot:
        tree = HTMLParser(raw)
        tiers: list[Tier] = []
        seen: set[str] = set()

        for row in tree.css(ROW_SELECTOR):
            name_td = row.css_first(NAME_SELECTOR)
            if name_td is None:
                continue

            # Drop the "More" expand toggle (and any nested markup) so the
            # name is just the tier label.
            for junk in name_td.css('a, button'):
                junk.decompose()
            name = re.sub(r"\s+", " ", name_td.text(separator=" ", strip=True)).strip()
            if not name:
                continue

            tds = row.css("td")
            status_text = (
                tds[1].text(separator=" ", strip=True).lower()
                if len(tds) > 1
                else ""
            )
            disabled = "disabled" in row.attributes

            price_node = row.css_first(PRICE_SELECTOR)
            price = price_node.text(strip=True) if price_node else None

            status = self._status(status_text, disabled)

            # Some events reuse a tier name at different prices; disambiguate so
            # they don't collapse into one entry in the state map.
            key = name
            if key in seen and price:
                key = f"{name} ({price})"
            seen.add(key)

            tiers.append(Tier(name=key, status=status, price=price))

        return Snapshot(target_name=target_name, tiers=tiers)

    @staticmethod
    def _status(status_text: str, disabled: bool) -> Status:
        if "sold out" in status_text:
            return Status.SOLD_OUT
        if "coming soon" in status_text or "on sale soon" in status_text:
            return Status.COMING_SOON
        if "off sale" in status_text or "unavailable" in status_text:
            return Status.SOLD_OUT
        if disabled:
            # disabled with no explicit reason -> treat as not buyable
            return Status.SOLD_OUT
        return Status.AVAILABLE
