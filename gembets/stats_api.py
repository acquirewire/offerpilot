"""Stats feed for Detector B, implemented against the **Sportmonks Football v3**
API. This is the SCARCE data — referee card history and per-player "fouls won"
are what cheaper feeds lack; Sportmonks is the one that surfaces referees.

WHAT'S REAL vs WHAT NEEDS YOUR KEY
----------------------------------
The HTTP client, the v3 endpoint/include/filter syntax, the confirmed stat
`type_id`s, and all the parsing/maths are written against the v3 docs and are
unit-tested with mocked responses (test_stats.py) — no key needed to run those.
What can't be verified from a dev box is the exact *shape* of a few nested
objects (the lineup starter flag, the referee-role marker, team/referee stat
names), because those only materialise once you hit the live API. So parsing is
deliberately DEFENSIVE and NAME-BASED, and `gembets sportmonks-probe` dumps one
real fixture so you can confirm/adjust against your account. Same "implemented to
the documented API, verify live with probe" pattern as boostmatcher's exchanges.

THE PRICE JOIN (important)
--------------------------
Sportmonks gives STATS, not ODDS. A gem needs both: our modelled probability AND
the bookmaker's offered price. So the live builders take a `price_lookup`
callable `(fixture, market, line) -> decimal | None`; matchups with no price are
skipped. Wiring that lookup to a props-capable odds feed (OpticOdds for player
foul props; the cards-total market) is the one remaining integration — see README.

A foul/winger edge is VOID unless both the player and his direct opponent are in
the CONFIRMED XI — live builders only use fixtures whose lineups are confirmed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import httpx

from .statedge import CardsMatchup, FoulMatchup

log = logging.getLogger(__name__)

BASE = "https://api.sportmonks.com/v3/football"

# Player-statistics type_ids, confirmed from the v3 "Player statistics" reference.
FOULS_COMMITTED = 56
FOULS_DRAWN = 96          # "fouls won" in betting parlance
YELLOWCARDS = 84
REDCARDS = 83
YELLOWRED = 85            # second-yellow -> red; counted as a card when present
MINUTES = 119
APPEARANCES = 321

# (fixture, market, line) -> best available decimal odds, or None if not priced.
PriceLookup = Callable[[str, str, float], "float | None"]


# --------------------------------------------------------------------------- #
#  Offline path (used by `gembets demo`) — unchanged dict builders.           #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FixtureContext:
    """Everything Detector B needs about one fixture, post-lineup-confirmation."""

    fixture: str
    lineups_confirmed: bool
    referee: str | None = None
    referee_cards_pg: float | None = None
    league_avg_cards_pg: float | None = None
    home_cards_p90: float | None = None
    away_cards_p90: float | None = None


def build_foul_matchups(raw: list[dict]) -> list[FoulMatchup]:
    """Map sample/provider rows to FoulMatchup, skipping unconfirmed lineups."""
    out = []
    for r in raw:
        if not r.get("lineups_confirmed", False):
            continue
        out.append(FoulMatchup(
            fixture=r["fixture"], player=r["player"], line=float(r.get("line", 1.5)),
            offered_decimal=float(r["offered_decimal"]),
            player_fouls_won_p90=float(r["player_fouls_won_p90"]),
            opp_defender_fouls_committed_p90=float(r["opp_defender_fouls_committed_p90"]),
            minutes_expected=float(r.get("minutes_expected", 85.0)),
            opponent=r.get("opponent")))
    return out


def build_cards_matchups(raw: list[dict]) -> list[CardsMatchup]:
    out = []
    for r in raw:
        out.append(CardsMatchup(
            fixture=r["fixture"], line=float(r.get("line", 4.5)),
            offered_decimal=float(r["offered_decimal"]),
            home_cards_p90=float(r["home_cards_p90"]), away_cards_p90=float(r["away_cards_p90"]),
            referee_cards_pg=float(r["referee_cards_pg"]),
            league_avg_cards_pg=float(r["league_avg_cards_pg"]), referee=r.get("referee")))
    return out


def load_sample(path: str) -> tuple[list[FoulMatchup], list[CardsMatchup]]:
    """Offline stats for `demo`: {"fouls": [...], "cards": [...]} JSON."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return build_foul_matchups(raw.get("fouls", [])), build_cards_matchups(raw.get("cards", []))


# --------------------------------------------------------------------------- #
#  Pure parsing helpers (no network) — these carry the field-shape assumptions #
#  and are exhaustively unit-tested. Adjust here if `probe` shows a mismatch.  #
# --------------------------------------------------------------------------- #

def _num(value: object) -> float | None:
    """Pull a number out of a v3 stat `value`, which is type-specific.

    Counts come as {"total": N}; rates sometimes as {"average": x} or {"count": n};
    occasionally the value is already a scalar. Prefer total, then average/count.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("total", "average", "count", "value"):
            if isinstance(value.get(k), (int, float)):
                return float(value[k])
    return None


def _detail(details: Iterable[dict], type_id: int) -> float | None:
    """Value of the stat with this type_id from a `statistics.details` array."""
    for d in details:
        if d.get("type_id") == type_id:
            return _num(d.get("value"))
    return None


def _detail_named(details: Iterable[dict], *needles: str) -> float | None:
    """Value of the first stat whose type name contains any needle (case-insensitive).

    Name-based fallback for entities whose numeric type_ids we can't pin from the
    docs (team/referee stats). Requires the `.type` nested include to be present.
    """
    for d in details:
        name = str(((d.get("type") or {}).get("name") or "")).lower()
        if name and any(n in name for n in needles):
            v = _num(d.get("value"))
            if v is not None:
                return v
    return None


def home_away(fixture: dict) -> tuple[dict | None, dict | None]:
    """(home_participant, away_participant) via participants[].meta.location."""
    home = away = None
    for p in fixture.get("participants", []):
        loc = (p.get("meta") or {}).get("location")
        if loc == "home":
            home = p
        elif loc == "away":
            away = p
    return home, away


def fixture_name(fixture: dict) -> str:
    home, away = home_away(fixture)
    h = (home or {}).get("name", "Home")
    a = (away or {}).get("name", "Away")
    return f"{h} vs {a}"


def main_referee(fixture: dict) -> dict | None:
    """The match referee from the referees include (not assistants / VAR / 4th).

    Selected by role NAME ("Referee") rather than a guessed type_id, so it
    survives id changes. Each entry: {type:{name}, referee:{id,name}} (or flat).
    """
    refs = fixture.get("referees") or []
    def role(r): return str(((r.get("type") or {}).get("name") or "")).lower()
    exact = [r for r in refs if role(r) == "referee"]
    loose = [r for r in refs if "referee" in role(r)
             and not any(x in role(r) for x in ("assistant", "video", "fourth", "var"))]
    pick = (exact or loose or refs[:1])
    if not pick:
        return None
    r = pick[0]
    return r.get("referee") or {"id": r.get("referee_id"), "name": r.get("name")}


def lineups_confirmed(fixture: dict) -> bool:
    """True only when the XI is CONFIRMED, not predicted.

    Prefers an explicit flag if the feed sets one; otherwise treats a populated
    `lineups` array as confirmed (the feed only fills it at confirmation, and the
    `expectedLineups` include is a *separate* field we never read).
    """
    for key in ("lineups_confirmed", "is_lineup_confirmed"):
        if isinstance(fixture.get(key), bool):
            return fixture[key]
    return bool(fixture.get("lineups"))


def _is_starter(entry: dict) -> bool:
    # Sportmonks marks starting XI vs bench via type_id (11 = lineup, 12 = bench).
    # Fall back to a truthy formation position when the id isn't present.
    tid = entry.get("type_id")
    if tid in (11, None):
        return tid == 11 or bool(entry.get("formation_field") or entry.get("formation_position"))
    return False


def _position_name(entry: dict) -> str:
    for key in ("position", "detailed_position"):
        nm = (entry.get(key) or {}).get("name")
        if nm:
            return str(nm).lower()
    return str(entry.get("position_name") or "").lower()


def _player_id(entry: dict) -> int | None:
    return entry.get("player_id") or (entry.get("player") or {}).get("id")


def _player_name(entry: dict) -> str:
    return entry.get("player_name") or (entry.get("player") or {}).get("name") or "Player"


def starters(fixture: dict, team_id: int) -> list[dict]:
    return [e for e in fixture.get("lineups", [])
            if e.get("team_id") == team_id and _is_starter(e)]


def _side(pos: str) -> str | None:
    if "left" in pos:
        return "left"
    if "right" in pos:
        return "right"
    return None


def _is_wide_attacker(pos: str) -> bool:
    return ("wing" in pos and "back" not in pos) or "winger" in pos


def _is_fullback(pos: str) -> bool:
    # Right/Left Back or Wing-Back; exclude centre-backs and goalkeepers.
    return "back" in pos and "cent" not in pos and "goal" not in pos and _side(pos) is not None


def pair_wingers_to_fullbacks(fixture: dict, home_id: int, away_id: int) -> list[dict]:
    """Heuristic matchups: a winger faces the OPPOSING fullback on the mirrored flank.

    A left winger runs at the opponent's right back, and vice versa. Returns dicts
    {fixture, attacker_id, attacker_name, defender_id, defender_name} for each pair
    we can form from the confirmed XIs. Tactical reality is messier (inversions,
    swaps) — this is a first cut to tune once you see real edges land.
    """
    mirror = {"left": "right", "right": "left"}
    out: list[dict] = []
    for att_team, def_team in ((home_id, away_id), (away_id, home_id)):
        wingers = [(e, _side(_position_name(e))) for e in starters(fixture, att_team)
                   if _is_wide_attacker(_position_name(e))]
        backs = [(e, _side(_position_name(e))) for e in starters(fixture, def_team)
                 if _is_fullback(_position_name(e))]
        for w, wside in wingers:
            if not wside:
                continue
            opp = next((b for b, bside in backs if bside == mirror[wside]), None)
            if opp is None:
                continue
            out.append({
                "attacker_id": _player_id(w), "attacker_name": _player_name(w),
                "defender_id": _player_id(opp), "defender_name": _player_name(opp),
            })
    return out


def per90_from_details(details: list[dict], type_id: int) -> float | None:
    """A per-90 rate for a count stat: total(type) / (minutes / 90)."""
    total = _detail(details, type_id)
    minutes = _detail(details, MINUTES)
    if total is None or not minutes:
        return None
    return total / (minutes / 90.0)


def team_cards_per_match(details: list[dict]) -> float | None:
    """(yellows + reds) per match from a team's season `statistics.details`.

    Type_ids for *team* card stats aren't pinned in the docs, so match by name
    (needs `statistics.details.type`). Falls back across common match-count names.
    """
    yellow = _detail_named(details, "yellowcard", "yellow card") or 0.0
    red = _detail_named(details, "redcard", "red card") or 0.0
    matches = _detail_named(details, "appearance", "matches played", "games", "matches")
    total = yellow + red
    if matches and matches > 0:
        return total / matches
    return None


def referee_cards_per_game(details: list[dict]) -> float | None:
    """(yellows + reds) per game for a referee's season `statistics.details`."""
    return team_cards_per_match(details)   # same name-based shape


# --------------------------------------------------------------------------- #
#  Live Sportmonks v3 client.                                                  #
# --------------------------------------------------------------------------- #

class SportmonksError(RuntimeError):
    pass


class Sportmonks:
    """Thin async v3 client: token auth, includes, filters, pagination, retry.

    Season-scoped per-90 / per-game computations are cached for the life of the
    client so one player isn't refetched across multiple matchups in a tick.
    """

    def __init__(self, token: str | None = None, *, timeout: float = 20.0):
        self.token = token or os.getenv("STATS_API_KEY", "")
        if not self.token:
            raise SportmonksError(
                "STATS_API_KEY not set - add it to .env (sportmonks.com). Until then run "
                "`gembets demo`, or keep enable_statedge: false.")
        self._timeout = timeout
        self._cache: dict[tuple, float | None] = {}

    async def _get(self, path: str, *, includes: str | None = None,
                   filters: str | None = None, params: dict | None = None) -> dict:
        q = {"api_token": self.token, "per_page": 50}
        if includes:
            q["include"] = includes
        if filters:
            q["filters"] = filters
        if params:
            q.update(params)
        url = f"{BASE}/{path.lstrip('/')}"
        last_exc: Exception | None = None
        for attempt in range(3):                      # brief retry on transient errors
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=q)
                if resp.status_code == 429:           # rate limited -> back off
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:                  # noqa: BLE001
                last_exc = exc
                await asyncio.sleep(0.5 * (attempt + 1))
        raise SportmonksError(f"GET {path} failed: {last_exc}")

    async def fixtures_by_date(self, date: str, league_ids: list[int] | None = None,
                               includes: str | None = None) -> list[dict]:
        """All fixtures on a date (YYYY-MM-DD), optionally filtered to leagues.

        Default includes pull everything Detector B needs in one call per page:
        participants (home/away), referees, lineups (+ player & position), and
        each lineup player's season statistics for the per-90 rates.
        """
        includes = includes or (
            "participants;referees;"
            "lineups.player.statistics.details.type;lineups.position")
        flt = f"fixtureLeagues:{','.join(map(str, league_ids))}" if league_ids else None
        out: list[dict] = []
        page = 1
        while True:
            payload = await self._get(f"fixtures/date/{date}", includes=includes,
                                      filters=flt, params={"page": page})
            out.extend(payload.get("data", []))
            pag = payload.get("pagination") or {}
            if not (pag.get("has_more") or payload.get("has_more")):
                break
            page += 1
            if page > 20:                             # safety: never loop forever
                break
        return out

    async def player_per90(self, player_id: int, season_id: int, type_id: int) -> float | None:
        key = ("p", player_id, season_id, type_id)
        if key in self._cache:
            return self._cache[key]
        payload = await self._get(
            f"players/{player_id}", includes="statistics.details.type",
            filters=f"playerStatisticSeasons:{season_id}")
        details = _season_details(payload.get("data", {}), season_id)
        val = per90_from_details(details, type_id) if details else None
        self._cache[key] = val
        return val

    async def referee_cards_pg(self, referee_id: int, season_id: int | None) -> float | None:
        key = ("r", referee_id, season_id)
        if key in self._cache:
            return self._cache[key]
        payload = await self._get(f"referees/{referee_id}", includes="statistics.details.type")
        details = _season_details(payload.get("data", {}), season_id)
        val = referee_cards_per_game(details) if details else None
        self._cache[key] = val
        return val

    async def team_cards_pg(self, team_id: int, season_id: int) -> float | None:
        key = ("t", team_id, season_id)
        if key in self._cache:
            return self._cache[key]
        payload = await self._get(f"teams/{team_id}", includes="statistics.details.type",
                                  filters=f"teamStatisticSeasons:{season_id}")
        details = _season_details(payload.get("data", {}), season_id)
        val = team_cards_per_match(details) if details else None
        self._cache[key] = val
        return val


def _season_details(entity: dict, season_id: int | None) -> list[dict]:
    """Flatten an entity's `statistics[].details[]`, preferring the wanted season.

    Player/team/referee all share the `statistics` array shape; each element is a
    season with a `details` list. If season_id is given we take that season, else
    the most recent statistics block.
    """
    stats = entity.get("statistics") or []
    if not stats:
        return []
    chosen = None
    if season_id is not None:
        chosen = next((s for s in stats if s.get("season_id") == season_id), None)
    chosen = chosen or stats[-1]
    return chosen.get("details") or []


# --------------------------------------------------------------------------- #
#  Orchestration: fixtures -> matchups (priced via the injected lookup).       #
# --------------------------------------------------------------------------- #

async def build_live_matchups(
    client: Sportmonks, fixtures: list[dict], *,
    price_lookup: PriceLookup | None = None,
    league_avg_cards_pg: float = 4.0,
    foul_line: float = 1.5, cards_line: float = 4.5,
) -> tuple[list[FoulMatchup], list[CardsMatchup]]:
    """Turn confirmed-lineup fixtures into typed matchups statedge can rate.

    Without a `price_lookup` we can't form a gem (no offered price), so matchups
    are skipped — but the modelled rates are still logged, which is exactly what
    `sportmonks-probe` surfaces so you can see the stats wiring working live.
    """
    fouls: list[FoulMatchup] = []
    cards: list[CardsMatchup] = []
    for fx in fixtures:
        if not lineups_confirmed(fx):
            continue
        name = fixture_name(fx)
        season_id = fx.get("season_id")
        home, away = home_away(fx)
        if not (home and away and season_id):
            continue

        # --- Cards / referee-bias matchup ---
        ref = main_referee(fx)
        ref_pg = await client.referee_cards_pg(ref["id"], season_id) if ref and ref.get("id") else None
        home_pg = await client.team_cards_pg(home["id"], season_id)
        away_pg = await client.team_cards_pg(away["id"], season_id)
        if ref_pg and home_pg is not None and away_pg is not None:
            price = price_lookup(name, f"Over {cards_line} Total Cards", cards_line) if price_lookup else None
            log.info("statedge cards %s: teams %.2f+%.2f, ref %.2f, price=%s",
                     name, home_pg, away_pg, ref_pg, price)
            if price:
                cards.append(CardsMatchup(
                    fixture=name, line=cards_line, offered_decimal=price,
                    home_cards_p90=home_pg, away_cards_p90=away_pg,
                    referee_cards_pg=ref_pg, league_avg_cards_pg=league_avg_cards_pg,
                    referee=(ref or {}).get("name")))

        # --- Foul / winger-vs-fullback matchups ---
        for pair in pair_wingers_to_fullbacks(fx, home["id"], away["id"]):
            won = await client.player_per90(pair["attacker_id"], season_id, FOULS_DRAWN)
            committed = await client.player_per90(pair["defender_id"], season_id, FOULS_COMMITTED)
            if won is None or committed is None:
                continue
            market = f"{pair['attacker_name']} Over {foul_line} Fouls Won"
            price = price_lookup(name, market, foul_line) if price_lookup else None
            log.info("statedge foul %s: %s won %.2f vs %s committed %.2f, price=%s",
                     name, pair["attacker_name"], won, pair["defender_name"], committed, price)
            if price:
                fouls.append(FoulMatchup(
                    fixture=name, player=pair["attacker_name"], line=foul_line,
                    offered_decimal=price, player_fouls_won_p90=won,
                    opp_defender_fouls_committed_p90=committed,
                    opponent=pair["defender_name"]))
    return fouls, cards


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


async def fetch_sportmonks(
    sport_key: str, *, league_ids: list[int] | None = None,
    price_lookup: PriceLookup | None = None, league_avg_cards_pg: float = 4.0,
    date: str | None = None,
) -> tuple[list[FoulMatchup], list[CardsMatchup]]:
    """Live entry point used by the monitor: today's confirmed fixtures -> matchups.

    `sport_key` is the odds-side league key; pass `league_ids` (Sportmonks numeric
    league ids) to scope the fixtures call. `price_lookup` joins the bookmaker's
    offered price to each modelled selection — without it, matchups are logged but
    not emitted (no price = no gem). Gated on STATS_API_KEY via the client.
    """
    client = Sportmonks()
    fixtures = await client.fixtures_by_date(date or _today(), league_ids)
    log.info("sportmonks: %d fixture(s) on %s", len(fixtures), date or _today())
    return await build_live_matchups(client, fixtures, price_lookup=price_lookup,
                                     league_avg_cards_pg=league_avg_cards_pg)


async def probe_fixture(date: str | None = None, league_ids: list[int] | None = None) -> dict:
    """Fetch ONE fixture with the full include set and summarise what we parsed.

    The live sanity check (mirrors boostmatcher's `probe`): proves your key works
    and shows whether home/away, the main referee, and the confirmed XI + positions
    parse correctly — so you can correct any field path before trusting Detector B.
    """
    client = Sportmonks()
    fixtures = await client.fixtures_by_date(date or _today(), league_ids)
    if not fixtures:
        return {"fixtures": 0, "note": "no fixtures on this date/league — try another date"}
    fx = next((f for f in fixtures if lineups_confirmed(f)), fixtures[0])
    home, away = home_away(fx)
    ref = main_referee(fx)
    pairs = pair_wingers_to_fullbacks(fx, (home or {}).get("id"), (away or {}).get("id")) \
        if home and away else []
    return {
        "fixtures_today": len(fixtures),
        "fixture": fixture_name(fx),
        "season_id": fx.get("season_id"),
        "lineups_confirmed": lineups_confirmed(fx),
        "main_referee": (ref or {}).get("name"),
        "starters_home": len(starters(fx, (home or {}).get("id"))) if home else 0,
        "starters_away": len(starters(fx, (away or {}).get("id"))) if away else 0,
        "winger_fullback_pairs": [f"{p['attacker_name']} vs {p['defender_name']}" for p in pairs],
    }


PROVIDERS = {
    "sportmonks": fetch_sportmonks,
}
