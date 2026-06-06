"""Entry point: one asyncio task per target, each polling on a jittered
interval with backoff. Detected drops fire SMS + email with the checkout link.

Run with:  python -m src.main
"""
from __future__ import annotations

import asyncio
import random
import signal
import sys

import structlog

from . import config as config_mod
from .config import DiscoveryTarget, Settings, Target
from .detector import diff
from .discovery import (
    extract_events,
    fetch_page_events_api,
    fetch_search_events_api,
)
from .fetchers import BrowserFetcher, HttpFetcher
from .notifiers import NotificationDispatcher
from .parsers import get_parser
from .state import StateStore

log = structlog.get_logger()


class Monitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = StateStore()
        self.dispatcher = NotificationDispatcher(settings)
        self.http = HttpFetcher(proxies=settings.proxies)
        self.browser = BrowserFetcher(proxies=settings.proxies)
        self._stop = asyncio.Event()

    def _fetcher(self, target):
        return self.browser if target.fetch.method == "browser" else self.http

    async def _poll_once(self, target: Target) -> None:
        raw = await self._fetcher(target).fetch(target.url)
        snapshot = get_parser(target.site).parse(target.name, raw)

        if not snapshot.tiers:
            log.warning("poll.empty", target=target.name,
                        hint="parser found no tiers; verify selectors")
            return

        previous = self.state.get(target.name)

        # First time we see this target: record a baseline silently. Otherwise
        # every currently-on-sale tier would look like a fresh "drop".
        if not previous:
            self.state.set(target.name, snapshot.as_map())
            log.info("baseline", target=target.name,
                     tiers=len(snapshot.tiers))
            return

        events = diff(previous, snapshot)

        # Persist the new state regardless, so we only alert on transitions.
        self.state.set(target.name, snapshot.as_map())

        if events:
            await self._fire_alert(target, events)
        else:
            log.debug("poll.nochange", target=target.name,
                      tiers=len(snapshot.tiers))

    async def _fire_alert(self, target: Target, events: list[str]) -> None:
        log.info("DROP", target=target.name, events=events)
        subject = f"🎟️ TICKET DROP: {target.name}"
        body = (
            "\n".join(f"• {e}" for e in events)
            + f"\n\nBuy now: {target.checkout_url}"
        )
        await self.dispatcher.alert(subject, body)

    # ---- event discovery (new events appearing on a listing page) ----
    async def _discover_once(self, d: DiscoveryTarget) -> None:
        if d.source == "api":
            events = await fetch_page_events_api(self.http, d.page_id, d.match)
        elif d.source == "search":
            events = await fetch_search_events_api(self.http, d.query, d.match)
        else:
            raw = await self._fetcher(d).fetch(d.url)
            events = extract_events(raw, d.match)

        key = f"discovery::{d.name}"
        current = {eid: e["title"] for eid, e in events.items()}

        # First successful poll: record a baseline (even if EMPTY) and don't
        # alert. Storing the empty set matters for one-off promoters like Fabric
        # that currently have no events -- the next event to appear is then a
        # genuine NEW one we alert on, rather than being silently absorbed.
        if not self.state.has(key):
            self.state.set_raw(key, current)
            log.info("discover.baseline", watcher=d.name, events=len(current))
            return

        seen = self.state.get_raw(key)
        new_ids = [eid for eid in events if eid not in seen]
        # Remember everything we've ever seen so an event dropping off the
        # listing and reappearing doesn't re-alert.
        merged = {**seen, **current}
        self.state.set_raw(key, merged)

        if new_ids:
            await self._fire_discovery_alert(d, [events[i] for i in new_ids])
        else:
            log.debug("discover.nochange", watcher=d.name, events=len(events))

    async def _fire_discovery_alert(self, d: DiscoveryTarget, new_events) -> None:
        titles = [e["title"] for e in new_events]
        log.info("NEW_EVENT", watcher=d.name, events=titles)
        subject = f"🆕 NEW EVENT: {d.name}"
        body = "\n\n".join(
            f"• {e['title']}\n{e['url']}" for e in new_events
        )
        await self.dispatcher.alert(subject, body)

    async def _loop(self, item, poll_coro) -> None:
        """Shared jittered poll loop with exponential backoff on errors."""
        backoff = 0
        while not self._stop.is_set():
            try:
                await poll_coro(item)
                backoff = 0
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                backoff = min(backoff + 1, 5)
                log.error("poll.error", item=item.name,
                          error=str(exc), backoff_step=backoff)

            # Jitter ±33% so polls don't form a detectable fixed cadence.
            base = item.interval * (2 ** backoff if backoff else 1)
            delay = base * random.uniform(0.67, 1.33)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _run_target(self, target: Target) -> None:
        log.info("target.start", target=target.name,
                 method=target.fetch.method, interval=target.interval)
        await self._loop(target, self._poll_once)

    async def _run_discovery(self, d: DiscoveryTarget) -> None:
        log.info("discovery.start", watcher=d.name,
                 method=d.fetch.method, interval=d.interval, match=d.match)
        await self._loop(d, self._discover_once)

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self._run_target(t))
            for t in self.settings.targets
        ]
        tasks += [
            asyncio.create_task(self._run_discovery(d))
            for d in self.settings.discovery
        ]
        await self._stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()
        await self.browser.aclose()

    def stop(self) -> None:
        self._stop.set()


async def _main() -> None:
    # Make log output unicode-safe regardless of the console/locale (event
    # titles can contain emoji; a C-locale stdout would otherwise crash).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best effort
            pass

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20)  # INFO
    )
    settings = config_mod.load()
    monitor = Monitor(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, monitor.stop)
        except NotImplementedError:
            # Windows: add_signal_handler is unsupported; Ctrl+C still raises.
            pass

    log.info("monitor.start", targets=len(settings.targets))
    try:
        await monitor.run()
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    asyncio.run(_main())
