"""Playwright fallback for the JS-only / proprietary tail (Module 1, Phase 5).

The 266 firms `resolve.py` can't reach have no readable JSON feed from a plain
HTTP client — they're client-rendered SPAs (Avature, tal.net, iCIMS, Oracle,
Teamtailor, bespoke). Rather than hand-write a scraper per site, we render the
page in headless Chromium and use two generic signals, in order:

  1. NETWORK CAPTURE  -- record every JSON response the page fetches while it
     loads, then pick the one that contains the largest array of job-like
     objects. This catches virtually every SPA, because the listing it shows you
     was itself fetched as JSON.
  2. DOM FALLBACK     -- if nothing job-shaped was fetched, read anchor links in
     the rendered DOM and treat plausible job titles as postings.

Either way we emit the same CareerPageSnapshot the detector diffs, so browser
firms flow through the identical gate -> diff -> 2027-intern filter -> alert.
Heavier than HTTP, so these firms poll on a long interval with low concurrency.
"""
from __future__ import annotations

import json as _json

from .models import CareerPageSnapshot, JobPosting, PostingStatus
from .parsers import infer_region, infer_cycle, detect_languages

# Keys an ATS commonly uses for the job title / location / link.
_TITLE_KEYS = ("title", "name", "text", "jobtitle", "positiontitle", "positionname",
               "position", "displayname", "postingtitle", "label")
_LOC_KEYS = ("locationstext", "location", "primarylocation", "city", "locationname",
             "joblocation", "country", "region")
_URL_KEYS = ("absolute_url", "hostedurl", "applyurl", "externalpath", "url",
             "canonicalurl", "joburl", "detailurl", "ref")
_BLOCK_RESOURCES = {"image", "media", "font", "stylesheet"}
_JOBLIKE_MIN = 2


def _get(d: dict, keys) -> str | None:
    low = {k.lower(): v for k, v in d.items() if isinstance(k, str)}
    for k in keys:
        v = low.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):  # e.g. location: {name: ...}
            for kk in ("name", "label", "city", "value"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk].strip()
    return None


_DEPT_KEYS = ("department", "team", "division", "businessdivision", "category",
              "function", "businessarea", "jobfamily")
_REQ_KEYS = ("id", "jobid", "reqid", "requisitionid", "postingid", "externalpath",
             "slug", "shortcode")


def _job_score(d: dict) -> int:
    """How job-shaped is this dict? A country/lookup row scores ~1; a real
    posting scores >=3 (title + location/url/date/department/req-id)."""
    if not isinstance(d, dict):
        return 0
    low = {k.lower(): v for k, v in d.items() if isinstance(k, str)}
    score = 0
    if _get(d, _TITLE_KEYS):
        score += 1
    else:
        return 0  # no title -> not a posting
    if _get(d, _LOC_KEYS):
        score += 1
    if _get(d, _URL_KEYS):
        score += 1
    if any("date" in k for k in low):
        score += 1
    if any(k in low for k in _DEPT_KEYS):
        score += 1
    if any(k in low for k in _REQ_KEYS):
        score += 1
    return score


def _find_job_arrays(obj, out: list[list]) -> None:
    """Recursively collect every list of dicts that has a title key."""
    if isinstance(obj, list):
        cand = [x for x in obj if isinstance(x, dict) and _get(x, _TITLE_KEYS)]
        if len(cand) >= _JOBLIKE_MIN:
            out.append(cand)
        for x in obj:
            _find_job_arrays(x, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _find_job_arrays(v, out)


def _postings_from_json(blobs: list) -> list[JobPosting]:
    best: list = []
    best_rank = (0, 0)  # (items scoring >=3, length) — picks jobs over lookup lists
    for blob in blobs:
        found: list[list] = []
        _find_job_arrays(blob, found)
        for arr in found:
            strong = sum(1 for x in arr if _job_score(x) >= 3)
            rank = (strong, len(arr))
            if rank > best_rank:
                best_rank, best = rank, arr
    # If nothing looked like a real posting (only lookup/country lists), bail so
    # the caller falls back to DOM scraping.
    if best_rank[0] < _JOBLIKE_MIN:
        return []
    postings: list[JobPosting] = []
    seen = set()
    for d in best:
        title = _get(d, _TITLE_KEYS)
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        loc = _get(d, _LOC_KEYS)
        url = _get(d, _URL_KEYS)
        postings.append(JobPosting(
            req_id=str(d.get("id") or d.get("jobId") or d.get("requisitionId") or "") or None,
            title=title, status=PostingStatus.OPEN, location=loc,
            region=infer_region(loc), languages=detect_languages(title),
            cycle=infer_cycle(title), apply_url=url,
        ))
    return postings


async def _postings_from_dom(page) -> list[JobPosting]:
    anchors = await page.eval_on_selector_all(
        "a",
        "els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href})).filter(x => x.t.length>6 && x.t.length<140)",
    )
    postings: list[JobPosting] = []
    seen = set()
    for a in anchors:
        t = a.get("t", "")
        low = t.lower()
        if low in seen or "\n" in t:
            continue
        # cheap "is this a job title" gate: must contain a letter and a job-ish word
        if not any(w in low for w in ("intern", "analyst", "associate", "graduate",
                                      "placement", "summer", "trainee", "programme",
                                      "program", "scheme")):
            continue
        seen.add(low)
        postings.append(JobPosting(
            req_id=None, title=t, status=PostingStatus.OPEN, location=None,
            region=None, languages=detect_languages(t), cycle=infer_cycle(t),
            apply_url=a.get("h"),
        ))
    return postings


async def snapshot(context, firm, *, settle_ms: int = 9000) -> CareerPageSnapshot:
    """Render firm.url in a fresh page; return a CareerPageSnapshot."""
    page = await context.new_page()
    captured: list = []

    async def on_response(resp):
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            body = await resp.json()
            captured.append(body)
        except Exception:
            pass

    # speed: drop heavy resources
    async def route(r):
        if r.request.resource_type in _BLOCK_RESOURCES:
            await r.abort()
        else:
            await r.continue_()

    try:
        await page.route("**/*", route)
        page.on("response", on_response)
        last_err = None
        for attempt in range(2):  # one retry: SPAs throw transient HTTP2/nav errors
            try:
                await page.goto(firm.url, wait_until="domcontentloaded", timeout=30000)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await page.wait_for_timeout(1500)
        if last_err is not None:
            raise last_err
        try:
            await page.wait_for_load_state("networkidle", timeout=settle_ms)
        except Exception:
            await page.wait_for_timeout(settle_ms)

        # Portal sites show nothing until you search. If configured, type the term
        # into the first plausible search box, submit, and let the results XHR fire
        # (the response listener keeps capturing).
        term = getattr(firm, "search_term", None)
        if term:
            for sel in ("input[type=search]", "input[name*=search i]",
                        "input[placeholder*=search i]", "input[aria-label*=search i]",
                        "#search", ".search input", "input[type=text]"):
                try:
                    box = await page.query_selector(sel)
                    if box:
                        await box.fill(term)
                        await box.press("Enter")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=settle_ms)
                        except Exception:
                            await page.wait_for_timeout(settle_ms)
                        break
                except Exception:
                    continue

        postings = _postings_from_json(captured)
        if not postings:
            postings = await _postings_from_dom(page)
        return CareerPageSnapshot(firm=firm.name, postings=postings)
    finally:
        await page.close()
