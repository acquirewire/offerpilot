"""Bookie boost-page scrapers: rendered page HTML -> list[Boost].

Bookie boost pages are JS-rendered + bot/geo-gated, so the live flow renders
them in headless Chromium (reuse jobtracker/browser.py) and hands the resulting
HTML to a parser here. Parsing uses the tiny CSS-ish engine in `dom.py`, driven
by a `SelectorSpec` of selector strings, so adapting to a book is editing
selectors you read off the live DOM in DevTools — not rewriting logic.

The selector strings are deliberately powerful enough for real bookie markup:

  * hashed CSS modules  -> class PREFIX:    ".BoostCard_root*"
  * stable test hooks   -> data attribute:  "[data-test-id=boost-card]"
  * odds in an attribute (very common) -> "[data-odds]::attr(data-odds)" or
                                          "span::attr(aria-label)"

Odds are normalised to decimal whether the page gives fractional ("10/3"),
decimal ("4.33"), or "evens". Extraction + odds maths are unit-tested against
fixtures; only the selector strings in each SelectorSpec need confirming live.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import dom
from .models import Boost


def to_decimal(odds: str | None) -> float | None:
    """Parse '10/3', '4.33', '4/1', 'evens' -> decimal price. None if unparseable."""
    if not odds:
        return None
    s = odds.strip().lower().replace(" ", "")
    if s in ("evens", "evs", "1/1"):
        return 2.0
    if "/" in s:
        try:
            num, den = s.split("/")
            return round(int(num) / int(den) + 1.0, 4)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


@dataclass(frozen=True)
class SelectorSpec:
    """Selector strings (dom.py grammar) locating a boost card and its fields.

    Read these off the live page in DevTools. `now_odds`/`was_odds` may point at
    an attribute (e.g. "::attr(aria-label)") when the price isn't plain text.
    """

    card: str               # selector matching each boost card container
    event: str              # selector for the event-name node
    selection: str          # selector for the boosted-selection node
    now_odds: str           # selector for the boosted (current) price
    was_odds: str = ""      # selector for the struck-through original price (optional)
    bookie_sel: str = ""    # per-card bookie selector (aggregators) e.g. logo alt;
                            # blank => use the fixed bookie passed to parse_with


def _first(card, selectors: str) -> str | None:
    """first_value over COMMA-separated alternative selectors; first hit wins.

    Lets one spec field cover layout variants (e.g. a page that renders the same
    odds in `.oddBtn*` in one card and `.boostOddBtn*` in another).
    """
    for sel in (s.strip() for s in selectors.split(",") if s.strip()):
        val = dom.first_value(card, sel)
        if val:
            return val
    return None


def parse_with(html: str, bookie: str, spec: SelectorSpec, *, url: str = "") -> list[Boost]:
    """Find each card by `spec.card`, pull its fields, build Boosts.

    `selection` + `now_odds` are required; `event` and `was_odds` are optional
    (some boosts — player props especially — carry no match name on the card).
    A card missing the selection or boosted price is skipped, not guessed.
    Any field may list comma-separated alternative selectors (first match wins).
    """
    root = dom.parse(html)
    boosts: list[Boost] = []
    seen: set[str] = set()                       # a boost shown in hero + list is one boost
    for card in dom.find_all(root, spec.card):
        selection = _first(card, spec.selection)
        now = to_decimal(_first(card, spec.now_odds))
        if not (selection and now):
            continue
        event = (_first(card, spec.event) if spec.event else None) or ""
        was = to_decimal(_first(card, spec.was_odds)) if spec.was_odds else None
        this_bookie = bookie
        if spec.bookie_sel:
            raw = _first(card, spec.bookie_sel)
            if raw:                                    # "bet365 logo" -> "bet365"
                this_bookie = raw.lower().replace("logo", "").strip() or bookie
        boost = Boost(bookie=this_bookie, event=event.strip(), market="Boost",
                      selection=selection.strip(), boosted_odds=now,
                      original_odds=was, url=url)
        if boost.key() in seen:
            continue
        seen.add(boost.key())
        boosts.append(boost)
    return boosts


# Default selector specs. Class names are PLACEHOLDERS to confirm on the live
# DOM — but written in the flexible forms you'll actually need. Start with Sky
# Bet (cleanest super-boosts page). If a book uses hashed classes, switch that
# field to a class-prefix (".Prefix*") or a data-attribute selector.
SPECS: dict[str, SelectorSpec] = {
    # Sky Bet uses Flutter's hashed CSS modules (class="<hash>-runnerName"); the
    # hash prefix changes per deploy but the suffixes are stable, so we match on
    # the suffix via [class*=...]. Confirmed against a live card 2026-06-18.
    # Note: the match/event name is NOT on the boost card, so `event` is left
    # blank (player-prop boosts can't be laid anyway; layable ones still rate).
    "skybet": SelectorSpec(
        card="[class*=-container]",
        event="",
        selection="[class*=-runnerName]",
        now_odds="[class*=-label]",
        was_odds="[class*=StruckThrough]"),
    "bet365": SelectorSpec(
        card=".sbb-BoostedItem*", event=".sbb-Event*",
        selection=".sbb-Selection*", now_odds=".sbb-Odds*"),
    "williamhill": SelectorSpec(
        card="[data-test=yourodds-card]", event="[data-test=event]",
        selection="[data-test=selection]", now_odds="[data-test=price]::attr(data-odds)"),
    "paddypower": SelectorSpec(
        card=".PriceBoost*", event=".event*", selection=".selection*",
        now_odds=".boostedPrice*", was_odds=".wasPrice*"),
}


# oddschecker aggregates boosts from MANY books on one page — best single target.
# Hashed classes, but prefixes are stable; the bookie is in each logo's alt text.
SPECS["oddschecker"] = SelectorSpec(
    card=".BoostWrapper*",
    event="",
    selection=".BoostTitle*",
    now_odds=".oddBtn*, .boostOddBtn*",
    was_odds=".BoostPrevOdd*",
    bookie_sel="img[alt*=logo]::attr(alt)")


def parse_oddschecker(html: str, *, url: str = "") -> list[Boost]:
    return parse_with(html, "oddschecker", SPECS["oddschecker"], url=url)


def parse_skybet(html: str, *, url: str = "") -> list[Boost]:
    return parse_with(html, "skybet", SPECS["skybet"], url=url)


def parse_bet365(html: str, *, url: str = "") -> list[Boost]:
    return parse_with(html, "bet365", SPECS["bet365"], url=url)


def parse_williamhill(html: str, *, url: str = "") -> list[Boost]:
    return parse_with(html, "williamhill", SPECS["williamhill"], url=url)


def parse_paddypower(html: str, *, url: str = "") -> list[Boost]:
    return parse_with(html, "paddypower", SPECS["paddypower"], url=url)


SCRAPERS: dict[str, Callable[..., list[Boost]]] = {
    "oddschecker": parse_oddschecker,
    "skybet": parse_skybet,
    "bet365": parse_bet365,
    "williamhill": parse_williamhill,
    "paddypower": parse_paddypower,
}
