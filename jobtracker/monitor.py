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
import random

import httpx
import structlog

from . import db, notify
from .config import Config, FirmTarget, load
from .diff import content_fingerprint, diff
from .parsers import PARSERS

log = structlog.get_logger()

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


async def _fetch(client: httpx.AsyncClient, firm: FirmTarget) -> str:
    if firm.method.upper() == "POST":
        resp = await client.post(firm.url, json=firm.body or {}, headers=_HEADERS)
    else:
        resp = await client.get(firm.url, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


async def poll_once(conn, cfg: Config, firm: FirmTarget, client: httpx.AsyncClient) -> list[str]:
    """Run a single firm tick. Returns the events it raised (also pushed)."""
    firm_id = db.get_or_create_firm(
        conn, firm.name, firm.slug, ats=firm.ats, max_apps=firm.max_apps, careers_url=firm.url
    )
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

    parser = PARSERS[firm.ats]
    snapshot = parser(firm.name, raw, host=firm.host) if firm.ats == "workday" \
        else parser(firm.name, raw, base_url=firm.host)

    previous = db.load_previous(conn, firm_id)
    events = diff(previous, snapshot, cfg.relevance)

    for event in events:
        await notify.alert(cfg.ntfy_topic, f"Drop: {firm.name}", event)
        log.info("drop", firm=firm.name, detail=event)

    db.save_snapshot(conn, firm_id, snapshot, content_hash=fingerprint)
    return events


async def run(config_path: str) -> None:
    """Forever-loop entrypoint. One asyncio task per firm, each self-pacing."""
    cfg = load(config_path)
    conn = db.connect(cfg.db_path)
    db.init_db(conn)

    async with httpx.AsyncClient(http2=True, timeout=20, follow_redirects=True) as client:
        async def watch(firm: FirmTarget):
            while True:
                await poll_once(conn, cfg, firm, client)
                jitter = firm.interval * random.uniform(0.67, 1.33)
                await asyncio.sleep(jitter)

        log.info("monitor.start", firms=[f.name for f in cfg.firms])
        await asyncio.gather(*(watch(f) for f in cfg.firms))
