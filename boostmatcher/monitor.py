"""The boostmatcher poll loop: scrape boosts -> match+quote on exchanges ->
rate -> alert the ones that clear the threshold -> refresh the HTML dashboard.

Mirrors jobtracker.monitor. The core `tick()` takes its fetcher and exchange
clients as arguments, so it runs against fakes in a test with no network (see
test_monitor) and against Playwright + live APIs in production.

Dedup: a boost is alerted when it first clears `alert_rating`, and re-alerted
only if its rating climbs materially (so a drifting price doesn't spam you).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from . import dashboard, notify
from .config import Config, load
from .instructions import plan
from .models import Boost, ExchangeQuote, RatedBoost
from .rating import best_of
from .scrapers import SCRAPERS

log = logging.getLogger(__name__)

Fetcher = Callable[[str], Awaitable[str]]
_REALERT_DELTA = 0.5        # only re-alert if rating improves by this many points


class _Client(Protocol):
    name: str
    async def quote(self, event: str, market: str, selection: str) -> ExchangeQuote | None: ...


async def collect_boosts(cfg: Config, fetch: Fetcher) -> list[Boost]:
    """Render every enabled bookie page and parse it into Boosts."""
    boosts: list[Boost] = []
    for bk in cfg.bookies:
        if not bk.enabled or bk.scraper not in SCRAPERS:
            continue
        try:
            html = await fetch(bk.url)
            found = SCRAPERS[bk.scraper](html, url=bk.url)
            log.info("scraped %s: %d boosts", bk.name, len(found))
            boosts.extend(found)
        except Exception as exc:  # noqa: BLE001 — one dead page mustn't stop the rest
            log.warning("scrape failed for %s: %s", bk.name, exc)
    return boosts


async def quote_all(clients: list[_Client], b: Boost) -> list[ExchangeQuote]:
    """Fan a boost out to every exchange; keep the quotes that matched."""
    results = await asyncio.gather(
        *(c.quote(b.event, b.market, b.selection) for c in clients), return_exceptions=True)
    return [q for q in results if isinstance(q, ExchangeQuote)]


def _alert_body(r: RatedBoost) -> str:
    p = plan(r)
    head = (f"{r.boost.bookie} {r.boost.event}: {r.boost.selection} @ {r.boost.boosted_odds:.2f}\n"
            f"Rating +{r.rating:.2f}%  ({'LOCK' if r.lockable else 'value'})")
    return head + ("\n" + p.as_text() if p else "")


async def tick(cfg: Config, clients: list[_Client], fetch: Fetcher,
               seen: dict[str, float], *, html_path: str | None = None) -> list[RatedBoost]:
    """One full pass. Returns every rated boost; alerts the qualifying new ones."""
    boosts = await collect_boosts(cfg, fetch)
    rated = [best_of(b, await quote_all(clients, b), cfg.back_stake) for b in boosts]

    for r in sorted(rated, key=lambda x: x.rating, reverse=True):
        if not (r.quote and r.rating >= cfg.alert_rating):
            continue
        key = r.boost.key()
        if key not in seen or r.rating > seen[key] + _REALERT_DELTA:
            await notify.alert(cfg.ntfy_topic, f"Boost +{r.rating:.1f}% {r.boost.bookie}",
                               _alert_body(r))
            log.info("alert %s rating=%.2f", key, r.rating)
            seen[key] = r.rating

    if html_path:
        dashboard.write(rated, html_path, stake=cfg.back_stake, alert_rating=cfg.alert_rating)
    return rated


async def _render_html(url: str) -> str:
    """Live fetcher: render a JS-heavy bookie page in headless Chromium.

    Falls back to a plain httpx GET if Playwright isn't installed (fine for
    static/test pages; most bookie boost pages need the browser path).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        import httpx
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            return (await c.get(url)).text
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await (await browser.new_context()).new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        html = await page.content()
        await browser.close()
        return html


def _build_clients(cfg: Config) -> list[_Client]:
    clients: list[_Client] = []
    for ex in cfg.exchanges:
        if not ex.enabled:
            continue
        if ex.name == "smarkets":
            from .exchanges.smarkets import Smarkets
            clients.append(Smarkets(commission=ex.commission))
        elif ex.name == "betfair":
            from .exchanges.betfair import Betfair
            clients.append(Betfair(commission=ex.commission))
    return clients


async def run(config_path: str, *, html_path: str | None = "boostmatcher_dashboard.html") -> None:
    """Forever loop: tick every cfg.poll_interval seconds."""
    cfg = load(config_path)
    clients = _build_clients(cfg)
    seen: dict[str, float] = {}
    log.info("monitor start: %d bookies, %d exchanges", len(cfg.bookies), len(clients))
    while True:
        try:
            await tick(cfg, clients, _render_html, seen, html_path=html_path)
        except Exception as exc:  # noqa: BLE001 — never let a tick kill the loop
            log.error("tick failed: %s", exc)
        await asyncio.sleep(cfg.poll_interval)
