"""Loads config.yaml + .env into typed objects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FetchConfig:
    method: str = "http"          # "http" | "browser"


@dataclass
class Target:
    name: str
    site: str                     # "fatsoma" | "milkshake" | "generic"
    url: str
    checkout_url: str
    interval: int = 45
    fetch: FetchConfig = field(default_factory=FetchConfig)


@dataclass
class DiscoveryTarget:
    """Watch a promoter's events and alert on NEW ones whose title contains all
    of `match` (case-insensitive).

    source = "api"    -> query Fatsoma's JSON API for one promoter page (needs
                         page_id); complete + reliable. Preferred for a single
                         promoter.
    source = "search" -> keyword-search all events (needs query); use for a
                         venue whose events come from many promoters.
    source = "html"   -> scrape a listing page (needs url); partial fallback.
    """

    name: str
    match: list[str]
    source: str = "api"
    page_id: str = ""
    query: str = ""
    url: str = ""
    interval: int = 120
    fetch: FetchConfig = field(default_factory=FetchConfig)


@dataclass
class Settings:
    targets: list[Target]
    discovery: list[DiscoveryTarget] = field(default_factory=list)

    # secrets pulled from the environment
    twilio_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from: str = os.getenv("TWILIO_FROM_NUMBER", "")
    sms_to: list[str] = field(
        default_factory=lambda: _split(os.getenv("ALERT_SMS_TO", ""))
    )

    email_backend: str = os.getenv("EMAIL_BACKEND", "smtp")
    email_to: list[str] = field(
        default_factory=lambda: _split(os.getenv("ALERT_EMAIL_TO", ""))
    )
    email_from: str = os.getenv("ALERT_EMAIL_FROM", "")
    sendgrid_key: str = os.getenv("SENDGRID_API_KEY", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587") or "587")
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    ntfy_server: str = os.getenv("NTFY_SERVER", "https://ntfy.sh")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "")

    proxies: list[str] = field(
        default_factory=lambda: _split(os.getenv("PROXIES", ""))
    )


def _split(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def load(config_path: str | Path = ROOT / "config.yaml") -> Settings:
    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    defaults = data.get("defaults", {}) or {}
    default_interval = int(defaults.get("interval", 45))

    targets: list[Target] = []
    for t in data.get("targets", []):
        fetch = FetchConfig(**(t.get("fetch") or {}))
        targets.append(
            Target(
                name=t["name"],
                site=t["site"],
                url=t["url"],
                checkout_url=t.get("checkout_url", t["url"]),
                interval=int(t.get("interval", default_interval)),
                fetch=fetch,
            )
        )
    discovery: list[DiscoveryTarget] = []
    for d in data.get("discovery", []) or []:
        fetch = FetchConfig(**(d.get("fetch") or {}))
        dt = DiscoveryTarget(
            name=d["name"],
            match=[str(m).lower() for m in (d.get("match") or [])],
            source=d.get("source", "api"),
            page_id=d.get("page_id", ""),
            query=d.get("query", ""),
            url=d.get("url", ""),
            interval=int(d.get("interval", 120)),
            fetch=fetch,
        )
        if dt.source == "api" and not dt.page_id:
            raise ValueError(f"discovery '{dt.name}': source=api needs page_id")
        if dt.source == "search" and not dt.query:
            raise ValueError(f"discovery '{dt.name}': source=search needs query")
        if dt.source == "html" and not dt.url:
            raise ValueError(f"discovery '{dt.name}': source=html needs url")
        discovery.append(dt)

    if not targets and not discovery:
        raise ValueError("config.yaml defines no targets or discovery watchers")
    return Settings(targets=targets, discovery=discovery)
