"""Event discovery: scan a Fatsoma listing/promoter page for event links and
return the ones whose title matches all the given keywords.

Used to alert when a brand-new event (e.g. a future Ministry Tuesday) gets
listed -- distinct from watching ticket tiers on already-known events.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

BASE = "https://www.fatsoma.com"
# Fatsoma event paths look like /e/<id>/<slug>
_EVENT_RE = re.compile(r"^/e/([a-z0-9]+)/(.+)$")

# Fatsoma's public JSON:API. The promoter page loads its full event list from
# here -- far more complete than the server-rendered HTML, which only includes
# the first handful. `vanity-name` is the /e/<code> URL shortcode.
API_EVENTS = "https://api.fatsoma.com/v1/events"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _clean(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip()


def _matches(title: str, match_terms: list[str]) -> bool:
    low = title.lower()
    return all(term in low for term in match_terms)


def _title_key(title: str) -> str:
    """Stable identity for an event across rep-listings/casing/punctuation."""
    collapsed = re.sub(r"[^a-z0-9]+", " ", title.lower())
    return re.sub(r"\s+", " ", collapsed).strip()


async def fetch_page_events_api(
    fetcher, page_id: str, match_terms: list[str]
) -> dict[str, dict[str, str]]:
    """Return {vanity_code: {"title", "url"}} for a promoter page's upcoming
    events whose title contains all of `match_terms` (case-insensitive).

    `fetcher` is an HttpFetcher (used for its get_json + cookie/proxy reuse).
    """
    params = {
        "filter[ends-at][gte]": _now(),   # only events that haven't ended
        "filter[page.id]": page_id,
        "filter[status]": "active",
        "page[size]": "100",
    }
    payload = await fetcher.get_json(API_EVENTS, params=params)

    found: dict[str, dict[str, str]] = {}
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        code = attrs.get("vanity-name")
        title = _clean(attrs.get("name"))
        if not code or not title or not _matches(title, match_terms):
            continue
        found[code] = {"title": title, "url": f"{BASE}/e/{code}"}

    return found


async def fetch_search_events_api(
    fetcher, query: str, match_terms: list[str]
) -> dict[str, dict[str, str]]:
    """Keyword-search upcoming events (e.g. all events at a venue named in the
    title). Used when a venue's events come from many different promoters --
    there's no single page to watch, so we search the title instead.

    Keyed by a normalized title so the same event posted by multiple reps (and
    minor title/casing tweaks) collapses to one entry.
    """
    params = {
        "filter[query]": query,
        "filter[status]": "active",
        "filter[ends-at][gte]": _now(),
        "page[size]": "100",
    }
    payload = await fetcher.get_json(API_EVENTS, params=params)

    found: dict[str, dict[str, str]] = {}
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        code = attrs.get("vanity-name")
        title = _clean(attrs.get("name"))
        if not code or not title or not _matches(title, match_terms):
            continue
        found.setdefault(
            _title_key(title), {"title": title, "url": f"{BASE}/e/{code}"}
        )

    return found


def extract_events(html: str, match_terms: list[str]) -> dict[str, dict[str, str]]:
    """Return {event_id: {"title": ..., "url": ...}} for matching events.

    `match_terms` are lower-cased substrings that must ALL appear in the title.
    An empty list matches every event on the page.
    """
    tree = HTMLParser(html)
    found: dict[str, dict[str, str]] = {}

    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        m = _EVENT_RE.match(href)
        if not m:
            continue

        event_id = m.group(1)
        title = re.sub(r"\s+", " ", a.text(separator=" ", strip=True)).strip()
        if not title:
            continue

        low = title.lower()
        if match_terms and not all(term in low for term in match_terms):
            continue

        # First occurrence wins (cards sometimes repeat the link).
        found.setdefault(
            event_id, {"title": title, "url": f"{BASE}{href}"}
        )

    return found
