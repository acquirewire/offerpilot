"""Fast path: poll the page/endpoint over HTTP/2 with httpx.

Anti-bot basics baked in:
  * realistic, rotating User-Agent + matching client hints
  * a persistent cookie jar per host (so challenge cookies stick)
  * optional round-robin proxy rotation
  * retry with backoff on transient failures / 429s
"""
from __future__ import annotations

import itertools
import random

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# A small pool of current, real desktop UAs. Rotate per request.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/json,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


class HttpFetcher:
    """One long-lived client per process; cookies persist across polls."""

    def __init__(self, proxies: list[str] | None = None):
        self._proxy_cycle = itertools.cycle(proxies) if proxies else None
        # Cookie jar is shared across requests on this client.
        self._clients: dict[str | None, httpx.AsyncClient] = {}

    def _client(self) -> httpx.AsyncClient:
        proxy = next(self._proxy_cycle) if self._proxy_cycle else None
        if proxy not in self._clients:
            self._clients[proxy] = httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=httpx.Timeout(15.0),
                proxy=proxy,
            )
        return self._clients[proxy]

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def fetch(self, url: str) -> str:
        client = self._client()
        resp = await client.get(url, headers=_headers())
        if resp.status_code == 429:
            raise httpx.TransportError("rate limited (429)")
        resp.raise_for_status()
        return resp.text

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def get_json(
        self,
        url: str,
        params: dict | None = None,
        accept: str = "application/vnd.api+json",
    ) -> dict:
        client = self._client()
        headers = _headers()
        headers["Accept"] = accept
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 429:
            raise httpx.TransportError("rate limited (429)")
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()
