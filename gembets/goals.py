"""Detector C: a goals model — the free, model-based gem.

Detector A only knows what the market says. This builds an INDEPENDENT view of a
match from team scoring strength and flags where the market's goals-related
prices (1X2, Over/Under 2.5, BTTS) disagree with the model. That's a "gem" in the
statistical sense — like the foul/card edges, but on the markets the FREE odds
feed actually carries, using FREE results data.

The model (pure stdlib, reuses the Poisson in odds.py):

  * Fit attack/defence ratings from recent results (ratio method — no solver):
        attack_t  = (goals scored per game by t)   / league average
        defence_t = (goals conceded per game by t) / league average
  * Expected goals for a fixture:
        lambda_home = league_home_avg * attack_home * defence_away
        lambda_away = league_away_avg * attack_away * defence_home
  * Turn (lambda_home, lambda_away) into a Poisson score grid and read off
        P(home/draw/away), P(over 2.5), P(BTTS).
  * Compare each model prob to the offered price -> EV -> flag.

Best for DOMESTIC LEAGUES with a decent match history (the free results source
covers the European leagues). Weak for short international tournaments — too few
games to rate teams. Team-name matching between the odds feed and the results
source is the real seam: `normalise` + an alias map handle the common cases;
tune per league if a fixture isn't matching.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass

from .models import GemBet, MarketSnapshot
from .odds import decimal_to_implied, evaluate_value, poisson_pmf

log = logging.getLogger(__name__)


# --------------------------------------------------------------- name matching

_SUFFIXES = (" fc", " afc", " cf", " sc", " ac", " calcio")
_ALIASES = {
    "man city": "manchester city", "man utd": "manchester united",
    "man united": "manchester united", "spurs": "tottenham",
    "wolves": "wolverhampton", "nott'm forest": "nottingham forest",
    "sheffield utd": "sheffield united", "west brom": "west bromwich",
    "paris sg": "paris saint germain", "psg": "paris saint germain",
    "inter": "internazionale", "bayern": "bayern munich",
}


def normalise(name: str) -> str:
    """Lower-case, strip club suffixes/punctuation, apply aliases — for matching."""
    s = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return _ALIASES.get(s, s)


# ------------------------------------------------------------------ the model

@dataclass(frozen=True)
class TeamRating:
    attack: float        # >1 scores more than average
    defence: float       # >1 concedes more than average
    games: int


@dataclass
class GoalsModel:
    ratings: dict[str, TeamRating]      # keyed by normalised name
    home_avg: float                     # league average home goals/game
    away_avg: float                     # league average away goals/game

    def expected_goals(self, home: str, away: str) -> tuple[float, float] | None:
        h = self.ratings.get(normalise(home))
        a = self.ratings.get(normalise(away))
        if not h or not a:
            return None
        return (self.home_avg * h.attack * a.defence,
                self.away_avg * a.attack * h.defence)


def fit(results: list[tuple[str, str, int, int]], *, min_games: int = 3) -> GoalsModel:
    """Fit a GoalsModel from (home, away, home_goals, away_goals) rows."""
    n = len(results)
    if n == 0:
        raise ValueError("no results to fit")
    home_avg = sum(hg for _, _, hg, _ in results) / n
    away_avg = sum(ag for _, _, _, ag in results) / n
    overall = (home_avg + away_avg) / 2 or 1.0

    scored: dict[str, int] = {}
    conceded: dict[str, int] = {}
    games: dict[str, int] = {}
    for home, away, hg, ag in results:
        for team, gf, ga in ((normalise(home), hg, ag), (normalise(away), ag, hg)):
            scored[team] = scored.get(team, 0) + gf
            conceded[team] = conceded.get(team, 0) + ga
            games[team] = games.get(team, 0) + 1

    ratings: dict[str, TeamRating] = {}
    for team, g in games.items():
        if g < min_games:           # too few games to rate reliably
            continue
        ratings[team] = TeamRating(
            attack=(scored[team] / g) / overall,
            defence=(conceded[team] / g) / overall,
            games=g)
    return GoalsModel(ratings=ratings, home_avg=home_avg, away_avg=away_avg)


def market_probs(lambda_home: float, lambda_away: float, *, max_goals: int = 10) -> dict:
    """Model probabilities for 1X2, Over/Under 2.5 and BTTS from the score grid."""
    ph = [poisson_pmf(i, lambda_home) for i in range(max_goals + 1)]
    pa = [poisson_pmf(j, lambda_away) for j in range(max_goals + 1)]
    home = draw = away = over = btts = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = ph[i] * pa[j]
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
            if i + j >= 3:
                over += p
            if i >= 1 and j >= 1:
                btts += p
    return {
        "1X2": (home, draw, away),
        "Over/Under 2.5": (over, 1.0 - over),
        "BTTS": (btts, 1.0 - btts),
    }


# ------------------------------------------------------------------ detection

def scan_snapshot(snap: MarketSnapshot, model: GoalsModel, *, min_edge: float = 0.05,
                  max_odds: float = 5.0, allowed_books: set[str] | None = None) -> list[GemBet]:
    """Flag book prices that beat the model's probability by >= min_edge EV."""
    if snap.market not in ("1X2", "Over/Under 2.5", "BTTS"):
        return []
    home, _, away = (snap.fixture.partition(" vs "))
    lam = model.expected_goals(home, away)
    if lam is None:                 # no ratings for one of the teams -> can't model
        return []
    probs = market_probs(*lam).get(snap.market)
    if not probs or len(probs) != len(snap.labels):
        return []

    allow = {b.lower() for b in allowed_books} if allowed_books else None
    quotes = snap.quotes_per_book()
    gems: list[GemBet] = []
    for idx, label in enumerate(snap.labels):
        model_prob = probs[idx]
        for book, decimals in quotes.items():
            if len(decimals) <= idx:
                continue
            if (allow is not None and book.lower() not in allow):
                continue
            offered = decimals[idx]
            if offered > max_odds:
                continue
            sig = evaluate_value(offered, model_prob, min_edge=min_edge)
            if not sig.has_edge:
                continue
            gems.append(GemBet(
                fixture=snap.fixture,
                market=f"{snap.market} - {label}",
                selection=label,
                book=book,
                decimal_odds=offered,
                implied_prob=decimal_to_implied(offered),
                fair_prob=model_prob,
                edge=sig.edge,
                kind="goals",
                reason=(f"Goals model: expected {lam[0]:.2f}-{lam[1]:.2f}, rates {label} at "
                        f"{model_prob*100:.0f}% but {book} prices {offered:.2f} "
                        f"({sig.offered_prob*100:.0f}% implied) -> +{sig.edge*100:.0f}% EV"),
                notes=[f"lambda {lam[0]:.2f}/{lam[1]:.2f}"],
                kickoff=snap.kickoff,
            ))
    return gems


def scan_all(snapshots: list[MarketSnapshot], model: GoalsModel, *, min_edge: float = 0.05,
             max_odds: float = 5.0, allowed_books: set[str] | None = None) -> list[GemBet]:
    gems: list[GemBet] = []
    for snap in snapshots:
        gems.extend(scan_snapshot(snap, model, min_edge=min_edge, max_odds=max_odds,
                                  allowed_books=allowed_books))
    return sorted(gems, key=lambda g: g.edge, reverse=True)


# ---------------------------------------------------------- free results source

def parse_footballdata_csv(text: str) -> list[tuple[str, str, int, int]]:
    """Parse a football-data.co.uk CSV (cols HomeTeam, AwayTeam, FTHG, FTAG)."""
    out: list[tuple[str, str, int, int]] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append((row["HomeTeam"], row["AwayTeam"],
                        int(row["FTHG"]), int(row["FTAG"])))
        except (KeyError, ValueError, TypeError):
            continue                # skip header noise / unplayed fixtures
    return out


async def load_footballdata(url: str) -> GoalsModel:
    """Fetch a football-data.co.uk league CSV and fit a model. No key needed.

    e.g. https://www.football-data.co.uk/mmz4281/2526/E0.csv (Premier League 25/26).
    """
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        resp = await c.get(url)
        resp.raise_for_status()
        results = parse_footballdata_csv(resp.text)
    log.info("goals model: fitted from %d results (%s)", len(results), url)
    return fit(results)
