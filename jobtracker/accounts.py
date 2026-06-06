"""User accounts, tiers and admin controls for the OfferPilot app.

A small, dependency-free auth + user store (SQLite + PBKDF2 password hashing).
Tiers: 'free' | 'pro' | 'admin'. Pro and admin unlock all features; admin also
sees the admin panel (list signups, flip anyone to Pro for free).

The admin account is seeded from ADMIN_EMAIL / ADMIN_PASSWORD in .env.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("ACCOUNTS_DB", "accounts.db")
TIERS = ("free", "pro", "admin")
FREE_MONTHLY_LIMIT = 3   # tailored CVs/month on the free tier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                pw_hash TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free',
                created_at TEXT NOT NULL,
                stripe_customer TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS usage(
                email TEXT NOT NULL,
                month TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(email, month)
            )""")
        c.commit()


# --- password hashing (stdlib PBKDF2) ---------------------------------------

def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"{salt.hex()}${dk.hex()}"


def _verify(pw: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# --- user operations ---------------------------------------------------------

def _row_to_user(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def get_user(email: str) -> dict | None:
    with connect() as c:
        return _row_to_user(
            c.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone())


def create_user(email: str, password: str, tier: str = "free") -> tuple[bool, str]:
    email = email.lower().strip()
    if "@" not in email or "." not in email:
        return False, "Enter a valid email address."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if get_user(email):
        return False, "An account with that email already exists — try logging in."
    try:
        with connect() as c:
            c.execute("INSERT INTO users(email, pw_hash, tier, created_at) VALUES(?,?,?,?)",
                      (email, hash_password(password), tier, _now()))
            c.commit()
    except sqlite3.IntegrityError:
        # another concurrent run inserted this email first — that's fine
        return False, "An account with that email already exists — try logging in."
    return True, "Account created."


def verify_login(email: str, password: str) -> dict | None:
    u = get_user(email)
    if u and _verify(password, u["pw_hash"]):
        return u
    return None


def set_tier(email: str, tier: str) -> None:
    if tier not in TIERS:
        return
    with connect() as c:
        c.execute("UPDATE users SET tier=? WHERE email=?", (tier, email.lower().strip()))
        c.commit()


def list_users() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT email, tier, created_at FROM users ORDER BY created_at DESC").fetchall()]


def is_pro(user: dict | None) -> bool:
    return bool(user) and user.get("tier") in ("pro", "admin")


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("tier") == "admin"


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage_count(email: str) -> int:
    with connect() as c:
        r = c.execute("SELECT count FROM usage WHERE email=? AND month=?",
                      (email.lower().strip(), _month())).fetchone()
        return r["count"] if r else 0


def record_use(email: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO usage(email, month, count) VALUES(?,?,1) "
                  "ON CONFLICT(email, month) DO UPDATE SET count=count+1",
                  (email.lower().strip(), _month()))
        c.commit()


def can_tailor(user: dict | None) -> bool:
    """Pro/admin: unlimited. Free: up to FREE_MONTHLY_LIMIT tailors this month."""
    if is_pro(user):
        return True
    return bool(user) and usage_count(user["email"]) < FREE_MONTHLY_LIMIT


def remaining_free(user: dict | None) -> int:
    return max(0, FREE_MONTHLY_LIMIT - usage_count(user["email"])) if user else 0


def ensure_admin() -> None:
    """Seed the admin account from env on first run (idempotent)."""
    email = (os.environ.get("ADMIN_EMAIL") or "").lower().strip()
    pw = os.environ.get("ADMIN_PASSWORD")
    if not (email and pw):
        return
    if get_user(email) is None:
        create_user(email, pw, tier="admin")   # race-safe (won't raise)
    u = get_user(email)
    if u and u["tier"] != "admin":
        set_tier(email, "admin")
