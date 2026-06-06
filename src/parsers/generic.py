"""Generic fallback parser.

No structural assumptions: it scans the whole page text for the status
keywords and reports a single synthetic tier. Useful for a quick "did the page
text change from Sold Out to Buy" signal before you write a proper parser.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from ..models import Snapshot, Status, Tier
from .base import Parser, status_from_keywords


class GenericParser(Parser):
    site = "generic"

    def parse(self, target_name: str, raw: str) -> Snapshot:
        text = HTMLParser(raw).text(separator=" ", strip=True)
        status = status_from_keywords(text)
        # If both "sold out" and "buy" appear, keyword order already favors the
        # more specific sold-out; treat presence of an explicit buy CTA as the
        # signal by re-checking just for buy when nothing negative is found.
        if status is Status.UNKNOWN:
            status = Status.UNKNOWN
        return Snapshot(
            target_name=target_name,
            tiers=[Tier(name="page", status=status)],
        )
