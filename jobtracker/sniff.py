"""Sniff a firm's *real* job API by watching network traffic while its careers
page renders (Module 1, Phase 6).

Many "browser-tier" firms (the ones resolve.py couldn't reach from static HTML)
DO call a clean JSON job API once their SPA boots — Workday cxs, SmartRecruiters,
Greenhouse-embed, Ashby, etc. If we render the page in Chromium and inspect every
request URL, we can recover that endpoint and PROMOTE the firm from the heavy
browser tier to a fast, light HTTP feed (and point at the right place, not the
marketing blurb). Anything we still can't resolve stays on the browser tier.

Run:
  python -m jobtracker.sniff --names "KKR" "Carlyle Group" ...   # from config browser firms
  python -m jobtracker.sniff --all-browser                       # every ats=browser firm
"""
from __future__ import annotations

import argparse
import asyncio
import json

import httpx
import yaml

from . import resolve as R

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


async def sniff_firm(context, http: httpx.AsyncClient, name: str, url: str,
                     settle_ms: int = 9000) -> dict | None:
    page = await context.new_page()
    seen: list[str] = []
    page.on("request", lambda req: seen.append(req.url))
    page.on("response", lambda resp: seen.append(resp.url))
    try:
        await page.route("**/*", lambda r: asyncio.create_task(
            r.abort() if r.request.resource_type in {"image", "media", "font"} else r.continue_()))
    except Exception:
        pass
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=settle_ms)
        except Exception:
            await page.wait_for_timeout(settle_ms)
    except Exception:
        await page.close()
        return None
    await page.close()

    # Examine captured URLs for a known ATS endpoint, verify it returns jobs.
    tried = set()
    for u in seen:
        d = R.detect_url(u)
        if not d:
            continue
        sig = (d["ats"], d.get("token") or d.get("url"))
        if sig in tried:
            continue
        tried.add(sig)
        v = await R.verify(http, d)
        if v:
            v["firm"], v["landing"] = name, url
            return v
    return None


async def run(targets: list[tuple[str, str]], concurrency: int = 4):
    from playwright.async_api import async_playwright
    resolved, failed = [], []
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p, httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 1600})
        async def one(name, url):
            async with sem:
                try:
                    r = await sniff_firm(ctx, http, name, url)
                except Exception:
                    r = None
            (resolved if r else failed).append(r or (name, url))
        await asyncio.gather(*(one(n, u) for n, u in targets))
        await ctx.close(); await browser.close()
    return resolved, failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="jobtracker/config.yaml")
    ap.add_argument("--names", nargs="*", help="specific firm names to sniff")
    ap.add_argument("--all-browser", action="store_true", help="sniff every ats=browser firm")
    ap.add_argument("--out", default="jobtracker/sniffed.yaml")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    firms = cfg["firms"]
    want = set(args.names or [])
    targets = [(f["name"], f["url"]) for f in firms
               if (args.all_browser and f["ats"] == "browser") or f["name"] in want]
    if not targets:
        print("no matching firms"); return

    print(f"sniffing {len(targets)} firms ...")
    resolved, failed = asyncio.run(run(targets))
    block = R.emit_yaml(sorted(resolved, key=lambda d: d["firm"].lower()), interval=1800)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(block)
    print(f"  promoted to HTTP feed: {len(resolved)}")
    for d in resolved:
        print(f"    {d['firm']:30} -> {d['ats']}  ({d['jobs']} jobs)")
    print(f"  still browser-only: {len(failed)}  -> {args.out} has the promotions")


if __name__ == "__main__":
    main()
