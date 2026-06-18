"""The gembets poll loop: fetch odds (+ stats) -> run both detectors -> alert the
new gems -> repeat. Mirrors boostmatcher.monitor.

The core `tick()` takes its odds/stats fetchers as arguments, so it runs against
fakes in a test with no network and against the live APIs in production.

Dedup: a gem is alerted the first time it's seen; re-alerted only if its EV
climbs materially (so a drifting price doesn't spam you). State is the in-memory
`seen` dict keyed by GemBet.key(), same pattern as the boost matcher.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from . import arb, ledger
from . import goals as goals_mod
from . import notify, outlier, staking, statedge, steam
from . import totals as totals_mod
from .config import Config, load
from .models import GemBet, MarketSnapshot
from .odds import consensus_fair_prob
from .statedge import CardsMatchup, FoulMatchup

log = logging.getLogger(__name__)

OddsFetcher = Callable[[], Awaitable[list[MarketSnapshot]]]
StatsFetcher = Callable[[], Awaitable[tuple[list[FoulMatchup], list[CardsMatchup]]]]

_REALERT_DELTA = 0.02       # only re-alert if EV improves by >= 2 percentage points


def _format(g: GemBet, stake: float) -> tuple[str, str]:
    """ntfy (title, body) for one gem — fixture, market, book, odds, prob, stake, reason."""
    title = f"💎 +{g.edge_pct:.1f}% {g.fixture}"
    stake_line = f"Stake £{stake:.2f}\n" if stake > 0 else ""
    body = (f"{g.market}\n"
            f"Book: {g.book} @ {g.decimal_odds:.2f}\n"
            f"Implied {g.implied_prob*100:.1f}%  |  Fair {g.fair_prob*100:.1f}%  "
            f"|  Edge +{g.edge_pct:.1f}%\n"
            f"{stake_line}➤ {g.reason}")
    return title, body


def _stake_for(g: GemBet, cfg: Config) -> float:
    """Kelly stake for a value gem (arbs are multi-leg — sized in their reason, not here)."""
    if g.kind == "arb":
        return 0.0
    return staking.kelly_stake(g.fair_prob, g.decimal_odds, cfg.bankroll,
                               fraction=cfg.kelly_fraction, max_fraction=cfg.max_fraction,
                               max_stake=cfg.max_stake).stake


async def _alert_and_record(gems: list[GemBet], seen: dict[str, float], cfg: Config,
                            conn, weights: dict[str, float]) -> int:
    """Push new/improved gems with a Kelly stake; log each to the ledger. CLV-weighted."""
    fired = 0
    for g in sorted(gems, key=lambda x: x.edge, reverse=True):
        # Auto-mute a detector that isn't beating the close over a real sample.
        if g.kind in weights and weights[g.kind] < cfg.clv_cutoff:
            continue
        key = g.key()
        if key in seen and g.edge <= seen[key] + _REALERT_DELTA:
            continue
        stake = _stake_for(g, cfg)
        if g.kind != "arb" and stake <= 0:
            continue            # Kelly says it's not a real +EV bet -> don't alert/log
        title, body = _format(g, stake)
        await notify.alert(cfg.ntfy_topic, title, body, priority=5 if g.edge_pct >= 8 else 4)
        if conn is not None:
            ledger.record_bet(conn, g, stake)
        log.info("alert %s edge=%.3f kind=%s stake=%.2f", key, g.edge, g.kind, stake)
        seen[key] = g.edge
        fired += 1
    return fired


def _refresh_clv(conn, snaps: list[MarketSnapshot]) -> None:
    """Update each pending snapshot-based bet's closing consensus prob (the CLV input)."""
    if conn is None or not snaps:
        return
    lookup: dict[tuple, float] = {}
    for snap in snaps:
        quotes = snap.quotes_per_book()
        if len(quotes) < 2:
            continue
        for idx, label in enumerate(snap.labels):
            try:
                lookup[(snap.fixture, snap.market, label)] = consensus_fair_prob(quotes, idx)
            except ValueError:
                continue
    for row in ledger.pending_bets(conn):
        base = row["market"].rsplit(" - ", 1)[0]        # "1X2 - Away" -> "1X2"
        fair = lookup.get((row["fixture"], base, row["selection"]))
        if fair is not None:
            ledger.update_closing(conn, row["key"], fair)


async def tick(cfg: Config, fetch_odds: OddsFetcher, fetch_stats: StatsFetcher | None,
               seen: dict[str, float], *, goals_model: "goals_mod.GoalsModel | None" = None,
               history: "steam.OddsHistory | None" = None,
               totals_model: "totals_mod.TotalsModel | None" = None,
               betfair=None, player_rates: dict | None = None, conn=None) -> list[GemBet]:
    """One full pass. Returns every gem found; stakes + records + alerts the new ones."""
    gems: list[GemBet] = []
    allow = set(cfg.allowed_books) or None

    # Fetch the odds once; every odds-based detector shares the snapshots.
    snaps: list[MarketSnapshot] = []
    try:
        snaps = await fetch_odds()
    except Exception as exc:  # noqa: BLE001 — a dead feed mustn't kill the loop
        log.warning("odds fetch failed: %s", exc)

    # Detector A — consensus outliers (always on).
    gems.extend(outlier.scan_all(snaps, min_lift=cfg.min_lift, min_books=cfg.min_books,
                                 max_odds=cfg.max_odds, allowed_books=allow))

    # Detector F — guaranteed cross-book arbitrage (free, pure odds).
    if cfg.enable_arb:
        gems.extend(arb.scan_arbs(snaps, min_margin=cfg.arb_min_margin))

    # Detector C — goals model (free, if enabled and a model was fitted).
    if cfg.enable_goals and goals_model is not None:
        gems.extend(goals_mod.scan_all(snaps, goals_model, min_edge=cfg.min_edge_goals,
                                       max_odds=cfg.max_odds, allowed_books=allow))

    # Detector D — line-movement / steam (free, needs history across ticks).
    if cfg.enable_steam and history is not None and snaps:
        history.record(snaps)
        gems.extend(steam.detect(history, snaps, move_threshold=cfg.steam_move,
                                 gap_threshold=cfg.steam_gap, max_odds=cfg.max_odds,
                                 allowed_books=allow))

    # Detector E — team-totals (cards/corners/...) vs free Betfair Exchange odds.
    if cfg.enable_totals and totals_model is not None and betfair is not None:
        try:
            quotes = await betfair.list_total_markets(
                market_types=cfg.betfair_market_types or None,
                hours_ahead=cfg.betfair_hours_ahead)
            gems.extend(totals_mod.scan_quotes(totals_model, quotes,
                                               min_edge=cfg.min_edge_goals, max_odds=cfg.max_odds))
        except Exception as exc:  # noqa: BLE001
            log.warning("totals/betfair fetch failed: %s", exc)

    # Detector B (FREE) — player fouls vs Betfair PLAYER_FOULS market.
    if cfg.enable_player_fouls and player_rates and betfair is not None:
        try:
            from . import player_fouls
            pquotes = await betfair.list_player_foul_markets(hours_ahead=cfg.betfair_hours_ahead)
            gems.extend(player_fouls.scan_player_fouls(
                pquotes, player_rates, min_edge=cfg.min_edge_statedge, max_odds=cfg.max_odds))
        except Exception as exc:  # noqa: BLE001
            log.warning("player-fouls/betfair fetch failed: %s", exc)

    # Detector B (legacy paid) — statistical mispricing via stats fetcher.
    if cfg.enable_statedge and fetch_stats is not None:
        try:
            fouls, cards = await fetch_stats()
            for m in fouls:
                if (g := statedge.foul_edge(m, min_edge=cfg.min_edge_statedge)):
                    gems.append(g)
            for m in cards:
                if (g := statedge.cards_edge(m, min_edge=cfg.min_edge_statedge)):
                    gems.append(g)
        except Exception as exc:  # noqa: BLE001
            log.warning("stats fetch/scan failed: %s", exc)

    # Refresh CLV on pending bets, then alert+stake+record the new gems, auto-muting
    # any detector whose flags haven't beaten the close over a real sample.
    _refresh_clv(conn, snaps)
    weights = ledger.clv_by_kind(conn, min_n=cfg.min_clv_sample) if conn is not None else {}
    await _alert_and_record(gems, seen, cfg, conn, weights)
    return gems


def _build_fetchers(cfg: Config) -> tuple[OddsFetcher, StatsFetcher | None]:
    """Bind the configured sources into zero-arg async fetchers."""
    from .sources import make_odds_fetcher
    fetch_odds = make_odds_fetcher(cfg)          # api-primary, scrape-fallback router

    fetch_stats: StatsFetcher | None = None
    if cfg.enable_statedge:
        from .stats_api import PROVIDERS as STATS
        fetch_stats_fn = STATS[cfg.stats_provider]

        async def fetch_stats() -> tuple[list[FoulMatchup], list[CardsMatchup]]:
            return await fetch_stats_fn(cfg.sport_key)

    return fetch_odds, fetch_stats


async def run(config_path: str) -> None:
    """Forever loop: tick every cfg.poll_interval seconds."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # don't log URLs (they carry the API key)
    cfg = load(config_path)
    fetch_odds, fetch_stats = _build_fetchers(cfg)
    seen: dict[str, float] = {}
    conn = ledger.connect(cfg.ledger_path)       # CLV + P&L log

    # Detector C: fit the goals model once at startup (re-fit periodically if you
    # run for weeks). Detector D: history persists across ticks for movement.
    goals_model = None
    if cfg.enable_goals and cfg.goals_csv_url:
        try:
            goals_model = await goals_mod.load_footballdata(cfg.goals_csv_url)
        except Exception as exc:  # noqa: BLE001
            log.error("goals model fit failed (%s) — Detector C disabled", exc)
    history = steam.OddsHistory(window=cfg.steam_window) if cfg.enable_steam else None

    # A shared Betfair Exchange client feeds Detector E (totals) and the free
    # Detector B (player fouls) — build it once if either is on.
    betfair = None
    if cfg.enable_totals or cfg.enable_player_fouls:
        from .betfair_odds import BetfairOdds
        betfair = BetfairOdds()
        if not betfair.ready:
            log.error("Betfair: APP_KEY/SESSION_TOKEN missing — Detectors B(free)/E disabled")
            betfair = None

    # Detector E: fit the team-totals model from the free results CSV.
    totals_model = None
    if cfg.enable_totals and cfg.totals_csv_url and betfair is not None:
        try:
            totals_model = totals_mod.build(await totals_mod.fetch_matches(cfg.totals_csv_url))
        except Exception as exc:  # noqa: BLE001
            log.error("totals model fit failed (%s) — Detector E disabled", exc)

    # Detector B (free): load the per-90 player foul rates.
    player_rates = None
    if cfg.enable_player_fouls and cfg.player_rates_path and betfair is not None:
        try:
            from . import player_fouls
            player_rates = player_fouls.load_player_rates(cfg.player_rates_path)
        except Exception as exc:  # noqa: BLE001
            log.error("player rates load failed (%s) — Detector B(free) disabled", exc)

    log.info("monitor start: source=%s sport=%s detectors=A%s%s%s%s%s",
             cfg.odds_source, cfg.sport_key,
             "+B(free)" if player_rates else ("+B" if cfg.enable_statedge else ""),
             "+C" if goals_model else "", "+D" if history is not None else "",
             "+E" if totals_model else "", "")
    while True:
        try:
            gems = await tick(cfg, fetch_odds, fetch_stats, seen,
                              goals_model=goals_model, history=history,
                              totals_model=totals_model, betfair=betfair,
                              player_rates=player_rates, conn=conn)
            log.info("tick: %d gem(s) live", len(gems))
        except Exception as exc:  # noqa: BLE001 — never let a tick kill the loop
            log.error("tick failed: %s", exc)
        await asyncio.sleep(cfg.poll_interval)
