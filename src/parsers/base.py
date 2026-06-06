"""Parser interface + shared helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Snapshot, Status

# Keyword -> status. Lower-cased substring match against a tier's button/label.
# Order matters: more specific first.
_KEYWORD_MAP: list[tuple[str, Status]] = [
    ("sold out", Status.SOLD_OUT),
    ("sold-out", Status.SOLD_OUT),
    ("unavailable", Status.SOLD_OUT),
    ("off sale", Status.SOLD_OUT),
    ("coming soon", Status.COMING_SOON),
    ("not yet", Status.COMING_SOON),
    ("on sale soon", Status.COMING_SOON),
    ("buy", Status.AVAILABLE),
    ("add to", Status.AVAILABLE),       # "Add to basket"
    ("get ticket", Status.AVAILABLE),
    ("select", Status.AVAILABLE),
    ("available", Status.AVAILABLE),
]


def status_from_keywords(text: str) -> Status:
    """Map a button/label string to a normalized Status."""
    t = (text or "").lower()
    for needle, status in _KEYWORD_MAP:
        if needle in t:
            return status
    return Status.UNKNOWN


class Parser(ABC):
    """Implementations turn raw response text into a Snapshot."""

    site: str

    @abstractmethod
    def parse(self, target_name: str, raw: str) -> Snapshot:
        ...

    def _empty(self, target_name: str) -> Snapshot:
        return Snapshot(target_name=target_name, tiers=[])
