"""Excel export (Module 4): render the SQLite log as a .xlsx view.

SQLite stays the source of truth; this produces a shareable spreadsheet on
demand. Each sheet is one query. Requires pandas + openpyxl.
"""
from __future__ import annotations

import sqlite3

_SHEETS: dict[str, str] = {
    "Applications": """
        SELECT f.name AS firm, p.title AS role, p.location, p.cycle,
               a.applied_at, a.stage, a.cv_file, a.cover_file,
               ROUND(a.ats_match_pct * 100, 1) AS ats_match,
               a.notes
        FROM application a
        JOIN firm f ON f.id = a.firm_id
        JOIN posting p ON p.id = a.posting_id
        ORDER BY a.applied_at DESC
    """,
    "Pipeline": """
        SELECT f.name AS firm, p.title AS role, a.stage,
               (SELECT MAX(occurred_at) FROM stage_event se
                WHERE se.application_id = a.id) AS last_update
        FROM application a
        JOIN firm f ON f.id = a.firm_id
        JOIN posting p ON p.id = a.posting_id
        ORDER BY f.name, a.stage
    """,
    "FirmLimits": "SELECT name AS firm, active_apps, max_apps, at_limit FROM firm_load ORDER BY name",
    "OpenPostings": """
        SELECT f.name AS firm, p.title AS role, p.location, p.cycle,
               p.status, p.last_seen, p.apply_url
        FROM posting p JOIN firm f ON f.id = p.firm_id
        WHERE p.status = 'OPEN'
        ORDER BY p.last_seen DESC
    """,
}


def export_xlsx(conn: sqlite3.Connection, out_path: str = "job_tracker.xlsx") -> str:
    import pandas as pd

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet, query in _SHEETS.items():
            df = pd.read_sql_query(query, conn)
            df.to_excel(writer, sheet_name=sheet, index=False)
    return out_path
