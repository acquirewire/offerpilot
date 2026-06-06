"""Career-page parsers: raw response -> CareerPageSnapshot (Module 1).

Banks/firms mostly run two ATSs behind their career sites:

  * Workday   -- POST returns JSON at .../jobs (jobPostings[]). Goldman, Citi,
                 RBC, many others. Prefer the JSON endpoint you find in
                 DevTools > Network over scraping the rendered SPA.
  * Greenhouse-- GET https://boards-api.greenhouse.io/v1/boards/<token>/jobs
                 returns clean JSON. Hines and many funds use this.

Each parser is dependency-light (stdlib json) and returns the same normalized
Snapshot the detector diffs, so adding a firm is just picking the right parser
and endpoint in config -- no new diff logic.
"""
from __future__ import annotations

import json
import re

from .models import (
    CareerPageSnapshot,
    JobPosting,
    PostingStatus,
    KNOWN_LANGUAGES,
)

# Region inference from a location string. First match wins.
_REGION_HINTS: list[tuple[str, str]] = [
    ("hong kong", "APAC"), ("singapore", "APAC"), ("tokyo", "APAC"),
    ("shanghai", "APAC"), ("sydney", "APAC"), ("mumbai", "APAC"),
    ("london", "EMEA"), ("paris", "EMEA"), ("frankfurt", "EMEA"),
    ("dubai", "EMEA"), ("zurich", "EMEA"),
    ("new york", "AMER"), ("toronto", "AMER"), ("chicago", "AMER"),
    ("san francisco", "AMER"), ("boston", "AMER"),
]

# Cycle inference from a title.
_CYCLE_RE = re.compile(
    r"(20\d{2})?\s*(summer analyst|off[\s-]?cycle|spring (?:week|insight)|"
    r"summer internship|industrial placement|full[\s-]?time analyst)",
    re.IGNORECASE,
)


def infer_region(location: str | None) -> str | None:
    if not location:
        return None
    loc = location.lower()
    for needle, region in _REGION_HINTS:
        if needle in loc:
            return region
    return None


def infer_cycle(title: str) -> str | None:
    m = _CYCLE_RE.search(title or "")
    if not m:
        return None
    year, kind = m.group(1), m.group(2)
    label = kind.strip().title()
    return f"{year} {label}".strip() if year else label


def detect_languages(*texts: str | None) -> set[str]:
    """Languages explicitly named in the posting's text (title + description)."""
    blob = " ".join(t for t in texts if t).lower()
    return {lang for lang in KNOWN_LANGUAGES if lang in blob}


def _status_from_flags(*, available: bool | None, closed: bool | None) -> PostingStatus:
    if closed:
        return PostingStatus.CLOSED
    if available:
        return PostingStatus.OPEN
    if available is False:
        return PostingStatus.COMING_SOON
    return PostingStatus.UNKNOWN


def parse_greenhouse(firm: str, raw: str, *, base_url: str = "") -> CareerPageSnapshot:
    """Greenhouse boards-api JSON -> snapshot. Listed jobs are open to apply."""
    data = json.loads(raw)
    postings: list[JobPosting] = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        location = (job.get("location") or {}).get("name")
        content = job.get("content", "")  # present when ?content=true
        postings.append(
            JobPosting(
                req_id=str(job.get("id")) if job.get("id") is not None else None,
                title=title,
                status=PostingStatus.OPEN,  # a job on the board is applyable
                location=location,
                region=infer_region(location),
                languages=detect_languages(title, content),
                cycle=infer_cycle(title),
                apply_url=job.get("absolute_url") or base_url,
            )
        )
    return CareerPageSnapshot(firm=firm, postings=postings)


def parse_workday(firm: str, raw: str, *, host: str = "") -> CareerPageSnapshot:
    """Workday CxS JSON (jobPostings[]) -> snapshot.

    Workday rarely exposes an explicit open/closed flag in the list view, so a
    listed posting is treated as OPEN; the diff still only alerts on the
    transition into the list, which is the signal that matters.
    """
    data = json.loads(raw)
    postings: list[JobPosting] = []
    for jp in data.get("jobPostings", []):
        title = jp.get("title", "")
        location = jp.get("locationsText") or jp.get("location")
        ext_path = jp.get("externalPath", "")
        postings.append(
            JobPosting(
                req_id=jp.get("bulletFields", [None])[0] or ext_path or None,
                title=title,
                status=PostingStatus.OPEN,
                location=location,
                region=infer_region(location),
                languages=detect_languages(title),
                cycle=infer_cycle(title),
                apply_url=(host.rstrip("/") + ext_path) if host and ext_path else ext_path,
            )
        )
    return CareerPageSnapshot(firm=firm, postings=postings)


def parse_lever(firm: str, raw: str, *, base_url: str = "") -> CareerPageSnapshot:
    """Lever postings JSON (a flat list) -> snapshot. Listed = open to apply."""
    data = json.loads(raw)
    postings: list[JobPosting] = []
    for job in data if isinstance(data, list) else []:
        title = job.get("text", "")
        cats = job.get("categories") or {}
        location = cats.get("location")
        desc = job.get("descriptionPlain", "")
        postings.append(
            JobPosting(
                req_id=str(job.get("id")) if job.get("id") else None,
                title=title,
                status=PostingStatus.OPEN,
                location=location,
                region=infer_region(location),
                languages=detect_languages(title, desc),
                cycle=infer_cycle(title),
                apply_url=job.get("hostedUrl") or job.get("applyUrl") or base_url,
            )
        )
    return CareerPageSnapshot(firm=firm, postings=postings)


PARSERS = {
    "greenhouse": parse_greenhouse,
    "workday": parse_workday,
    "lever": parse_lever,
}
