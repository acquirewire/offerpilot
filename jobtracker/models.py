"""Data types for the career-page Drop Tracker (Module 1).

Mirrors the ticket monitor's models: a normalized per-item Status enum and a
Snapshot that the detector diffs against. The unit here is a *job posting*
rather than a ticket tier, and identity is the ATS requisition id when we can
get one (it survives page re-renders, unlike title text).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class PostingStatus(str, Enum):
    """Normalized state of a single job posting."""

    OPEN = "OPEN"                # apply button live -> actionable
    CLOSED = "CLOSED"            # listed but applications shut
    COMING_SOON = "COMING_SOON"  # announced, not yet open
    UNKNOWN = "UNKNOWN"


# Languages we care about matching against a posting's requirements.
# Kept as a set so filter logic is plain set intersection.
KNOWN_LANGUAGES = {"english", "cantonese", "mandarin", "french"}


@dataclass
class JobPosting:
    """One role on a firm's career page."""

    req_id: str | None          # ATS requisition id; the stable identity key
    title: str
    status: PostingStatus
    location: str | None = None
    region: str | None = None           # "APAC" | "EMEA" | "AMER"
    languages: set[str] = field(default_factory=set)  # lower-cased
    cycle: str | None = None            # "2027 Summer" | "Off-cycle"
    apply_url: str | None = None

    def key(self) -> str:
        """Stable identity for diffing. Falls back to title when no req_id."""
        return self.req_id or f"title::{self.title.strip().lower()}"


@dataclass
class CareerPageSnapshot:
    """Full parsed state of one career page at a point in time."""

    firm: str
    postings: list[JobPosting] = field(default_factory=list)

    def as_map(self) -> dict[str, JobPosting]:
        """key -> posting, the canonical form the detector diffs against."""
        return {p.key(): p for p in self.postings}


@dataclass
class RelevanceFilter:
    """What counts as worth-alerting. Empty collection == 'no constraint'."""

    keywords: set[str] = field(default_factory=set)     # OR gate (legacy): >=1 must appear
    regions: set[str] = field(default_factory=set)      # e.g. {"APAC"}
    # A posting passes the language gate if the user can satisfy AT LEAST the
    # languages it requires. So we store what the *user* speaks, and require
    # required_languages ⊆ user_languages.
    user_languages: set[str] = field(default_factory=lambda: {"english"})
    # Internship targeting (the "2027 internships only" rule):
    require_any: set[str] = field(default_factory=set)  # role must contain >=1 of these (e.g. intern terms)
    exclude: set[str] = field(default_factory=set)      # reject if any appears (full-time/senior)
    years: set[str] = field(default_factory=set)        # if a year is named, it must be one of these

    @classmethod
    def from_config(cls, raw: dict) -> "RelevanceFilter":
        return cls(
            keywords={k.lower() for k in raw.get("keywords", [])},
            regions={r.upper() for r in raw.get("regions", [])},
            user_languages={l.lower() for l in raw.get("user_languages", ["english"])},
            require_any={k.lower() for k in raw.get("require_any", [])},
            exclude={k.lower() for k in raw.get("exclude", [])},
            years={str(y) for y in raw.get("years", [])},
        )


def dumps_languages(langs: set[str]) -> str:
    """Serialize a language set for the SQLite `posting.languages` column."""
    return json.dumps(sorted(langs))
