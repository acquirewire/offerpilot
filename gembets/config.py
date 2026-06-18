"""Config loader (YAML), mirroring boostmatcher.config / jobtracker.config.

One file drives: which sport key + markets + leagues to pull, the two edge
thresholds, the consensus quorum, the poll cadence, and the ntfy topic. API keys
live in .env (never the YAML), read by the api layers from the environment.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Config:
    # --- odds feed ---
    # odds_source: "api" (The Odds API), "scrape" (oddschecker), or "both"
    # (api primary, scrape fallback when free credits run low). Default free-friendly.
    odds_source: str = "both"
    odds_provider: str = "theoddsapi"        # key into odds_api.PROVIDERS
    sport_key: str = "soccer_epl"            # provider's league/competition id
    # Free-tier defaults: 1 region + 2 markets keeps each call to ~2 credits.
    markets: list[str] = field(default_factory=lambda: ["1X2", "Over/Under 2.5"])
    regions: list[str] = field(default_factory=lambda: ["uk"])

    # The Odds API free tier is 500 credits/MONTH (cost = markets x regions per
    # call). The router self-throttles to stay under budget and stops hitting the
    # API when remaining <= credit_floor, falling back to scraping if enabled.
    monthly_credits: int = 500
    credit_floor: int = 25

    # --- scrape fallback (free, unlimited, but needs live selector calibration) ---
    scrape_scraper: str = "oddschecker"
    scrape_urls: list[str] = field(default_factory=list)   # oddschecker match "winner" pages

    # --- Detector C: goals model (FREE, model-based) ---
    enable_goals: bool = False               # needs a results CSV to fit the model
    goals_csv_url: str = ""                  # football-data.co.uk league CSV
    min_edge_goals: float = 0.05             # +5% EV vs the model to flag

    # --- Detector D: line-movement / steam (FREE, time-series) ---
    enable_steam: bool = False
    steam_move: float = 0.03                 # sharp implied prob must rise >= this
    steam_gap: float = 0.05                  # soft must imply >= this much less than sharp
    steam_window: int = 1800                 # seconds of history to measure movement over

    # --- Detector E: team-totals model + free Betfair Exchange odds ---
    enable_totals: bool = False              # needs totals_csv_url + Betfair creds (env)
    totals_csv_url: str = ""                 # football-data.co.uk CSV to fit the model
    betfair_market_types: list[str] = field(default_factory=list)  # [] = sensible defaults
    betfair_hours_ahead: int = 48            # how far ahead to pull Betfair markets

    # --- Detector B (FREE): player fouls via Betfair PLAYER_FOULS + free stats ---
    enable_player_fouls: bool = False        # needs player_rates_path + Betfair creds
    player_rates_path: str = ""              # JSON of per-90 player foul rates

    # --- stats feed (legacy Detector B via paid Sportmonks/props odds) ---
    stats_provider: str = "sportmonks"       # key into stats_api.PROVIDERS
    enable_statedge: bool = False            # leave off on the free plan

    # --- thresholds (Detector A) ---
    min_lift: float = 0.33                   # flag only if book odds are >= this fraction
                                             # above the typical price (0.33 = 4.0 vs 3.0)
    max_odds: float = 5.0                    # cap: ignore longshots priced above this
    min_books: int = 4                       # need >= this many books for a typical price
    allowed_books: list[str] = field(default_factory=list)  # only flag these books ([]=all)
    # --- threshold (Detector B) ---
    min_edge_statedge: float = 0.06          # +6% EV to flag a model edge (noisier)

    # --- staking (Kelly) ---
    bankroll: float = 500.0                  # your betting bank (£)
    kelly_fraction: float = 0.25             # quarter-Kelly (conservative)
    max_fraction: float = 0.05               # never stake > 5% of bankroll on one bet
    max_stake: float | None = None           # optional hard £ cap per bet

    # --- ledger / CLV / P&L ---
    ledger_path: str = "gembets_ledger.db"   # SQLite bet log
    clv_cutoff: float = -0.01                # mute a detector if its avg CLV < this...
    min_clv_sample: int = 30                 # ...once it has >= this many priced bets

    # --- arbitrage (Detector F) ---
    enable_arb: bool = True                  # flag guaranteed cross-book arbs (free)
    arb_min_margin: float = 0.005            # require >= 0.5% locked margin

    # --- loop ---
    poll_interval: int = 1800                # 30 min default: free-tier-safe cadence
    ntfy_topic: str | None = None


def load(path: str) -> Config:
    import yaml
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Config(
        odds_source=raw.get("odds_source", "both"),
        odds_provider=raw.get("odds_provider", "theoddsapi"),
        sport_key=raw.get("sport_key", "soccer_epl"),
        markets=list(raw.get("markets", ["1X2", "Over/Under 2.5"])),
        regions=list(raw.get("regions", ["uk"])),
        monthly_credits=int(raw.get("monthly_credits", 500)),
        credit_floor=int(raw.get("credit_floor", 25)),
        scrape_scraper=raw.get("scrape_scraper", "oddschecker"),
        scrape_urls=list(raw.get("scrape_urls", [])),
        stats_provider=raw.get("stats_provider", "sportmonks"),
        enable_statedge=bool(raw.get("enable_statedge", False)),
        min_lift=float(raw.get("min_lift", 0.33)),
        max_odds=float(raw.get("max_odds", 5.0)),
        min_books=int(raw.get("min_books", 4)),
        allowed_books=list(raw.get("allowed_books", [])),
        enable_goals=bool(raw.get("enable_goals", False)),
        goals_csv_url=raw.get("goals_csv_url", ""),
        min_edge_goals=float(raw.get("min_edge_goals", 0.05)),
        enable_steam=bool(raw.get("enable_steam", False)),
        steam_move=float(raw.get("steam_move", 0.03)),
        steam_gap=float(raw.get("steam_gap", 0.05)),
        steam_window=int(raw.get("steam_window", 1800)),
        enable_totals=bool(raw.get("enable_totals", False)),
        totals_csv_url=raw.get("totals_csv_url", ""),
        betfair_market_types=list(raw.get("betfair_market_types", [])),
        betfair_hours_ahead=int(raw.get("betfair_hours_ahead", 48)),
        enable_player_fouls=bool(raw.get("enable_player_fouls", False)),
        player_rates_path=raw.get("player_rates_path", ""),
        bankroll=float(raw.get("bankroll", 500.0)),
        kelly_fraction=float(raw.get("kelly_fraction", 0.25)),
        max_fraction=float(raw.get("max_fraction", 0.05)),
        max_stake=(float(raw["max_stake"]) if raw.get("max_stake") is not None else None),
        ledger_path=raw.get("ledger_path", "gembets_ledger.db"),
        clv_cutoff=float(raw.get("clv_cutoff", -0.01)),
        min_clv_sample=int(raw.get("min_clv_sample", 30)),
        enable_arb=bool(raw.get("enable_arb", True)),
        arb_min_margin=float(raw.get("arb_min_margin", 0.005)),
        min_edge_statedge=float(raw.get("min_edge_statedge", 0.06)),
        poll_interval=int(raw.get("poll_interval", 1800)),
        ntfy_topic=raw.get("ntfy_topic"),
    )
