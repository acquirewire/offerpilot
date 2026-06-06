"""Config loading for the Drop Tracker (Module 1).

A firm entry says where to look and how to parse it; the global `filter` block
defines what counts as relevant (keywords / regions / the languages YOU speak).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .models import RelevanceFilter


@dataclass
class FirmTarget:
    name: str
    slug: str
    ats: str                      # "greenhouse" | "workday"
    url: str                      # JSON endpoint to poll
    method: str = "POST"          # Workday list endpoints are POST; Greenhouse GET
    body: dict | None = None      # POST payload for Workday search
    host: str = ""                # base host for building apply URLs
    scope_selector: str | None = None
    max_apps: int = 3
    interval: int = 300


@dataclass
class Config:
    firms: list[FirmTarget] = field(default_factory=list)
    relevance: RelevanceFilter = field(default_factory=RelevanceFilter)
    ntfy_topic: str | None = None
    db_path: str = "jobtracker.db"


def load(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    defaults = raw.get("defaults", {})
    firms = [
        FirmTarget(
            name=f["name"],
            slug=f["slug"],
            ats=f["ats"],
            url=f["url"],
            method=f.get("method", "GET" if f["ats"] == "greenhouse" else "POST"),
            body=f.get("body"),
            host=f.get("host", ""),
            scope_selector=f.get("scope_selector"),
            max_apps=f.get("max_apps", defaults.get("max_apps", 3)),
            interval=f.get("interval", defaults.get("interval", 300)),
        )
        for f in raw.get("firms", [])
    ]

    return Config(
        firms=firms,
        relevance=RelevanceFilter.from_config(raw.get("filter", {})),
        ntfy_topic=raw.get("ntfy_topic"),
        db_path=raw.get("db_path", "jobtracker.db"),
    )
