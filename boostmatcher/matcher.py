"""Match a scraped Boost to the right exchange runner.

This is the genuinely hard module-2 problem: a bookie writes "England to win",
the exchange runner is "England", the market is "Match Odds" on event
"England v USA". We normalise both sides and score candidates by token overlap,
returning the best runner per exchange so the rating core can price it.

Player-prop boosts ("Saka 2+ shots on target") usually have NO exchange runner
to lay — `match` returns None for those and the caller surfaces them as
manual-only. Keeping this heuristic and dependency-free; swap in a fuzzy lib
later if recall is poor.
"""
from __future__ import annotations

import re

_STOP = {"to", "win", "the", "of", "a", "fc", "afc", "v", "vs", "and", "&"}
_NORMALISE = str.maketrans("", "", ".,'’")


def tokens(text: str) -> set[str]:
    """Lower-cased significant word tokens, stop-words and punctuation removed."""
    cleaned = text.translate(_NORMALISE).lower()
    return {w for w in re.split(r"\s+", cleaned) if w and w not in _STOP}


def score(selection: str, runner: str) -> float:
    """Jaccard overlap of significant tokens, in [0, 1]."""
    a, b = tokens(selection), tokens(runner)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_runner(selection: str, runners: list[str], *, threshold: float = 0.5) -> str | None:
    """Return the runner name best matching `selection`, or None below threshold."""
    if not runners:
        return None
    ranked = sorted(runners, key=lambda r: score(selection, r), reverse=True)
    top = ranked[0]
    return top if score(selection, top) >= threshold else None
