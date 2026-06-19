"""Smart diffing for career pages (Module 1).

The problem with naively hashing a career page is that almost every fetch
differs: rotating CSRF tokens, "last updated" timestamps, view counters, CSP
nonces, ad/analytics blobs, copyright years. A byte-level diff fires constantly
and you learn to ignore it. So we diff in two layers:

  LAYER 1 -- content_fingerprint(html)
      Strip the volatile junk, keep only the job-listing-relevant text, and
      hash that. A changed fingerprint means "something meaningful moved on the
      page" -- the cheap gate that decides whether the expensive parse/LLM step
      is even worth running.

  LAYER 2 -- diff(previous, snapshot, filt)
      Once parsed into postings, emit an alert ONLY for transitions you'd act
      on: a relevant role that just OPENED, or a brand-new relevant role that
      appeared already open. We deliberately do not alert on closings or on
      UNKNOWN churn -- same policy as the ticket detector.

Relevance (keywords / region / language) is applied in layer 2 so we never page
the user about a Frankfurt back-office role when they're tracking HK IBD.
"""
from __future__ import annotations

import hashlib
import re

from selectolax.parser import HTMLParser

from .models import (
    CareerPageSnapshot,
    JobPosting,
    PostingStatus,
    RelevanceFilter,
)

_ACTIONABLE = {PostingStatus.OPEN}

# Tags whose contents are never job-listing signal. Dropped before hashing.
_NOISE_TAGS = (
    "script", "style", "noscript", "svg", "iframe",
    "footer", "head", "nav",
)

# Attribute-borne volatility: nonces, CSRF tokens, cache-busting query strings.
_NOISE_ATTR_RE = re.compile(
    r'\b(nonce|csrf[-_]?token|data-csrf|_token|sid|sessionid)\b',
    re.IGNORECASE,
)

# Substrings that, on their own line, are pure chrome and should be dropped so a
# copyright-year rollover or a "last viewed" tick never moves the fingerprint.
_NOISE_LINE_RE = re.compile(
    r'(?:©|copyright|all rights reserved'
    r'|last\s+updated|page\s+generated'
    r'|\bviews?\b|\d+\s+applicants?'
    r'|cookie|privacy policy|terms of (?:use|service))',
    re.IGNORECASE,
)

# Collapse anything that looks like a volatile token/number-with-time so two
# fetches of an otherwise-identical page agree.
_TIMESTAMP_RE = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?')
_LONGNUM_RE = re.compile(r'\b\d{6,}\b')          # epoch ms, request ids, etc.
_WS_RE = re.compile(r'\s+')


def _normalize(html: str, scope_selector: str | None = None) -> str:
    """Reduce a page to its stable, meaningful text.

    `scope_selector` optionally narrows hashing to the listings container (e.g.
    "main" or "#search-results"); strongly recommended per-firm, because it
    makes the fingerprint immune to everything outside the results area.
    """
    tree = HTMLParser(html)

    for tag in _NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()

    root = tree
    if scope_selector:
        scoped = tree.css_first(scope_selector)
        if scoped is not None:
            root = scoped

    text = root.text(separator="\n", strip=True)

    kept: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or _NOISE_LINE_RE.search(line):
            continue
        line = _TIMESTAMP_RE.sub("", line)
        line = _LONGNUM_RE.sub("", line)
        line = _WS_RE.sub(" ", line).strip()
        if line:
            kept.append(line.lower())

    # Sort so a pure reordering of equivalent cards doesn't read as a change,
    # while any added/removed/renamed line still does.
    return "\n".join(sorted(kept))


def content_fingerprint(html: str, scope_selector: str | None = None) -> str:
    """Stable hash of the meaningful page content. Layer-1 cheap change gate."""
    norm = _normalize(html, scope_selector)
    # Also fold in any CSRF/nonce attribute *names* removal isn't enough for:
    # we simply ignore attributes entirely by hashing text only, but keep the
    # regex documented so future structural hashing stays noise-aware.
    _ = _NOISE_ATTR_RE  # referenced to keep the noise contract explicit
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


_YEAR_RE = re.compile(r"\b20\d{2}\b")
_TERM_CACHE: dict[str, re.Pattern] = {}


def _term_re(term: str) -> re.Pattern:
    """Word-boundary matcher for a filter term. 'intern' matches intern/interns/
    internship but NOT 'internal'/'international'; other terms match on a leading
    word boundary (so 'placement' also catches 'placements')."""
    pat = _TERM_CACHE.get(term)
    if pat is None:
        if term == "intern":
            rx = r"\bintern(?:ship|s)?\b"
        else:
            rx = r"\b" + re.escape(term)
        pat = _TERM_CACHE[term] = re.compile(rx, re.IGNORECASE)
    return pat


def _any_term(haystack: str, terms) -> bool:
    return any(_term_re(t).search(haystack) for t in terms)


def is_relevant(posting: JobPosting, filt: RelevanceFilter) -> bool:
    """True if this posting matches the user's gates.

    Internship targeting (e.g. "2027 internships only"):
      * require_any -- the title must read like an internship (>=1 term), which
        is what strips out full-time / experienced roles a careers feed mixes in.
      * exclude     -- hard reject on seniority / full-time markers.
      * years       -- if the title names a cycle year, it must be a wanted one
        (a title with no year still passes, since many list the year elsewhere).
    """
    haystack = f"{posting.title} {posting.cycle or ''}".lower()

    # Keyword gate (legacy OR): at least one target keyword in title or cycle.
    if filt.keywords and not any(k in haystack for k in filt.keywords):
        return False

    # Internship gate: must contain at least one internship term (word-aware,
    # so "Internal Audit" / "International" don't masquerade as "intern").
    if filt.require_any and not _any_term(haystack, filt.require_any):
        return False

    # Seniority / full-time exclusions.
    if filt.exclude and _any_term(haystack, filt.exclude):
        return False

    # Year gate: if a year is named and it isn't one we want, drop it.
    if filt.years:
        named = set(_YEAR_RE.findall(haystack))
        if named and not (named & filt.years):
            return False

    # Region gate.
    if filt.regions and (posting.region or "").upper() not in filt.regions:
        return False

    # Language gate: user must satisfy every language the role requires.
    # (Empty requirement set -> no constraint -> passes.)
    if posting.languages and not posting.languages.issubset(filt.user_languages):
        return False

    return True


def diff(
    previous: dict[str, JobPosting],
    snapshot: CareerPageSnapshot,
    filt: RelevanceFilter,
) -> list[str]:
    """Return alert-worthy change descriptions (empty == nothing actionable).

    `previous` is the last snapshot's `as_map()`; persist it (or its req_id ->
    status projection) in the `posting` table between runs.
    """
    events: list[str] = []
    new_map = snapshot.as_map()

    for key, posting in new_map.items():
        if not is_relevant(posting, filt):
            continue

        before = previous.get(key)
        lang = f" [{'/'.join(sorted(posting.languages))}]" if posting.languages else ""
        loc = f" — {posting.location}" if posting.location else ""

        if before is None:
            # Never seen this req. Only page the user if it's already open.
            if posting.status in _ACTIONABLE:
                events.append(
                    f"NEW & OPEN at {snapshot.firm}: '{posting.title}'{loc}{lang}"
                )
            continue

        if posting.status in _ACTIONABLE and before.status not in _ACTIONABLE:
            events.append(
                f"'{posting.title}' at {snapshot.firm} is now OPEN "
                f"(was {before.status.value}){loc}{lang}"
            )

    return events
