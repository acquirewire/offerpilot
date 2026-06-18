"""Detector B (FREE version): player-fouls mispricing.

Your original gem — a foul-heavy fullback (or a foul-drawing winger) whose
Betfair player-fouls line doesn't match his real rate — but built entirely free:
  * ODDS  : Betfair's PLAYER_FOULS market (free; `betfair_odds.list_player_foul_markets`).
  * STATS : per-90 player foul rates from a free source (FBref export / API-Football
            free tier), loaded via `load_player_rates`.

Model (reuses the Poisson in odds.py): a player's expected fouls in this match is
his fouls/90 scaled to expected minutes, optionally LIFTED by the opponent he's
matched against (a fullback who fouls 2.8/90 facing a winger who draws 2.5/90 is
pushed above his baseline — the matchup edge). Then P(over the line) vs the
offered price gives the EV.

Two seams you calibrate once: the Betfair player-market JSON shape (confirm with
`gembets betfair-probe`) and the player-rate source (drop the numbers into a JSON;
FBref's "Miscellaneous Stats" table has Fls/Fld per 90 for free). The maths and
the scan are unit-tested.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .goals import normalise
from .models import GemBet
from .odds import evaluate_value, prob_over_line


@dataclass(frozen=True)
class PlayerFoulQuote:
    """A Betfair player-fouls over/under price."""

    fixture: str
    player: str
    line: float                       # e.g. 1.5 fouls
    over_decimal: float | None = None
    under_decimal: float | None = None
    source: str = "betfair"


@dataclass(frozen=True)
class PlayerFoulRate:
    """A player's free per-90 foul rate, with an optional matchup lift."""

    fouls_p90: float                  # fouls committed per 90 (the market's metric)
    opp_draw_p90: float | None = None  # opponent's fouls-drawn /90 -> matchup lift
    minutes_expected: float = 85.0


def expected_fouls(rate: PlayerFoulRate, *, own_weight: float = 0.7) -> float:
    """Expected fouls this match: own rate, optionally blended with the matchup."""
    if rate.opp_draw_p90 is None:
        base = rate.fouls_p90
    else:
        base = own_weight * rate.fouls_p90 + (1.0 - own_weight) * rate.opp_draw_p90
    return base * rate.minutes_expected / 90.0


def scan_player_fouls(quotes: list[PlayerFoulQuote], rates: dict[str, PlayerFoulRate], *,
                      min_edge: float = 0.06, max_odds: float = 5.0) -> list[GemBet]:
    """Flag player-fouls lines the model thinks are mispriced. `rates` keyed by name."""
    gems: list[GemBet] = []
    for q in quotes:
        rate = rates.get(normalise(q.player))
        if rate is None:
            continue
        expected = expected_fouls(rate)
        p_over = prob_over_line(expected, q.line)
        for side, offered, prob in (("Over", q.over_decimal, p_over),
                                    ("Under", q.under_decimal, 1.0 - p_over)):
            if not offered or offered > max_odds:
                continue
            sig = evaluate_value(offered, prob, min_edge=min_edge)
            if not sig.has_edge:
                continue
            lift = "" if rate.opp_draw_p90 is None else f", matchup vs {rate.opp_draw_p90:.1f}/90 drawn"
            gems.append(GemBet(
                fixture=q.fixture,
                market=f"{q.player} {side} {q.line} Fouls",
                selection=f"{side} {q.line}",
                book=q.source,
                decimal_odds=offered,
                implied_prob=sig.offered_prob,
                fair_prob=prob,
                edge=sig.edge,
                kind="player_fouls",
                reason=(f"{q.player} fouls {rate.fouls_p90:.1f}/90{lift}: model expects "
                        f"{expected:.2f}, {side} {q.line} fair {prob*100:.0f}% but "
                        f"{q.source} pays {offered:.2f} ({sig.offered_prob*100:.0f}%) "
                        f"-> +{sig.edge*100:.0f}% EV"),
                notes=[f"expected {expected:.2f} fouls"],
            ))
    return sorted(gems, key=lambda g: g.edge, reverse=True)


def load_player_rates(path: str) -> dict[str, PlayerFoulRate]:
    """Load free per-90 rates from JSON: {players:[{name, fouls_p90, opp_draw_p90?,
    minutes_expected?}]}. Populate from FBref's Miscellaneous Stats (Fls/Fld per 90).
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, PlayerFoulRate] = {}
    for p in raw.get("players", []):
        out[normalise(p["name"])] = PlayerFoulRate(
            fouls_p90=float(p["fouls_p90"]),
            opp_draw_p90=(float(p["opp_draw_p90"]) if p.get("opp_draw_p90") is not None else None),
            minutes_expected=float(p.get("minutes_expected", 85.0)))
    return out
