"""SQLite persistence for the job tracker (Module 4) + the diff's state store.

This is the source of truth. Excel is exported *from* here (a view), never
written to directly, so concurrent monitor runs can't corrupt the log.

Two roles:
  * Module 1 state  -- `load_previous()` rebuilds the `previous` map the diff
    needs; `save_snapshot()` writes the new state back after each poll.
  * Module 4 log    -- `log_application()` records a real submission and its
    pipeline history; `check_firm_limit()` powers the Rule Engine.

Stdlib sqlite3 only, to match the repo's lean deps. Timestamps are ISO8601 UTC.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import (
    CareerPageSnapshot,
    JobPosting,
    PostingStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS firm (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    slug          TEXT NOT NULL UNIQUE,
    ats           TEXT,
    max_apps      INTEGER DEFAULT 3,
    careers_url   TEXT
);

CREATE TABLE IF NOT EXISTS posting (
    id            INTEGER PRIMARY KEY,
    firm_id       INTEGER NOT NULL REFERENCES firm(id),
    posting_key   TEXT NOT NULL,              -- JobPosting.key(): req_id or title fallback
    req_id        TEXT,
    title         TEXT NOT NULL,
    location      TEXT,
    region        TEXT,
    languages     TEXT,                       -- JSON array
    cycle         TEXT,
    status        TEXT NOT NULL,
    apply_url     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    content_hash  TEXT,
    UNIQUE(firm_id, posting_key)
);

CREATE TABLE IF NOT EXISTS application (
    id            INTEGER PRIMARY KEY,
    posting_id    INTEGER NOT NULL REFERENCES posting(id),
    firm_id       INTEGER NOT NULL REFERENCES firm(id),
    applied_at    TEXT NOT NULL,
    stage         TEXT NOT NULL DEFAULT 'Applied',
    cv_file       TEXT,
    cover_file    TEXT,
    ats_match_pct REAL,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS stage_event (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES application(id),
    stage          TEXT NOT NULL,
    occurred_at    TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS firm_load AS
SELECT f.id AS firm_id, f.name, f.max_apps,
       COUNT(a.id) AS active_apps,
       (COUNT(a.id) >= f.max_apps) AS at_limit
FROM firm f
LEFT JOIN application a
       ON a.firm_id = f.id AND a.stage NOT IN ('Rejected', 'Withdrawn')
GROUP BY f.id;
"""

# Stages that count against a firm's application cap (mirrors the firm_load view).
_ACTIVE_STAGES_EXCLUDED = ("Rejected", "Withdrawn")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str = "jobtracker.db") -> sqlite3.Connection:
    """Open the DB with foreign keys on and row access by column name."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_or_create_firm(
    conn: sqlite3.Connection,
    name: str,
    slug: str,
    *,
    ats: str | None = None,
    max_apps: int = 3,
    careers_url: str | None = None,
) -> int:
    """Return the firm id, inserting it on first sight."""
    row = conn.execute("SELECT id FROM firm WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO firm (name, slug, ats, max_apps, careers_url) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, slug, ats, max_apps, careers_url),
    )
    conn.commit()
    return cur.lastrowid


# --- Module 1: diff state store ------------------------------------------------

def _row_to_posting(row: sqlite3.Row) -> JobPosting:
    return JobPosting(
        req_id=row["req_id"],
        title=row["title"],
        status=PostingStatus(row["status"]),
        location=row["location"],
        region=row["region"],
        languages=set(json.loads(row["languages"] or "[]")),
        cycle=row["cycle"],
        apply_url=row["apply_url"],
    )


def load_previous(conn: sqlite3.Connection, firm_id: int) -> dict[str, JobPosting]:
    """Rebuild the `previous` map the diff compares against.

    Keyed by posting_key, which is exactly what `CareerPageSnapshot.as_map()`
    produces, so the two sides of `diff(previous, snapshot, filt)` line up.
    """
    rows = conn.execute(
        "SELECT * FROM posting WHERE firm_id = ?", (firm_id,)
    ).fetchall()
    return {row["posting_key"]: _row_to_posting(row) for row in rows}


def get_or_create_posting(
    conn: sqlite3.Connection,
    firm_id: int,
    title: str,
    *,
    req_id: str | None = None,
    location: str | None = None,
    region: str | None = None,
    cycle: str | None = None,
    status: str = "OPEN",
    apply_url: str | None = None,
) -> int:
    """Return a posting id, creating a minimal row if needed.

    Used by `apply` to attach an application to a role even if the monitor
    hasn't recorded it yet. Keyed the same way the diff keys postings.
    """
    key = req_id or f"title::{title.strip().lower()}"
    row = conn.execute(
        "SELECT id FROM posting WHERE firm_id = ? AND posting_key = ?", (firm_id, key)
    ).fetchone()
    if row:
        return row["id"]
    now = _now()
    cur = conn.execute(
        "INSERT INTO posting (firm_id, posting_key, req_id, title, location, region, "
        "languages, cycle, status, apply_url, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?)",
        (firm_id, key, req_id, title, location, region, cycle, status, apply_url, now, now),
    )
    conn.commit()
    return cur.lastrowid


def save_snapshot(
    conn: sqlite3.Connection,
    firm_id: int,
    snapshot: CareerPageSnapshot,
    content_hash: str | None = None,
) -> None:
    """Upsert every posting in the snapshot, refreshing status and last_seen.

    Idempotent: re-running on an unchanged page only bumps last_seen. Call this
    AFTER diffing so the diff still sees the prior state.
    """
    now = _now()
    for posting in snapshot.postings:
        conn.execute(
            """
            INSERT INTO posting (
                firm_id, posting_key, req_id, title, location, region,
                languages, cycle, status, apply_url,
                first_seen, last_seen, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(firm_id, posting_key) DO UPDATE SET
                status       = excluded.status,
                title        = excluded.title,
                location     = excluded.location,
                region       = excluded.region,
                languages    = excluded.languages,
                cycle        = excluded.cycle,
                apply_url    = excluded.apply_url,
                last_seen    = excluded.last_seen,
                content_hash = excluded.content_hash
            """,
            (
                firm_id,
                posting.key(),
                posting.req_id,
                posting.title,
                posting.location,
                posting.region,
                json.dumps(sorted(posting.languages)),
                posting.cycle,
                posting.status.value,
                posting.apply_url,
                now,
                now,
                content_hash,
            ),
        )
    conn.commit()


# --- Module 4: application log + Rule Engine -----------------------------------

def log_application(
    conn: sqlite3.Connection,
    posting_id: int,
    firm_id: int,
    *,
    cv_file: str | None = None,
    cover_file: str | None = None,
    ats_match_pct: float | None = None,
    notes: str | None = None,
) -> int:
    """Record a submitted application + its opening stage event. Returns app id.

    This is the hook the autofill flow calls right after a successful submit.
    """
    now = _now()
    cur = conn.execute(
        "INSERT INTO application "
        "(posting_id, firm_id, applied_at, stage, cv_file, cover_file, ats_match_pct, notes) "
        "VALUES (?, ?, ?, 'Applied', ?, ?, ?, ?)",
        (posting_id, firm_id, now, cv_file, cover_file, ats_match_pct, notes),
    )
    app_id = cur.lastrowid
    conn.execute(
        "INSERT INTO stage_event (application_id, stage, occurred_at) "
        "VALUES (?, 'Applied', ?)",
        (app_id, now),
    )
    conn.commit()
    return app_id


def advance_stage(conn: sqlite3.Connection, application_id: int, stage: str) -> None:
    """Move an application to a new pipeline stage and record the transition."""
    now = _now()
    conn.execute(
        "UPDATE application SET stage = ? WHERE id = ?", (stage, application_id)
    )
    conn.execute(
        "INSERT INTO stage_event (application_id, stage, occurred_at) VALUES (?, ?, ?)",
        (application_id, stage, now),
    )
    conn.commit()


def check_firm_limit(conn: sqlite3.Connection, firm_id: int) -> tuple[int, int, bool]:
    """Rule Engine: (active_apps, max_apps, at_limit) for one firm.

    Call before launching an autofill so you can warn the user *before* burning
    one of a limited number of slots at a bank.
    """
    row = conn.execute(
        "SELECT active_apps, max_apps, at_limit FROM firm_load WHERE firm_id = ?",
        (firm_id,),
    ).fetchone()
    if row is None:  # firm exists but no applications yet
        m = conn.execute(
            "SELECT max_apps FROM firm WHERE id = ?", (firm_id,)
        ).fetchone()
        return (0, m["max_apps"] if m else 0, False)
    return (row["active_apps"], row["max_apps"], bool(row["at_limit"]))
