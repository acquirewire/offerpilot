"""Bet ledger: CLV (closing-line value) + P&L, in SQLite.

Two things you manage by measuring:

  * CLV — did the price you flagged beat the CLOSING price? Measured as the EV of
    your odds at the closing consensus probability: clv = your_odds * close_prob - 1.
    Positive CLV over many bets is the ONLY real proof an edge exists — it needs no
    match result, just the closing line, so the monitor captures it automatically.
  * P&L — actual profit once a bet settles (win/loss), per detector, with ROI and
    hit rate, so you see where the money really comes from and kill what doesn't.

Every alerted gem is recorded once (keyed by GemBet.key()). The monitor refreshes
`closing_fair_prob` each tick from the live consensus, so the last value before
kickoff is the close. Settle outcomes with `gembets settle`; read it with
`gembets report`. Pure stdlib (sqlite3).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import GemBet

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    key TEXT PRIMARY KEY,
    ts TEXT, kind TEXT, fixture TEXT, market TEXT, selection TEXT, book TEXT,
    odds REAL, fair_prob REAL, edge REAL, stake REAL, kickoff TEXT,
    closing_fair_prob REAL, clv_pct REAL,
    result TEXT, pnl REAL, settled INTEGER DEFAULT 0
);
"""


def connect(path: str = "gembets_ledger.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def record_bet(conn: sqlite3.Connection, gem: GemBet, stake: float) -> bool:
    """Insert a newly-alerted gem (no-op if its key already exists). True if new."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO bets (key, ts, kind, fixture, market, selection, book, "
        "odds, fair_prob, edge, stake, kickoff) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (gem.key(), datetime.now(timezone.utc).isoformat(), gem.kind, gem.fixture,
         gem.market, gem.selection, gem.book, gem.decimal_odds, gem.fair_prob,
         gem.edge, stake, gem.kickoff))
    conn.commit()
    return cur.rowcount > 0


def update_closing(conn: sqlite3.Connection, key: str, closing_fair_prob: float) -> None:
    """Refresh a bet's closing consensus prob + CLV (call each tick pre-kickoff)."""
    row = conn.execute("SELECT odds FROM bets WHERE key=? AND settled=0", (key,)).fetchone()
    if not row:
        return
    clv = row["odds"] * closing_fair_prob - 1.0
    conn.execute("UPDATE bets SET closing_fair_prob=?, clv_pct=? WHERE key=?",
                 (closing_fair_prob, clv, key))
    conn.commit()


def settle(conn: sqlite3.Connection, key: str, result: str) -> float | None:
    """Settle a bet: result in {'win','loss','void'}. Returns the P&L, or None."""
    row = conn.execute("SELECT odds, stake FROM bets WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if result == "win":
        pnl = row["stake"] * (row["odds"] - 1.0)
    elif result == "loss":
        pnl = -row["stake"]
    else:
        pnl = 0.0
    conn.execute("UPDATE bets SET result=?, pnl=?, settled=1 WHERE key=?", (result, pnl, key))
    conn.commit()
    return pnl


def pending_keys(conn: sqlite3.Connection) -> list[str]:
    return [r["key"] for r in conn.execute("SELECT key FROM bets WHERE settled=0")]


def pending_bets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Unsettled bets (key, fixture, market, selection) — for CLV refresh."""
    return conn.execute(
        "SELECT key, fixture, market, selection FROM bets WHERE settled=0").fetchall()


@dataclass
class KindStats:
    kind: str
    bets: int
    avg_edge: float
    avg_clv: float | None      # mean CLV% over bets with a closing price
    clv_n: int
    settled: int
    wins: int
    pnl: float
    staked: float

    @property
    def roi(self) -> float | None:
        return (self.pnl / self.staked) if self.staked > 0 else None

    @property
    def hit_rate(self) -> float | None:
        return (self.wins / self.settled) if self.settled else None


def report(conn: sqlite3.Connection) -> list[KindStats]:
    """Per-detector summary: edge, CLV, settled P&L, ROI, hit rate."""
    out: list[KindStats] = []
    kinds = [r["kind"] for r in conn.execute("SELECT DISTINCT kind FROM bets")]
    for kind in kinds:
        rows = conn.execute("SELECT * FROM bets WHERE kind=?", (kind,)).fetchall()
        clv = [r["clv_pct"] for r in rows if r["clv_pct"] is not None]
        settled = [r for r in rows if r["settled"]]
        out.append(KindStats(
            kind=kind, bets=len(rows),
            avg_edge=sum(r["edge"] for r in rows) / len(rows),
            avg_clv=(sum(clv) / len(clv)) if clv else None, clv_n=len(clv),
            settled=len(settled), wins=sum(1 for r in settled if r["result"] == "win"),
            pnl=sum(r["pnl"] or 0.0 for r in settled),
            staked=sum(r["stake"] or 0.0 for r in settled)))
    return out


def clv_by_kind(conn: sqlite3.Connection, *, min_n: int = 20) -> dict[str, float]:
    """Mean CLV% per detector, only for kinds with >= min_n priced bets.

    The monitor uses this to AUTO-WEIGHT detectors: a kind whose flags don't beat
    the close over a real sample is noise and gets its threshold raised.
    """
    out: dict[str, float] = {}
    for s in report(conn):
        if s.avg_clv is not None and s.clv_n >= min_n:
            out[s.kind] = s.avg_clv
    return out
