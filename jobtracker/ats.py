"""Mock ATS Scanner (Module 3).

Compares a generated CV against a target job description and reports a keyword
match rate plus the specific required skills that are missing. Deterministic and
fast -- no LLM call -- so you can gate document tailoring on it cheaply.

Matching is fuzzy: "DCF modelling" in the JD is satisfied by "built DCF models"
in the CV. Uses rapidfuzz when installed; falls back to stdlib difflib so the
scanner runs with zero extra dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

try:  # optional accelerator
    from rapidfuzz import fuzz

    def _ratio(a: str, b: str) -> float:
        return fuzz.partial_ratio(a, b) / 100.0
except ImportError:  # stdlib fallback
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


# Curated high-finance skill lexicon. Each entry is a canonical skill plus the
# surface forms an ATS / recruiter would accept for it. Extend per target role.
SKILL_LEXICON: dict[str, list[str]] = {
    "Financial Modeling": ["financial model", "three statement", "3-statement"],
    "DCF": ["dcf", "discounted cash flow"],
    "LBO": ["lbo", "leveraged buyout"],
    "Valuation": ["valuation", "comparable compan", "trading comps", "precedent transaction"],
    "M&A": ["m&a", "mergers and acquisitions", "merger"],
    "Excel": ["excel", "spreadsheet"],
    "VBA": ["vba", "macro"],
    "PowerPoint": ["powerpoint", "pitch book", "pitchbook"],
    "Bloomberg": ["bloomberg", "bloomberg terminal"],
    "Capital IQ": ["capital iq", "capiq", "s&p capital"],
    "Python": ["python"],
    "SQL": ["sql"],
    "Accounting": ["accounting", "gaap", "ifrs"],
    "Equity Research": ["equity research", "sell-side research"],
    "Due Diligence": ["due diligence", "diligence"],
    "Cantonese": ["cantonese"],
    "Mandarin": ["mandarin", "putonghua"],
    "French": ["french"],
    "CFA": ["cfa", "chartered financial analyst"],
}

# JD phrases that mark a skill as REQUIRED rather than merely nice-to-have.
_REQUIRED_MARKERS = (
    "required", "must have", "must-have", "essential", "minimum", "you have",
    "you will need", "proficiency in", "fluent", "strong",
)

_WORD_RE = re.compile(r"[a-z0-9&+\-]+")


def _norm(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def _present(surface_forms: list[str], cv: str, threshold: float) -> bool:
    """True if any surface form of a skill appears (fuzzily) in the CV."""
    for form in surface_forms:
        if form in cv:                       # exact substring -> cheap win
            return True
        if _ratio(form, cv) >= threshold:    # fuzzy fallback
            return True
    return False


def extract_required_skills(jd_text: str) -> list[str]:
    """Canonical skills the JD mentions, prioritizing ones near a 'required' cue."""
    jd = _norm(jd_text)
    found: list[str] = []
    for skill, forms in SKILL_LEXICON.items():
        if any(f in jd for f in forms):
            found.append(skill)
    # Order: required-marker-adjacent skills first, so the missing-flag is loud
    # about genuine blockers.
    def near_marker(skill: str) -> int:
        for f in SKILL_LEXICON[skill]:
            idx = jd.find(f)
            if idx == -1:
                continue
            window = jd[max(0, idx - 60): idx + 60]
            if any(m in window for m in _REQUIRED_MARKERS):
                return 0
        return 1

    return sorted(found, key=near_marker)


@dataclass
class ATSResult:
    match_pct: float                 # 0..1, share of JD-required skills present in CV
    matched: list[str]
    missing: list[str]               # the custom flag: required skills not evidenced

    @property
    def flag(self) -> str:
        if not self.missing:
            return "PASS — all required skills evidenced"
        return "MISSING: " + ", ".join(self.missing)


def scan(cv_text: str, jd_text: str, *, fuzzy_threshold: float = 0.86) -> ATSResult:
    """Score a CV against a JD. Returns match rate + missing-skill flags."""
    cv = _norm(cv_text)
    required = extract_required_skills(jd_text)
    if not required:
        return ATSResult(match_pct=1.0, matched=[], missing=[])

    matched, missing = [], []
    for skill in required:
        if _present(SKILL_LEXICON[skill], cv, fuzzy_threshold):
            matched.append(skill)
        else:
            missing.append(skill)

    return ATSResult(
        match_pct=round(len(matched) / len(required), 3),
        matched=matched,
        missing=missing,
    )


def jd_terms(jd_text: str) -> list[str]:
    """Skill surface-forms that appear in the JD — used to highlight matches in
    the CV. Longest first so multi-word phrases highlight before their parts."""
    jd = _norm(jd_text)
    terms: set[str] = set()
    for forms in SKILL_LEXICON.values():
        for f in forms:
            if f in jd:
                terms.add(f)
    return sorted(terms, key=len, reverse=True)


def highlight_html(text: str, terms: list[str]) -> str:
    """HTML-escape `text` and wrap any JD term occurrences in <mark>."""
    import html as _html

    out = _html.escape(text)
    for t in terms:
        out = re.sub(rf"(?i)({re.escape(_html.escape(t))})", r"<mark>\1</mark>", out)
    return out


def bullet_hits(text: str, terms: list[str]) -> int:
    """How many distinct JD terms a bullet references (0 = generic / off-target)."""
    low = text.lower()
    return sum(1 for t in terms if t in low)


# --- JD-driven coverage (requirements parsed from the JD, not a fixed lexicon) --

def evidenced(cv_text: str, surface_forms: list[str], *, fuzzy_threshold: float = 0.88) -> bool:
    """True if the CV shows any surface form of a requirement (exact or fuzzy)."""
    return _present([f.lower() for f in surface_forms if f], _norm(cv_text), fuzzy_threshold)


@dataclass
class Requirement:
    label: str
    terms: list[str]
    covered: bool


@dataclass
class CoverageReport:
    """Coverage of the requirements parsed from a specific JD."""

    hard: list[Requirement]    # technical skills / methods / domain knowledge
    soft: list[Requirement]    # competencies / attributes

    @staticmethod
    def _pct(items: list[Requirement]) -> float:
        return round(sum(r.covered for r in items) / len(items), 3) if items else 1.0

    @property
    def hard_pct(self) -> float:
        return self._pct(self.hard)

    @property
    def soft_pct(self) -> float:
        return self._pct(self.soft)

    @property
    def overall_pct(self) -> float:
        # hard skills weigh more than competencies in a real screen
        return round(0.7 * self.hard_pct + 0.3 * self.soft_pct, 3)


def check_coverage(cv_text: str, requirements: dict) -> CoverageReport:
    """Deterministically check the CV against JD requirements (see tailor.extract_
    requirements). No LLM here, so it's free to re-run after manual edits."""
    def build(items) -> list[Requirement]:
        out = []
        for it in items or []:
            terms = [t.lower() for t in (it.get("terms") or [])] or [it.get("label", "").lower()]
            out.append(Requirement(it.get("label", "?"), terms, evidenced(cv_text, terms)))
        return out

    return CoverageReport(build(requirements.get("hard")), build(requirements.get("soft")))
