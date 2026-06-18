"""Free, unlimited odds via scraping oddschecker's multi-book odds grid — the
fallback for when The Odds API's free monthly credits run out.

Reuses boostmatcher's proven kit (sibling package in this repo): the stdlib
CSS-ish selector engine (`boostmatcher.dom`), the fractional/decimal odds parser
(`to_decimal`), and the headless-Chromium renderer (oddschecker is JS-rendered +
bot-gated). One oddschecker "winner" page = one fixture's 1X2 grid across ~8
books, which is exactly the consensus input Detector A needs.

STATUS (mirrors boostmatcher's scrapers): the PARSING LOGIC is unit-tested
against a synthetic grid, but the live `SPECS["oddschecker"]` selector strings
are PLACEHOLDERS — oddschecker's real class/attribute names change and must be
confirmed once against a saved page with `gembets scrape-test --file page.html`.
Scraping is fragile and against the site's ToS; it's the fallback, not the default
source of truth. The clean path is the free API tier; this keeps you running when
credits are gone.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from .models import BookLine, MarketSnapshot

log = logging.getLogger(__name__)

# boostmatcher (sibling package) is only needed when the scrape FALLBACK actually
# runs, so it's imported lazily — gembets deploys standalone without it.


@dataclass(frozen=True)
class GridSpec:
    """Selector strings (dom.py grammar) locating each book's row in an odds grid.

    `cell` should resolve to the per-outcome odds IN ORDER (Home, Draw, Away);
    odds usually live in an attribute, hence the `::attr(...)` extractor.
    """

    row: str                # selector for each bookmaker row
    bookie: str             # bookie name/code within the row (text or ::attr)
    cell: str               # per-outcome odds cells, in outcome order


def _values(node: dom.Node, selectors: str) -> list[str]:
    """Ordered extracted values of every node under `node` matching `selectors`.

    Honours COMMA-separated alternatives (like boostmatcher's `_first`): the first
    alternative that yields any values wins, so cell ordering stays consistent and
    a page using `data-o` vs `data-odds` is covered by one spec.
    """
    from boostmatcher import dom
    for spec in (s.strip() for s in selectors.split(",") if s.strip()):
        sel = dom.Selector.parse(spec)
        out = []
        if sel.matches(node) and (v := sel.value(node)):
            out.append(v)
        for n in node.walk():
            if sel.matches(n) and (v := sel.value(n)):
                out.append(v)
        if out:
            return out
    return []


def fixture_from_url(url: str) -> str:
    """Derive a fixture name from an oddschecker match-page slug.

    .../premier-league/brighton-v-aston-villa/winner -> "Brighton vs Aston Villa".
    """
    m = re.search(r"/([a-z0-9-]+)-v-([a-z0-9-]+)(?:/|$)", url.lower())
    if not m:
        return url
    title = lambda s: " ".join(w.capitalize() for w in s.split("-"))
    return f"{title(m.group(1))} vs {title(m.group(2))}"


def parse_grid(html: str, fixture: str, labels: tuple[str, ...], spec: GridSpec,
               *, market: str = "1X2", kickoff: str | None = None,
               min_books: int = 2) -> MarketSnapshot | None:
    """Parse one match's odds grid into a MarketSnapshot (None if too thin)."""
    from boostmatcher import dom
    from boostmatcher.scrapers import to_decimal
    root = dom.parse(html)
    lines: list[BookLine] = []
    seen: set[str] = set()
    for row in dom.find_all(root, spec.row):
        bk = dom.first_value(row, spec.bookie)
        raw = _values(row, spec.cell)
        if not bk or len(raw) < len(labels):
            continue
        decimals = [to_decimal(x) for x in raw[:len(labels)]]
        if any(d is None or d <= 1.0 for d in decimals):
            continue
        book = bk.strip().lower()
        if book in seen:
            continue
        seen.add(book)
        lines.append(BookLine(book=book, decimals=tuple(decimals)))
    if len(lines) < min_books:
        return None
    return MarketSnapshot(fixture=fixture, market=market, labels=labels,
                          lines=tuple(lines), kickoff=kickoff)


# Live oddschecker selectors — PLACEHOLDERS. oddschecker renders each book as a
# row carrying a `data-bk` code, with per-outcome odds in a `data-o`/`data-odds`
# attribute. Confirm the real names on a saved page via `gembets scrape-test`.
SPECS: dict[str, GridSpec] = {
    "oddschecker": GridSpec(
        row="[data-bk]",
        bookie="[data-bk]::attr(data-bk)",
        cell="[data-odds]::attr(data-odds), [data-o]::attr(data-o)"),
}


def parse_oddschecker(html: str, *, fixture: str, url: str = "") -> MarketSnapshot | None:
    return parse_grid(html, fixture, ("Home", "Draw", "Away"), SPECS["oddschecker"])


SCRAPERS: dict[str, Callable[..., "MarketSnapshot | None"]] = {
    "oddschecker": parse_oddschecker,
}


async def _render(url: str) -> str:
    """Render a JS/bot-gated page in headless Chromium (reuses boostmatcher)."""
    from boostmatcher.monitor import _render_html
    return await _render_html(url)


async def fetch_scrape(scraper: str, urls: list[str]) -> list[MarketSnapshot]:
    """Scrape each configured match page into a snapshot. Best-effort per URL."""
    parse = SCRAPERS.get(scraper)
    if not parse or not urls:
        if not urls:
            log.info("scrape: no scrape_urls configured - fallback yields nothing")
        return []
    snaps: list[MarketSnapshot] = []
    for url in urls:
        try:
            html = await _render(url)
            snap = parse(html, fixture=fixture_from_url(url), url=url)
            if snap:
                snaps.append(snap)
            else:
                log.warning("scrape: parsed no usable grid from %s "
                            "(selectors need calibration?)", url)
        except Exception as exc:  # noqa: BLE001 — one dead page mustn't stop the rest
            log.warning("scrape failed for %s: %s", url, exc)
    return snaps
