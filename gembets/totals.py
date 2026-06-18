"""Detector E: a free, multi-market team-totals model.

The key unlock: one free football-data.co.uk CSV carries, per match, the columns
for fouls, corners, cards, shots and shots-on-target *plus the referee*. So a
single fetch lets us model the fair line for many "match total" markets at once —
the corners/cards/shots/fouls gems you asked for — with zero paid data.

Same Poisson ratio model as the goals detector, generalised to any stat:

  * for each stat, every team gets a "for" rate (how much it produces) and an
    "against" rate (how much its opponents produce against it), vs the league avg;
  * expected match total = home side's expected + away side's expected;
  * for CARDS we also multiply by a referee factor (their cards/game vs league) —
    the "strict ref vs disciplined teams" edge, now sourced free from the CSV;
  * Poisson turns the expected total into P(over line) for any line.

What's free vs not: the MODEL (this file) is fully free and tested. The bit you
still supply is the bookmaker's offered price for these markets — they're niche,
so the realistic free route is reading the line off the bookie yourself; the
`gembets model` command then tells you instantly whether it's a gem. Referee
data in the CSV is Premier-League-only; elsewhere the referee factor is 1.0.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

from .goals import normalise
from .models import GemBet
from .odds import decimal_to_implied, evaluate_value, implied_to_decimal, prob_over_line

log = logging.getLogger(__name__)

# market -> (home_col, away_col) in the football-data CSV. "cards" is derived
# (yellows + reds for each side). Goals included so one model covers everything.
_COLS: dict[str, tuple[str, str]] = {
    "goals": ("FTHG", "FTAG"),
    "shots": ("HS", "AS"),
    "shots_on_target": ("HST", "AST"),
    "fouls": ("HF", "AF"),
    "corners": ("HC", "AC"),
    # Booking points (10 per yellow, 25 per red) — matches Betfair's cards market
    # exactly, unlike a raw card count. football-data carries HBP/ABP directly.
    "booking_points": ("HBP", "ABP"),
}

# Markets that scale with referee strictness (cards-type).
_REF_SCALED = {"cards", "booking_points"}

# Sensible default over/under lines to print per market.
DEFAULT_LINES: dict[str, list[float]] = {
    "goals": [1.5, 2.5, 3.5],
    "cards": [2.5, 3.5, 4.5, 5.5],
    "booking_points": [20.5, 30.5, 40.5, 50.5],
    "corners": [8.5, 9.5, 10.5, 11.5, 12.5],
    "fouls": [20.5, 22.5, 24.5, 26.5],
    "shots": [22.5, 24.5, 26.5],
    "shots_on_target": [7.5, 8.5, 9.5],
}


# --------------------------------------------------------------- data loading

@dataclass
class Match:
    home: str
    away: str
    referee: str
    stats: dict[str, tuple[float, float]] = field(default_factory=dict)


def _num(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return None


def parse_matches(text: str) -> list[Match]:
    """Parse a football-data.co.uk CSV into Matches with every stat it carries."""
    out: list[Match] = []
    for row in csv.DictReader(io.StringIO(text)):
        home, away = row.get("HomeTeam"), row.get("AwayTeam")
        if not home or not away:
            continue
        stats: dict[str, tuple[float, float]] = {}
        for stat, (hc, ac) in _COLS.items():
            h, a = _num(row, hc), _num(row, ac)
            if h is not None and a is not None:
                stats[stat] = (h, a)
        # cards = yellows + reds per side (count; a straight/second-yellow red = its cards)
        hy, ay = _num(row, "HY"), _num(row, "AY")
        hr, ar = _num(row, "HR"), _num(row, "AR")
        if None not in (hy, ay, hr, ar):
            stats["cards"] = (hy + hr, ay + ar)
        if stats:
            out.append(Match(home=home, away=away, referee=row.get("Referee", "") or "",
                             stats=stats))
    return out


async def fetch_matches(url: str) -> list[Match]:
    """Fetch a football-data.co.uk league CSV (no key). Returns parsed Matches."""
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        resp = await c.get(url)
        resp.raise_for_status()
    matches = parse_matches(resp.text)
    log.info("totals: parsed %d matches from %s", len(matches), url)
    return matches


# --------------------------------------------------------------- the model

@dataclass(frozen=True)
class TeamRate:
    for_rate: float          # produces this much vs league average (>1 = more)
    against_rate: float      # opponents produce this much vs league average
    games: int


@dataclass
class StatModel:
    rates: dict[str, TeamRate]
    home_avg: float          # league average home-side value per match
    away_avg: float

    def expected(self, home: str, away: str) -> tuple[float, float] | None:
        h = self.rates.get(normalise(home))
        a = self.rates.get(normalise(away))
        if not h or not a:
            return None
        return (self.home_avg * h.for_rate * a.against_rate,
                self.away_avg * a.for_rate * h.against_rate)


def fit_stat(matches: list[Match], stat: str, *, min_games: int = 3) -> StatModel | None:
    """Fit a team-rate model for one stat (None if the data lacks that column)."""
    rows = [(m.home, m.away, *m.stats[stat]) for m in matches if stat in m.stats]
    if not rows:
        return None
    home_avg = sum(h for *_, h, _ in rows) / len(rows)
    away_avg = sum(a for *_, _, a in rows) / len(rows)
    overall = (home_avg + away_avg) / 2 or 1.0

    for_sum: dict[str, float] = {}
    against_sum: dict[str, float] = {}
    games: dict[str, int] = {}
    for home, away, hv, av in rows:
        for team, gf, ga in ((normalise(home), hv, av), (normalise(away), av, hv)):
            for_sum[team] = for_sum.get(team, 0.0) + gf
            against_sum[team] = against_sum.get(team, 0.0) + ga
            games[team] = games.get(team, 0) + 1
    rates = {t: TeamRate((for_sum[t] / g) / overall, (against_sum[t] / g) / overall, g)
             for t, g in games.items() if g >= min_games}
    return StatModel(rates=rates, home_avg=home_avg, away_avg=away_avg)


@dataclass
class RefereeModel:
    cards_pg: dict[str, float]       # normalised referee name -> cards/game
    games: dict[str, int]
    league_avg: float

    def factor(self, referee: str | None, *, min_games: int = 5) -> float:
        """Cards multiplier for a referee vs the league (1.0 if unknown/too few)."""
        if not referee:
            return 1.0
        key = normalise(referee)
        if self.games.get(key, 0) < min_games or self.league_avg <= 0:
            return 1.0
        return self.cards_pg[key] / self.league_avg


def fit_referees(matches: list[Match]) -> RefereeModel:
    """Referee card averages from the CSV (Premier League is the league that has refs)."""
    total: dict[str, float] = {}
    games: dict[str, int] = {}
    all_cards: list[float] = []
    for m in matches:
        if "cards" not in m.stats:
            continue
        match_cards = sum(m.stats["cards"])
        all_cards.append(match_cards)
        if m.referee:
            key = normalise(m.referee)
            total[key] = total.get(key, 0.0) + match_cards
            games[key] = games.get(key, 0) + 1
    cards_pg = {r: total[r] / g for r, g in games.items()}
    league_avg = (sum(all_cards) / len(all_cards)) if all_cards else 0.0
    return RefereeModel(cards_pg=cards_pg, games=games, league_avg=league_avg)


# --------------------------------------------------------------- the bundle

@dataclass
class TotalsModel:
    """Every per-stat model + the referee model, fit from one CSV."""

    stats: dict[str, StatModel]
    referees: RefereeModel

    def expected_total(self, market: str, home: str, away: str,
                       referee: str | None = None) -> float | None:
        sm = self.stats.get(market)
        if sm is None:
            return None
        exp = sm.expected(home, away)
        if exp is None:
            return None
        total = exp[0] + exp[1]
        if market in _REF_SCALED:
            total *= self.referees.factor(referee)
        return total

    def markets(self) -> list[str]:
        return [m for m in DEFAULT_LINES if m in self.stats]


def build(matches: list[Match]) -> TotalsModel:
    stats = {stat: m for stat in (*_COLS, "cards") if (m := fit_stat(matches, stat))}
    return TotalsModel(stats=stats, referees=fit_referees(matches))


# --------------------------------------------------------------- pricing

@dataclass
class FairLine:
    market: str
    line: float
    expected: float
    prob_over: float
    fair_over: float         # fair decimal odds for Over
    fair_under: float

    @property
    def prob_under(self) -> float:
        return 1.0 - self.prob_over


def fair_lines(model: TotalsModel, home: str, away: str, *, referee: str | None = None,
               lines: dict[str, list[float]] | None = None) -> list[FairLine]:
    """The model's fair over/under for every market+line it can price."""
    lines = lines or DEFAULT_LINES
    out: list[FairLine] = []
    for market in model.markets():
        expected = model.expected_total(market, home, away, referee)
        if expected is None:
            continue
        for line in lines.get(market, []):
            p = prob_over_line(expected, line)
            if 0.0 < p < 1.0:
                out.append(FairLine(market, line, expected, p,
                                    implied_to_decimal(p), implied_to_decimal(1.0 - p)))
    return out


@dataclass(frozen=True)
class TotalQuote:
    """An over/under price from an odds source (e.g. Betfair) for a totals market."""

    fixture: str             # "Arsenal v Chelsea"
    market: str              # goals | corners | booking_points | fouls | shots | ...
    line: float
    over_decimal: float | None = None
    under_decimal: float | None = None
    source: str = "betfair"


def _split_fixture(fixture: str) -> tuple[str | None, str | None]:
    for sep in (" vs ", " v "):
        if sep in fixture:
            h, _, a = fixture.partition(sep)
            return h.strip(), a.strip()
    return None, None


def scan_quotes(model: TotalsModel, quotes: list[TotalQuote], *, min_edge: float = 0.05,
                max_odds: float = 5.0, referee: str | None = None) -> list[GemBet]:
    """Spot mispriced totals: compare each offered Over/Under to the model -> GemBets.

    This is the mispricing engine for Detector E — feed it quotes from any source
    (Betfair Exchange is the free one) and it flags every side the model thinks is
    value. EV = model_prob * offered - 1; flagged at >= min_edge, capped at max_odds.
    """
    gems: list[GemBet] = []
    for q in quotes:
        home, away = _split_fixture(q.fixture)
        if not home:
            continue
        expected = model.expected_total(q.market, home, away, referee)
        if expected is None:
            continue
        p_over = prob_over_line(expected, q.line)
        for side, offered, prob in (("Over", q.over_decimal, p_over),
                                    ("Under", q.under_decimal, 1.0 - p_over)):
            if not offered or offered > max_odds:
                continue
            sig = evaluate_value(offered, prob, min_edge=min_edge)
            if not sig.has_edge:
                continue
            gems.append(GemBet(
                fixture=q.fixture,
                market=f"{q.market} {side} {q.line}",
                selection=f"{side} {q.line}",
                book=q.source,
                decimal_odds=offered,
                implied_prob=sig.offered_prob,
                fair_prob=prob,
                edge=sig.edge,
                kind="totals",
                reason=(f"{q.market}: model expects {expected:.1f}, {side} {q.line} fair "
                        f"{prob*100:.0f}% but {q.source} pays {offered:.2f} "
                        f"({sig.offered_prob*100:.0f}% implied) -> +{sig.edge*100:.0f}% EV"),
                notes=[f"expected {expected:.1f}"],
            ))
    return sorted(gems, key=lambda g: g.edge, reverse=True)


def check(model: TotalsModel, home: str, away: str, market: str, line: float,
          offered_decimal: float, *, side: str = "over", referee: str | None = None,
          min_edge: float = 0.05):
    """EV of an offered Over/Under price vs the model. None if market unmodellable."""
    expected = model.expected_total(market, home, away, referee)
    if expected is None:
        return None
    p_over = prob_over_line(expected, line)
    model_prob = p_over if side.lower() == "over" else 1.0 - p_over
    sig = evaluate_value(offered_decimal, model_prob, min_edge=min_edge)
    return {
        "market": market, "line": line, "side": side, "expected": expected,
        "model_prob": model_prob, "implied": decimal_to_implied(offered_decimal),
        "edge": sig.edge, "has_edge": sig.has_edge,
    }
