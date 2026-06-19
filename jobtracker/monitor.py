"""The Drop Tracker poll loop (Module 1): fetch -> gate -> diff -> alert -> save.

Per firm, each tick:
  1. fetch the ATS JSON endpoint (httpx; Workday=POST, Greenhouse=GET)
  2. LAYER-1 GATE: compute content_fingerprint; if unchanged since last save,
     skip parsing/alerting entirely (cheap no-op on a quiet page)
  3. parse -> CareerPageSnapshot
  4. diff against the DB's previous state, filtered for relevance
  5. push any alert-worthy events, then persist the new snapshot

Jitter is added to each firm's interval so polling isn't a metronome.
"""
from __future__ import annotations

import asyncio
import hashlib
import random

import structlog

from . import db, notify
from .config import Config, FirmTarget, load
from .diff import content_fingerprint, diff
from .parsers import PARSERS

log = structlog.get_logger()

# Many ATS APIs (SmartRecruiters, Lever, Ashby, Workable, Recruitee, Pinpoint)
# sit behind Cloudflare, which blocks plain httpx/requests by TLS fingerprint.
# curl_cffi impersonates a real Chrome handshake and gets through; we fall back
# to httpx only if curl_cffi isn't installed (Greenhouse/Workday don't need it).
try:
    from curl_cffi.requests import AsyncSession  # type: ignore
    _HAVE_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import httpx
    _HAVE_CURL_CFFI = False

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def _new_client():
    if _HAVE_CURL_CFFI:
        return AsyncSession(impersonate="chrome", timeout=25)
    return httpx.AsyncClient(http2=True, timeout=20, follow_redirects=True)


async def _fetch(client, firm: FirmTarget) -> str:
    if firm.method.upper() == "POST":
        resp = await client.post(firm.url, json=firm.body or {}, headers=_HEADERS)
    else:
        resp = await client.get(firm.url, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


# Headless Chromium is heavy; cap how many render at once across all firms.
_BROWSER_SEM = asyncio.Semaphore(3)


def _snapshot_fingerprint(snapshot) -> str:
    """Layer-1 gate for browser firms: hash the sorted set of posting identities."""
    blob = "\n".join(sorted(f"{p.key()}|{p.title}" for p in snapshot.postings))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def poll_once(conn, cfg: Config, firm: FirmTarget, client, *,
                    browser_ctx=None, alert: bool = True) -> list[str]:
    """Run a single firm tick. Returns the events it raised.

    `alert=False` (priming) computes and saves the baseline snapshot without
    pushing, so the first real run doesn't fire on every already-open role.
    `ats: browser` firms render in headless Chromium instead of an HTTP fetch.
    """
    firm_id = db.get_or_create_firm(
        conn, firm.name, firm.slug, ats=firm.ats, max_apps=firm.max_apps, careers_url=firm.url
    )

    if firm.ats == "browser":
        if browser_ctx is None:
            log.error("browser.unavailable", firm=firm.name)
            return []
        from . import browser as _browser
        try:
            async with _BROWSER_SEM:
                snapshot = await _browser.snapshot(browser_ctx, firm)
        except Exception as exc:  # noqa: BLE001
            log.warning("render.failed", firm=firm.name, error=str(exc))
            return []
        fingerprint = _snapshot_fingerprint(snapshot)
    else:
        try:
            raw = await _fetch(client, firm)
        except Exception as exc:  # noqa: BLE001
            log.error("fetch.failed", firm=firm.name, error=str(exc))
            return []
        fingerprint = content_fingerprint(raw, firm.scope_selector)

    last = conn.execute(
        "SELECT content_hash FROM posting WHERE firm_id = ? ORDER BY last_seen DESC LIMIT 1",
        (firm_id,),
    ).fetchone()
    if last and last["content_hash"] == fingerprint:
        log.debug("gate.unchanged", firm=firm.name)
        return []  # Layer-1 gate: nothing meaningful moved

    if firm.ats != "browser":
        parser = PARSERS[firm.ats]
        try:
            snapshot = parser(firm.name, raw, host=firm.host) if firm.ats == "workday" \
                else parser(firm.name, raw, base_url=firm.host)
        except Exception as exc:  # noqa: BLE001 — a CDN challenge/HTML page instead of JSON
            log.warning("parse.failed", firm=firm.name, error=str(exc))
            return []

    previous = db.load_previous(conn, firm_id)
    events = diff(previous, snapshot, cfg.relevance)

    if alert:
        for event in events:
            await notify.alert(cfg.ntfy_topic, f"Drop: {firm.name}", event)
            log.info("drop", firm=firm.name, detail=event)

    db.save_snapshot(conn, firm_id, snapshot, content_hash=fingerprint)
    return events


async def run(config_path: str, *, prime: bool = False) -> None:
    """Forever-loop entrypoint. One asyncio task per firm, each self-pacing.

    `prime=True` does a single silent baseline pass and exits — run it once
    before the first live run so you aren't paged for every already-open role.
    """
    cfg = load(config_path)
    conn = db.connect(cfg.db_path)
    db.init_db(conn)

    needs_browser = any(f.ats == "browser" for f in cfg.firms)
    pw = browser = bctx = None
    if needs_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        bctx = await browser.new_context(
            user_agent=_HEADERS["User-Agent"], viewport={"width": 1280, "height": 1800}
        )

    async with _new_client() as client:
        try:
            if prime:
                log.info("monitor.prime", firms=len(cfg.firms))
                sem = asyncio.Semaphore(8)
                async def prime_one(firm: FirmTarget):
                    async with sem:
                        await poll_once(conn, cfg, firm, client, browser_ctx=bctx, alert=False)
                await asyncio.gather(*(prime_one(f) for f in cfg.firms))
                log.info("monitor.prime.done")
                return

            async def watch(firm: FirmTarget):
                while True:
                    await poll_once(conn, cfg, firm, client, browser_ctx=bctx)
                    jitter = firm.interval * random.uniform(0.67, 1.33)
                    await asyncio.sleep(jitter)

            log.info("monitor.start", firms=[f.name for f in cfg.firms])
            await asyncio.gather(*(watch(f) for f in cfg.firms))
        finally:
            if bctx:
                await bctx.close()
            if browser:
                await browser.close()
            if pw:
                await pw.stop()
