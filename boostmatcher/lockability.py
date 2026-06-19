"""Decide whether a boost can be locked, and say exactly what to lay.

Bookies bury boosts in props/combos you can't cover. This reads a boost's
selection text and classifies it into the exchange MARKET it belongs to — so the
site can (a) filter out the ones with no lockable market and (b) tell you the
precise market + selection to lay on Matchbook/Betfair.

Heuristic and deliberately conservative: when unsure it returns "none" rather
than send you hunting for a market that isn't there. Order matters — combos and
player props are checked before the generic "team to win" rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lock:
    kind: str            # "lay" (exchange market exists) | "none" (can't lock)
    market: str = ""     # exchange market name to open, e.g. "Match Odds"
    lay: str = ""        # the selection to lay within that market
    note: str = ""       # human explanation / caveat

    @property
    def lockable(self) -> bool:
        return self.kind == "lay"


# Words that mean "player prop the exchange doesn't price" -> never lockable.
_PROP = ("shot on target", "shots on target", "to be carded", "to be booked",
         "card", "foul", "with a header", "with a free", "assist", "to be shown",
         "tackle", "offside", "corner", "to be sent off", "to commit")
# Specialist markets that exchanges rarely list -> treat as not lockable.
_SPECIAL = ("both halves", "to nil", "ht/ft", "half-time/full-time", "half time/full time",
            "winning margin", "score in both", "to score in both", "multi", "bet builder")


def _combo(s: str) -> bool:
    """A multi-leg boost (two+ things must all happen) — no single market."""
    return (" & " in s or " and " in s or "," in s
            or s.count(" to ") > 1 or s.count(" - ") > 1)


def classify(selection: str) -> Lock:
    s = selection.strip().lower()

    if _combo(s):
        return Lock("none", note="combo / multi-leg — no single exchange market")
    if any(p in s for p in _PROP):
        return Lock("none", note="player prop — exchanges don't price this to lay")
    if any(p in s for p in _SPECIAL):
        return Lock("none", note="specialist market — rarely on the exchange")

    # Both teams to score
    if "both teams to score" in s or s in ("btts", "btts - yes", "gg"):
        return Lock("lay", "Both Teams to Score", "Yes",
                    note="lay the 'Yes' in the BTTS market")

    # Total goals over/under  (e.g. "over 2.5 goals", "under 3.5 goals")
    m = re.search(r"\b(over|under)\s+([\d.]+)\s+goals?\b", s)
    if m:
        return Lock("lay", f"Over/Under {m.group(2)} Goals", f"{m.group(1).title()} {m.group(2)}",
                    note="lay the same over/under line")

    # Anytime goalscorer / player to score (not header/both-halves, already excluded)
    if ("anytime" in s and "scor" in s) or re.search(r"\bto score\b", s):
        player = re.sub(r"(anytime goalscorer|anytime scorer|to score.*)", "", s, flags=re.I)
        player = re.sub(r"[-–]", "", player).strip().title()
        return Lock("lay", "Anytime Goalscorer", player or selection,
                    note="exchange 'To Score' market — big matches only; check liquidity")

    # Correct score
    if "correct score" in s or re.search(r"\b\d\s*[-–]\s*\d\b", s):
        return Lock("lay", "Correct Score", selection, note="lay the exact score; thin liquidity")

    # Match result: "<team> to win" with nothing else attached
    m = re.search(r"^(.*?)\s+to win$", s)
    if m:
        team = m.group(1).strip().title()
        return Lock("lay", "Match Odds", team, note="lay the team in the match-result market")

    # Double chance / draw no bet
    if "double chance" in s or "draw no bet" in s:
        return Lock("lay", "Double Chance / Draw No Bet", selection, note="lay the same line")

    return Lock("none", note="no standard exchange market matches this selection")
