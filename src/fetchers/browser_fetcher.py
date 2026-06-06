"""Fallback path: render the page with Playwright + stealth.

Use only when a target hard-blocks plain HTTP (JS challenge that issues the
real content only after execution). Heavier and more fingerprintable than the
HTTP fetcher, so keep it for the few targets that need it.

One browser is launched lazily and reused across polls; each fetch runs in a
fresh context so cookies/fingerprint don't bleed between targets.
"""
from __future__ import annotations

import random

# playwright is imported lazily inside _ensure() so the package (and the
# HTTP-only deployment) works without it installed.

_VIEWPORTS = [(1920, 1080), (1536, 864), (1440, 900)]


class BrowserFetcher:
    def __init__(self, proxies: list[str] | None = None):
        self._proxies = proxies or []
        self._pw = None
        self._browser = None

    async def _ensure(self):
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )

    async def fetch(self, url: str) -> str:
        await self._ensure()
        width, height = random.choice(_VIEWPORTS)
        proxy = (
            {"server": random.choice(self._proxies)} if self._proxies else None
        )
        context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            locale="en-GB",
            proxy=proxy,
        )
        page = await context.new_page()
        try:
            try:
                from playwright_stealth import stealth_async

                await stealth_async(page)
            except ImportError:
                pass
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            return await page.content()
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
