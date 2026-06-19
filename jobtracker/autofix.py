"""Auto-fix browser-tier firms pointed at a brochure page (Module 1, Phase 7).

healthcheck.py flags firms whose configured URL is a marketing blurb, not a job
listing. This tries to repair them automatically, HTTP-only (fast, no browser):

  for each firm:
    1. fetch the brochure; check the page URL + every href/src for a known ATS
       feed (Greenhouse/Lever/Ashby/Workday/SmartRecruiters/Recruitee/Pinpoint/
       Workable) and verify it returns the job shape -> PROMOTE to HTTP feed.
    2. else follow same-domain links that look like "search jobs / vacancies /
       opportunities / open roles" (one hop) and re-check those for an ATS feed.
    3. else token-guess Greenhouse (name-verified, accepts a currently-empty
       board) -> PROMOTE.
    4. else, if a plausible job-search sub-page was found, REPOINT the browser
       firm at it (+search_term) so the renderer at least watches the listings.
    5. else leave it for the render-sniff / manual pass.

Outputs an updated config in place (backup kept) and autofix_report.csv.

Run:  python -m jobtracker.autofix --only-suspects   # from health_hf.csv
      python -m jobtracker.autofix --all-browser
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os

from selectolax.parser import HTMLParser

from . import resolve as R

try:
    from curl_cffi.requests import AsyncSession
    def _client():
        return AsyncSession(impersonate="chrome", timeout=20)
except ImportError:
    import httpx
    def _client():
        return httpx.AsyncClient(timeout=20, follow_redirects=True)

_SEARCH_HINTS = ("search", "job", "vacanc", "opportunit", "roles", "opening",
                 "position", "explore", "current-openings", "find-a-job", "apply")


def _same_site(a: str, b: str) -> bool:
    from urllib.parse import urlparse
    return urlparse(a).netloc.split(":")[0].lstrip("www.") == urlparse(b).netloc.split(":")[0].lstrip("www.")


def _candidate_links(html: str, base: str) -> list[str]:
    from urllib.parse import urljoin
    tree = HTMLParser(html)
    out, seen = [], set()
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(base, href)
        text = (a.text() or "").lower()
        blob = (href + " " + text).lower()
        if any(h in blob for h in _SEARCH_HINTS) and _same_site(full, base) and full not in seen:
            seen.add(full)
            out.append(full)
    return out[:5]


async def _ats_from_text(client, text_or_url: str) -> dict | None:
    d = R.detect_url(text_or_url)
    if d:
        v = await R.verify(client, d)
        if v:
            return v
    return None


async def _scan_html_for_feed(client, html: str) -> dict | None:
    tree = HTMLParser(html)
    urls = set()
    for node in tree.css("a, link, script, iframe"):
        for attr in ("href", "src"):
            u = node.attributes.get(attr)
            if u:
                urls.add(u)
    for u in list(urls)[:200]:
        v = await _ats_from_text(client, u)
        if v:
            return v
    return None


async def fix_firm(client, name: str, url: str) -> dict:
    res = {"firm": name, "url": url, "action": "manual", "ats": "", "feed": "", "jobs": ""}
    # 1. the brochure URL itself + its HTML
    try:
        r = await client.get(url, headers={"User-Agent": R.UA})
        html, final = r.text, str(getattr(r, "url", url))
    except Exception:
        html, final = "", url
    v = await _ats_from_text(client, final) or (await _scan_html_for_feed(client, html) if html else None)
    # 2. follow search sub-pages
    subpage = None
    if not v and html:
        for link in _candidate_links(html, final):
            subpage = subpage or link
            sv = await _ats_from_text(client, link)
            if sv:
                v = sv; break
            try:
                rr = await client.get(link, headers={"User-Agent": R.UA})
                sv = await _ats_from_text(client, str(getattr(rr, "url", link))) or await _scan_html_for_feed(client, rr.text)
                if sv:
                    v = sv; break
            except Exception:
                pass
    # 3. greenhouse token-guess (name-verified, empty ok)
    if not v:
        for tok in R.guess_tokens(name):
            d = await R._gh_named(client, name, tok)
            if d:
                v = await R.verify(client, d) or {"ats": "greenhouse", "token": tok,
                                                  "feed": f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs?content=true",
                                                  "method": "GET", "jobs": 0}
                break
    if v:
        res.update(action="promote", ats=v["ats"], feed=v["feed"],
                   jobs=v.get("jobs", ""), method=v.get("method", "GET"),
                   host=v.get("host", ""), body=v.get("body"))
    elif subpage:
        res.update(action="repoint", feed=subpage)
    return res


async def run(targets, concurrency=10):
    sem = asyncio.Semaphore(concurrency)
    rows = []
    async with _client() as client:
        async def one(n, u):
            async with sem:
                try:
                    rows.append(await asyncio.wait_for(fix_firm(client, n, u), timeout=60))
                except Exception:
                    rows.append({"firm": n, "url": u, "action": "manual", "ats": "", "feed": "", "jobs": ""})
        await asyncio.gather(*(one(n, u) for n, u in targets))
    return rows


def main(argv=None):
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="jobtracker/config.yaml")
    ap.add_argument("--only-suspects", action="store_true", help="only firms flagged in health_hf.csv")
    ap.add_argument("--all-browser", action="store_true")
    ap.add_argument("--health", default="jobtracker/health_hf.csv")
    ap.add_argument("--report", default="jobtracker/autofix_report.csv")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    bad = set()
    if args.only_suspects and os.path.exists(args.health):
        for r in csv.DictReader(open(args.health, encoding="utf-8")):
            if r["status"] != "ok":
                bad.add(r["firm"])
    targets = [(f["name"], f["url"]) for f in cfg["firms"] if f["ats"] == "browser"
               and (args.all_browser or not bad or f["name"] in bad)]
    print(f"autofixing {len(targets)} firms ...", flush=True)
    rows = asyncio.run(run(targets))

    promo = {r["firm"]: r for r in rows if r["action"] == "promote"}
    repoint = {r["firm"]: r for r in rows if r["action"] == "repoint"}
    WD = {"appliedFacets": {}, "limit": 100, "offset": 0, "searchText": ""}
    for f in cfg["firms"]:
        n = f["name"]
        if n in promo:
            p = promo[n]
            for k in ("method", "body", "host", "search_term", "scope_selector"):
                f.pop(k, None)
            f["ats"] = p["ats"]; f["url"] = p["feed"]; f["interval"] = 1800
            if p.get("method") == "POST":
                f["method"] = "POST"; f["body"] = p.get("body") or WD
            if p.get("host"):
                f["host"] = p["host"]
        elif n in repoint:
            f["url"] = repoint[n]["feed"]
            f.setdefault("search_term", "intern")

    import shutil
    shutil.copy(args.config, args.config.replace(".yaml", ".beforeautofix.bak.yaml"))
    yaml.safe_dump(cfg, open(args.config, "w", encoding="utf-8"),
                   sort_keys=False, allow_unicode=True, default_flow_style=False, width=200)
    with open(args.report, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["firm", "action", "ats", "jobs", "feed", "url"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in ["firm", "action", "ats", "jobs", "feed", "url"]})
    from collections import Counter
    print("result:", dict(Counter(r["action"] for r in rows)))
    print(f"  promoted to HTTP feed: {len(promo)} | repointed at search page: {len(repoint)}")
    print(f"  report -> {args.report}")


if __name__ == "__main__":
    main()
