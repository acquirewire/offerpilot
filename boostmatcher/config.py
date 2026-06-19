"""Config loader for the boost matcher (YAML), mirroring jobtracker.config.

One file drives: which bookie boost pages to scrape, exchange commissions, the
default back stake, and the rating threshold above which a boost is alerted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass
class BookieTarget:
    name: str                   # "skybet"
    url: str                    # boost-page URL to scrape
    scraper: str                # key into scrapers.SCRAPERS
    enabled: bool = True


@dataclass
class ExchangeCfg:
    name: str                   # "betfair" | "smarkets"
    commission: float           # default commission rate
    enabled: bool = True


@dataclass
class Config:
    bookies: list[BookieTarget]
    exchanges: list[ExchangeCfg]
    back_stake: float = 25.0            # default stake the rater prices each boost at
    alert_rating: float = 2.0           # only alert boosts rating >= this (% of stake)
    poll_interval: int = 120            # seconds between boost-page polls
    ntfy_topic: str | None = None


def load(path: str) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    bookies = [BookieTarget(**b) for b in raw.get("bookies", [])]
    exchanges = [ExchangeCfg(**e) for e in raw.get("exchanges", [])]
    return Config(
        bookies=bookies,
        exchanges=exchanges,
        back_stake=float(raw.get("back_stake", 25.0)),
        alert_rating=float(raw.get("alert_rating", 2.0)),
        poll_interval=int(raw.get("poll_interval", 120)),
        ntfy_topic=raw.get("ntfy_topic"),
    )
