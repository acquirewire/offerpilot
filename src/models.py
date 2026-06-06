"""Shared data types used across fetchers, parsers, and the detector."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    """Normalized state of a single ticket tier."""

    AVAILABLE = "AVAILABLE"      # on sale right now -> buyable
    SOLD_OUT = "SOLD_OUT"
    COMING_SOON = "COMING_SOON"  # announced but not yet on sale
    UNKNOWN = "UNKNOWN"


@dataclass
class Tier:
    """One ticket tier/release on an event page."""

    name: str
    status: Status
    price: str | None = None


@dataclass
class Snapshot:
    """The full parsed state of an event at one point in time."""

    target_name: str
    tiers: list[Tier] = field(default_factory=list)

    def as_map(self) -> dict[str, Status]:
        """name -> status, the canonical form the detector diffs against."""
        return {t.name: t.status for t in self.tiers}
