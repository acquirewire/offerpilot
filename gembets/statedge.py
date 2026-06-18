"""Detector B: statistical mispricing (contextual edges).

Turn a real-world rate into a probability with a Poisson model, then compare it
to the book's implied price. Two football edges are built in:

  * FoulMatchup  -- "Player Over N.5 Fouls Won" priced off the player's own
                    season rate, ignoring that his DIRECT opponent (the fullback
                    he runs at) concedes fouls at a high rate. We blend the two.
  * CardsMatchup -- "Over N.5 Total Cards" priced off two disciplined teams,
                    ignoring that the appointed REFEREE books heavily. We scale
                    the teams' base rate by the referee's cards-vs-league ratio.

The model probability is only as good as its inputs and its weights — the blend
weights here are illustrative defaults; tune them by backtesting (see README).
Detector B should also be gated on CONFIRMED LINEUPS upstream (a player/fullback
edge is void if either isn't starting) — the monitor does that gating.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import GemBet
from .odds import decimal_to_implied, evaluate_value, prob_over_line


# ----------------------------------------------------- Scenario A: foul matchup

@dataclass(frozen=True)
class FoulMatchup:
    fixture: str
    player: str                          # "K. Mitoma"
    line: float                          # 1.5
    offered_decimal: float               # the book's price for the Over
    player_fouls_won_p90: float          # the winger's own rate, e.g. 1.9
    opp_defender_fouls_committed_p90: float   # the RB he faces, e.g. 2.8
    minutes_expected: float = 85.0       # discount for subs/late minutes
    opponent: str | None = None          # the defender's name, for the alert


def foul_edge(m: FoulMatchup, *, min_edge: float = 0.06,
              draw_weight: float = 0.60) -> GemBet | None:
    """Model the winger's expected fouls WON in this specific matchup.

    Blend his own foul-drawing ability with the specific fullback's tendency to
    foul: a defender who commits 2.8/90 inflates the winger's expected fouls won
    above his season baseline — the edge the market may not have priced.

        expected = (draw_weight*player_rate + (1-draw_weight)*opp_rate) * mins/90

    `draw_weight` (default 0.60) leans on the player's own ability; the rest is
    lifted by the opponent. Tune by backtesting, don't trust the default blindly.
    """
    minutes_factor = m.minutes_expected / 90.0
    matchup_rate = (draw_weight * m.player_fouls_won_p90
                    + (1.0 - draw_weight) * m.opp_defender_fouls_committed_p90)
    expected = matchup_rate * minutes_factor

    model_prob = prob_over_line(expected, m.line)
    sig = evaluate_value(m.offered_decimal, model_prob, min_edge=min_edge)
    if not sig.has_edge:
        return None

    opp = f" ({m.opponent})" if m.opponent else ""
    return GemBet(
        fixture=m.fixture,
        market=f"{m.player} Over {m.line} Fouls Won",
        selection=f"Over {m.line}",
        book="best price",
        decimal_odds=m.offered_decimal,
        implied_prob=decimal_to_implied(m.offered_decimal),
        fair_prob=model_prob,
        edge=sig.edge,
        kind="statedge",
        reason=(f"Statistical Edge: opposing defender{opp} commits "
                f"{m.opp_defender_fouls_committed_p90:.1f} fouls/90. Model expects "
                f"{expected:.2f} fouls won (P(Over {m.line})={model_prob*100:.0f}%) "
                f"vs book {decimal_to_implied(m.offered_decimal)*100:.0f}% "
                f"(+{sig.edge*100:.1f}% EV)"),
        notes=[f"player {m.player_fouls_won_p90:.1f}/90, "
               f"opp {m.opp_defender_fouls_committed_p90:.1f}/90, "
               f"{m.minutes_expected:.0f} mins expected"],
    )


# ---------------------------------------------------- Scenario B: referee cards

@dataclass(frozen=True)
class CardsMatchup:
    fixture: str
    line: float                          # 4.5
    offered_decimal: float               # the book's price for Over total cards
    home_cards_p90: float                # cards shown in this team's games, /90
    away_cards_p90: float
    referee_cards_pg: float              # the appointed ref's cards per game
    league_avg_cards_pg: float           # league baseline, to scale the ref effect
    referee: str | None = None


def cards_edge(m: CardsMatchup, *, min_edge: float = 0.06) -> GemBet | None:
    """Model expected total cards, scaled by the referee's strictness.

    Base rate is the two teams' combined card tendency. A referee who averages
    5.5/game in a 4.0/game league multiplies that by 5.5/4.0 = 1.375 — the bias
    a market pricing only the (disciplined) teams misses.

        expected = (home_cards_p90 + away_cards_p90) * (ref_pg / league_pg)
    """
    base = m.home_cards_p90 + m.away_cards_p90
    ref_factor = (m.referee_cards_pg / m.league_avg_cards_pg
                  if m.league_avg_cards_pg > 0 else 1.0)
    expected = base * ref_factor

    model_prob = prob_over_line(expected, m.line)
    sig = evaluate_value(m.offered_decimal, model_prob, min_edge=min_edge)
    if not sig.has_edge:
        return None

    ref = f" ({m.referee})" if m.referee else ""
    return GemBet(
        fixture=m.fixture,
        market=f"Over {m.line} Total Cards",
        selection=f"Over {m.line}",
        book="best price",
        decimal_odds=m.offered_decimal,
        implied_prob=decimal_to_implied(m.offered_decimal),
        fair_prob=model_prob,
        edge=sig.edge,
        kind="statedge",
        reason=(f"Referee Bias: appointed ref{ref} averages {m.referee_cards_pg:.1f} "
                f"cards/game (league {m.league_avg_cards_pg:.1f}, x{ref_factor:.2f}). "
                f"Model expects {expected:.1f} cards (P(Over {m.line})={model_prob*100:.0f}%) "
                f"vs book {decimal_to_implied(m.offered_decimal)*100:.0f}% "
                f"(+{sig.edge*100:.1f}% EV)"),
        notes=[f"teams {base:.1f}/90 combined, ref x{ref_factor:.2f}"],
    )
