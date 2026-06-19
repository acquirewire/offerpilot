"""Resolve each firm's *live ATS job feed* from its careers URL (Module 1, Phase 4).

`discover.py` blindly guesses Greenhouse/Lever tokens. This goes further: it
starts from the careers landing URL we already have for every firm and

  1. pattern-matches the URL itself against known ATS shapes (Greenhouse, Lever,
     Ashby, Workday, Workable, SmartRecruiters, Recruitee, Pinpoint), else
  2. fetches the landing page and scans the HTML/redirects for an embedded ATS
     (career pages almost always load their board from one of these), then
  3. builds the ATS's JSON feed URL and verifies it actually returns jobs.

Output: a paste-ready `firms:` YAML block of source-direct feeds, plus a
`manual_needed` list for the JS-only / proprietary tail (Avature, tal.net,
iCIMS, Oracle, Teamtailor-with-key) that needs a one-time DevTools endpoint.

Run:
  python -m jobtracker.resolve --map jobtracker/firm_urls.json \
      --out jobtracker/resolved.yaml --manual jobtracker/manual_needed.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re

try:
    from curl_cffi.requests import AsyncSession  # impersonates Chrome -> through Cloudflare
    def _new_client():
        return AsyncSession(impersonate="chrome", timeout=20)
except ImportError:  # pragma: no cover
    import httpx
    def _new_client():
        return httpx.AsyncClient(timeout=20, follow_redirects=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WD_BODY = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

# --- ATS signatures: regex over a URL -> (ats, dict of extracted params) ------

def _gh(m):  return ("greenhouse", {"token": m.group(1)})
def _lv(m):  return ("lever", {"token": m.group(1)})
def _ash(m): return ("ashby", {"token": m.group(1)})
def _wk(m):  return ("workable", {"token": m.group(1)})
def _sr(m):  return ("smartrecruiters", {"token": m.group(1)})
def _rec(m): return ("recruitee", {"token": m.group(1)})
def _pin(m): return ("pinpoint", {"token": m.group(1)})

_URL_SIGS: list[tuple[re.Pattern, callable]] = [
    # API endpoints (seen when sniffing a page's network traffic)
    (re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)", re.I), _sr),
    (re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.-]+)", re.I), _ash),
    (re.compile(r"apply\.workable\.com/api/[^/]+/(?:widget/)?accounts/([A-Za-z0-9_-]+)", re.I), _wk),
    (re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([A-Za-z0-9_-]+)", re.I), _gh),
    (re.compile(r"job-boards\.(?:eu\.)?greenhouse\.io/([A-Za-z0-9_-]+)", re.I), _gh),
    (re.compile(r"greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)", re.I), _gh),
    (re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", re.I), _lv),
    (re.compile(r"api\.lever\.co/v0/postings/([A-Za-z0-9_-]+)", re.I), _lv),
    (re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I), _ash),
    (re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)", re.I), _wk),
    (re.compile(r"([A-Za-z0-9_-]+)\.workable\.com", re.I), _wk),
    (re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I), _sr),
    (re.compile(r"smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I), _sr),
    (re.compile(r"([A-Za-z0-9_-]+)\.recruitee\.com", re.I), _rec),
    (re.compile(r"([A-Za-z0-9_-]+)\.pinpointhq\.com", re.I), _pin),
]
# Workday handled separately (needs tenant + datacenter + site).
_WD_JOBS = re.compile(r"https?://([A-Za-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[^/]+/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)
_WD_SITE = re.compile(r"https?://(?:www\.)?(wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)", re.I)


def detect_workday(url: str) -> dict | None:
    m = _WD_JOBS.search(url)
    if m:
        tenant, wd, site = m.group(1), m.group(2), m.group(3)
        if site.lower() in ("wday", "en-us"):
            return None
        host = f"https://{tenant}.{wd}.myworkdayjobs.com"
        return {"ats": "workday", "host": host,
                "url": f"{host}/wday/cxs/{tenant}/{site}/jobs", "method": "POST", "body": WD_BODY}
    m = _WD_SITE.search(url)
    if m:
        wd, tenant, site = m.group(1), m.group(2), m.group(3)
        host = f"https://{wd}.myworkdaysite.com"
        return {"ats": "workday", "host": host,
                "url": f"{host}/wday/cxs/{tenant}/{site}/jobs", "method": "POST", "body": WD_BODY}
    return None


def detect_url(url: str) -> dict | None:
    wd = detect_workday(url)
    if wd:
        return wd
    for rx, fn in _URL_SIGS:
        m = rx.search(url)
        if m:
            ats, params = fn(m)
            tok = params["token"]
            if tok.lower() in ("en", "en-us", "en-gb", "www", "jobs", "careers", "job", "uk"):
                continue
            return {"ats": ats, **params}
    return None


# --- feed URL builders + how to fetch/verify each ATS -------------------------

def feed_url(d: dict) -> tuple[str, str, dict | None]:
    """Return (url, method, body) for the JSON feed."""
    ats = d["ats"]
    t = d.get("token", "")
    if ats == "greenhouse":
        return (f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true", "GET", None)
    if ats == "lever":
        return (f"https://api.lever.co/v0/postings/{t}?mode=json", "GET", None)
    if ats == "ashby":
        return (f"https://api.ashbyhq.com/posting-api/job-board/{t}", "GET", None)
    if ats == "smartrecruiters":
        return (f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=100", "GET", None)
    if ats == "workable":
        return (f"https://apply.workable.com/api/v1/widget/accounts/{t}?details=true", "GET", None)
    if ats == "recruitee":
        return (f"https://{t}.recruitee.com/api/offers/", "GET", None)
    if ats == "pinpoint":
        return (f"https://{t}.pinpointhq.com/postings.json", "GET", None)
    if ats == "workday":
        return (d["url"], "POST", d.get("body", WD_BODY))
    raise ValueError(ats)


def count_jobs(ats: str, data) -> int:
    try:
        if ats == "greenhouse":     return len(data.get("jobs", []))
        if ats == "lever":          return len(data) if isinstance(data, list) else 0
        if ats == "ashby":          return len(data.get("jobs", []))
        if ats == "smartrecruiters":return len(data.get("content", []))
        if ats == "workable":       return len(data.get("jobs", data.get("results", [])))
        if ats == "recruitee":      return len(data.get("offers", []))
        if ats == "pinpoint":       return len(data.get("data", []))
        if ats == "workday":        return int(data.get("total", len(data.get("jobPostings", []))))
    except Exception:
        return 0
    return 0


async def verify(client, d: dict) -> dict | None:
    url, method, body = feed_url(d)
    try:
        if method == "POST":
            r = await client.post(url, json=body, headers={"User-Agent": UA, "Accept": "application/json"})
        else:
            r = await client.get(url, headers={"User-Agent": UA, "Accept": "application/json"})
        if r.status_code != 200:
            return None
        data = r.json()
        n = count_jobs(d["ats"], data)
        if n <= 0:
            return None
        out = dict(d)
        out.update({"feed": url, "method": method, "jobs": n})
        if body is not None:
            out["body"] = body
        return out
    except Exception:
        return None


# --- per-firm resolution -----------------------------------------------------

try:
    from rapidfuzz import fuzz
    def _name_match(a: str, b: str) -> int:
        return int(fuzz.token_set_ratio(a.lower(), b.lower()))
except ImportError:
    from difflib import SequenceMatcher
    def _name_match(a: str, b: str) -> int:
        return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)

_SUFFIXES = {"group", "capital", "partners", "management", "advisors", "advisory",
             "asset", "investments", "investment", "securities", "global", "co",
             "international", "llp", "plc", "ltd", "company", "trading", "technologies",
             "holdings", "markets", "bank", "insurance", "fund", "associates", "and", "the"}


def guess_tokens(firm: str) -> list[str]:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", firm) if w]
    full = re.sub(r"[^a-z0-9]", "", firm.lower())
    core = re.sub(r"[^a-z0-9]", "", "".join(w for w in words if w.lower() not in _SUFFIXES).lower())
    first = words[0].lower() if words else ""
    out: list[str] = []
    for c in (core, full, first):
        if c and len(c) >= 3 and c not in out:
            out.append(c)
    return out[:3]


async def _gh_named(client, firm, tok) -> dict | None:
    """Greenhouse guess, verified by fuzzy-matching the board's own name."""
    try:
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs",
                             headers={"User-Agent": UA})
        if r.status_code != 200 or not r.json().get("jobs"):
            return None
        meta = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}",
                               headers={"User-Agent": UA})
        board = meta.json().get("name", tok) if meta.status_code == 200 else tok
        if _name_match(firm, board) < 70:
            return None
        return {"ats": "greenhouse", "token": tok}
    except Exception:
        return None


async def guess_feed(client, firm) -> dict | None:
    """Token-guess across ATSs when the landing page hid the board. Greenhouse is
    name-verified; others are accepted on a verified jobs hit (rarer collisions)."""
    for tok in guess_tokens(firm):
        d = await _gh_named(client, firm, tok)
        if d:
            return d
    for tok in guess_tokens(firm):
        for ats in ("lever", "ashby", "workable", "recruitee", "pinpoint", "smartrecruiters"):
            v = await verify(client, {"ats": ats, "token": tok})
            if v and _name_match(firm, tok) >= 55:
                return {"ats": ats, "token": tok}
    return None


async def resolve_firm(client, name: str, landing: str) -> dict | None:
    # 1) the URL we already have
    d = detect_url(landing)
    if d:
        v = await verify(client, d)
        if v:
            v["firm"], v["landing"] = name, landing
            return v
    # 2) fetch the landing page, scan HTML + final redirect URL for an ATS
    try:
        r = await client.get(landing, headers={"User-Agent": UA}, timeout=15)
        html, final = r.text, str(r.url)
        for cand in (final, html):
            d = detect_url(cand)
            if d:
                v = await verify(client, d)
                if v:
                    v["firm"], v["landing"] = name, landing
                    return v
    except Exception:
        pass
    # 3) token-guess fallback (name-verified for Greenhouse)
    d = await guess_feed(client, name)
    if d:
        v = await verify(client, d)
        if v:
            v["firm"], v["landing"] = name, landing
            return v
    return None


async def run(mapping: dict[str, str], concurrency: int = 16) -> tuple[list[dict], list[tuple[str, str]]]:
    sem = asyncio.Semaphore(concurrency)
    resolved: list[dict] = []
    failed: list[tuple[str, str]] = []
    async with _new_client() as client:
        async def one(name, url):
            async with sem:
                try:
                    res = await resolve_firm(client, name, url)
                except Exception:
                    res = None
            (resolved if res else failed).append(res or (name, url))
        await asyncio.gather(*(one(n, u) for n, u in mapping.items()))
    resolved.sort(key=lambda d: d["firm"].lower())
    failed.sort(key=lambda t: t[0].lower())
    return resolved, failed


def _slug(firm: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", firm) if w)


def emit_yaml(resolved: list[dict], interval: int) -> str:
    lines = ["# Auto-resolved source-direct ATS feeds (jobtracker.resolve).",
             "# Merge under the `firms:` key of config.yaml.", "firms:"]
    for d in resolved:
        lines.append(f'- name: "{d["firm"]}"')
        lines.append(f'  slug: "{_slug(d["firm"])}"')
        lines.append(f'  ats: {d["ats"]}')
        lines.append(f'  url: "{d["feed"]}"')
        if d.get("method") == "POST":
            lines.append("  method: POST")
            lines.append(f'  body: {json.dumps(d.get("body", WD_BODY))}')
        if d.get("host"):
            lines.append(f'  host: "{d["host"]}"')
        lines.append(f'  interval: {interval}')
        lines.append(f'  # {d["jobs"]} live postings  | board: {d.get("token","")}')
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--map", required=True, help="JSON {firm: careers_url}")
    p.add_argument("--out", default="jobtracker/resolved.yaml")
    p.add_argument("--manual", default="jobtracker/manual_needed.txt")
    p.add_argument("--interval", type=int, default=1800, help="poll seconds per firm")
    args = p.parse_args(argv)

    with open(args.map, encoding="utf-8") as fh:
        mapping = json.load(fh)

    resolved, failed = asyncio.run(run(mapping))

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(emit_yaml(resolved, args.interval))
    with open(args.manual, "w", encoding="utf-8") as fh:
        fh.write("# Firms whose live feed couldn't be auto-resolved.\n")
        fh.write("# These need a one-time DevTools endpoint (Workday/Avature/tal.net/\n")
        fh.write("# iCIMS/Oracle/Teamtailor) or a Playwright fallback.\n\n")
        for name, url in failed:
            fh.write(f"{name}\t{url}\n")

    from collections import Counter
    by_ats = Counter(d["ats"] for d in resolved)
    print(f"firms in: {len(mapping)}")
    print(f"  resolved source-direct: {len(resolved)}")
    for a, n in by_ats.most_common():
        print(f"      {n:>3}  {a}")
    print(f"  need manual/Playwright: {len(failed)}")
    print(f"  -> {args.out}\n  -> {args.manual}")


if __name__ == "__main__":
    main()
