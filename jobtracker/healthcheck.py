"""Health-check every configured firm: is its watch target actually a job LISTING,
or a dead marketing/blurb page? (Module 1 ops tool.)

For each firm it does one real fetch/render + parse and reports how many roles
came back, how many match the 2027-intern filter, and a sample of titles. A
browser-tier firm that returns 0 roles — or only navigation links like
"Internship Programme" / "Students & Graduates" with no location — is almost
certainly pointed at a blurb page (like Deutsche Bank's was) and needs its URL
swapped to the real search/listings page.

Run:
  python -m jobtracker.healthcheck --config jobtracker/config.yaml --out health.csv
  python -m jobtracker.healthcheck --priority   # only extras + high-finance
  python -m jobtracker.healthcheck --names "KKR" "Carlyle Group"
"""
from __future__ import annotations

import argparse
import asyncio
import csv

from .config import load, FirmTarget
from .diff import is_relevant
from .parsers import PARSERS
from . import monitor

# Titles that signal a programme-nav / blurb page rather than real reqs.
_NAV = {"students and graduates", "students & graduates", "graduate programme",
        "graduate program", "internship programme", "internship program",
        "insight programmes", "insight programme", "search programmes",
        "search roles", "early careers", "apply", "careers", "students",
        "graduates", "experienced professionals", "programmes", "our programmes"}


def _classify(tier: str, roles: list, matches: int) -> str:
    if not roles:
        return "EMPTY" if tier == "browser" else "empty(ok if off-season)"
    titles = [(p.title or "").strip().lower() for p in roles]
    has_loc = any(p.location for p in roles)
    if tier == "browser" and not has_loc and all(t in _NAV or len(t.split()) <= 3 for t in titles):
        return "BLURB/NAV"          # looks like the programme menu, not reqs
    return "ok"


async def check_one(conn_client, cfg, firm: FirmTarget, browser_ctx) -> dict:
    tier = firm.ats
    try:
        if firm.ats == "browser":
            from . import browser as B
            async with monitor._BROWSER_SEM:
                snap = await B.snapshot(browser_ctx, firm)
        else:
            raw = await monitor._fetch(conn_client, firm)
            parser = PARSERS[firm.ats]
            snap = parser(firm.name, raw, host=firm.host) if firm.ats == "workday" \
                else parser(firm.name, raw, base_url=firm.host)
        roles = snap.postings
        matches = [p for p in roles if is_relevant(p, cfg.relevance)]
        status = _classify(tier, roles, len(matches))
        sample = " | ".join((p.title or "")[:40] for p in roles[:4])
        return {"firm": firm.name, "tier": tier, "roles": len(roles),
                "matches": len(matches), "status": status, "sample": sample, "url": firm.url}
    except Exception as exc:  # noqa: BLE001
        return {"firm": firm.name, "tier": tier, "roles": 0, "matches": 0,
                "status": f"ERROR:{type(exc).__name__}", "sample": "", "url": firm.url}


_FIELDS = ["firm", "tier", "roles", "matches", "status", "sample", "url"]


async def run(cfg, firms: list[FirmTarget], concurrency: int = 6,
              out_path: str | None = None) -> list[dict]:
    needs_browser = any(f.ats == "browser" for f in firms)
    pw = browser = bctx = None
    if needs_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        bctx = await browser.new_context(user_agent=monitor._HEADERS["User-Agent"],
                                         viewport={"width": 1280, "height": 1600})
    rows: list[dict] = []
    sem = asyncio.Semaphore(concurrency)
    fh = None
    if out_path:                       # write incrementally so a long run can't lose data
        fh = open(out_path, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=_FIELDS); writer.writeheader(); fh.flush()
    lock = asyncio.Lock()
    done = [0]
    async with monitor._new_client() as client:
        async def one(f):
            async with sem:
                # hard cap per firm so one hung site can't stall the whole run
                try:
                    row = await asyncio.wait_for(check_one(client, cfg, f, bctx), timeout=70)
                except Exception as exc:  # noqa: BLE001
                    row = {"firm": f.name, "tier": f.ats, "roles": 0, "matches": 0,
                           "status": f"ERROR:{type(exc).__name__}", "sample": "", "url": f.url}
            rows.append(row)
            if fh:
                async with lock:
                    writer.writerow(row); fh.flush()
                    done[0] += 1
                    if done[0] % 20 == 0:
                        print(f"  ...{done[0]} done", flush=True)
        try:
            await asyncio.gather(*(one(f) for f in firms))
        finally:
            if fh: fh.close()
            if bctx: await bctx.close()
            if browser: await browser.close()
            if pw: await pw.stop()
    rows.sort(key=lambda r: r["firm"].lower())
    return rows


def _is_priority(name: str, extras: set, firmcats: dict) -> bool:
    if name in extras:
        return True
    cats = firmcats.get(name, set())
    LOW = {"Consulting", "Big 4", "Accounting and Audit", "Miscellaneous"}
    return bool(cats) and not (cats <= LOW)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="jobtracker/config.yaml")
    ap.add_argument("--out", default="health.csv")
    ap.add_argument("--names", nargs="*")
    ap.add_argument("--priority", action="store_true", help="only extras + high-finance")
    ap.add_argument("--browser-only", action="store_true")
    args = ap.parse_args(argv)

    cfg = load(args.config)
    firms = cfg.firms
    if args.names:
        want = set(args.names); firms = [f for f in firms if f.name in want]
    if args.browser_only:
        firms = [f for f in firms if f.ats == "browser"]
    if args.priority:
        import json, os
        t = os.environ.get("TEMP", ".")
        extras, firmcats = set(), {}
        try:
            extras = set(json.load(open(os.path.join(t, "extra_sectors.json"), encoding="utf-8")))
            tr = json.load(open(os.path.join(t, "uk_finance_2027.json"), encoding="utf-8"))
            for r in tr:
                firmcats.setdefault(r["company"]["name"], set()).update(r.get("categories") or [])
        except Exception:
            pass
        firms = [f for f in firms if _is_priority(f.name, extras, firmcats)]

    print(f"health-checking {len(firms)} firms ...", flush=True)
    rows = asyncio.run(run(cfg, firms, out_path=args.out))
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["firm", "tier", "roles", "matches", "status", "sample", "url"])
        w.writeheader(); w.writerows(rows)

    from collections import Counter
    st = Counter(r["status"].split(":")[0] for r in rows)
    suspects = [r for r in rows if r["status"] in ("EMPTY", "BLURB/NAV") or r["status"].startswith("ERROR")]
    print("status summary:", dict(st))
    print(f"\n{len(suspects)} SUSPECTS (likely wrong URL / needs the listings page):")
    for r in suspects:
        print(f"  [{r['status']:14}] {r['firm'][:26]:26} {r['tier']:11} roles={r['roles']:<3} {r['url'][:48]}")
    print(f"\nfull report -> {args.out}")


if __name__ == "__main__":
    main()
