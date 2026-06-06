"""Turns (previous state, new snapshot) into human-readable drop events.

A "drop" is the thing you actually want an alert for:
  * a tier whose status improved into AVAILABLE (e.g. SOLD_OUT/COMING_SOON->buy)
  * a brand-new tier that appeared already AVAILABLE (a fresh release)

We deliberately do NOT alert on the reverse (going sold out) or on
UNKNOWN<->anything churn, which is usually just a parse hiccup.
"""
from __future__ import annotations

from .models import Snapshot, Status

_BUYABLE = {Status.AVAILABLE}


def diff(previous: dict[str, Status], snapshot: Snapshot) -> list[str]:
    """Return a list of alert-worthy change descriptions (empty = nothing new)."""
    events: list[str] = []
    new_map = snapshot.as_map()

    for name, status in new_map.items():
        before = previous.get(name)

        if before is None:
            # A tier we've never seen. Only alert if it's already buyable.
            if status in _BUYABLE:
                events.append(f"NEW RELEASE on sale: '{name}'")
            continue

        if status in _BUYABLE and before not in _BUYABLE:
            events.append(f"'{name}' is now ON SALE (was {before.value})")

    return events
