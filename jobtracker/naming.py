"""Standardized output filenames (Module 2).

Convention: Firstname_Lastname_FirmSlug.pdf  e.g. Henry_Smith_GoldmanSachs.pdf
Everything is ASCII-folded and punctuation-stripped so the names are safe on
Windows, macOS and ATS upload widgets alike.
"""
from __future__ import annotations

import re
import unicodedata

_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def _token(s: str) -> str:
    """ASCII-fold and strip to a single CamelCase-safe token."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    parts = [p for p in _SAFE_RE.split(s) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def firm_slug(firm_name: str) -> str:
    """'Goldman Sachs' -> 'GoldmanSachs'. Stable key reused in the DB."""
    return _token(firm_name)


def output_filename(
    full_name: str,
    firm_name: str,
    *,
    kind: str = "CV",
    ext: str = "pdf",
) -> str:
    """Build 'First_Last_Firm.ext'. `kind` ('CV'/'Cover') is appended for covers.

    >>> output_filename('Henry Smith', 'Goldman Sachs')
    'Henry_Smith_GoldmanSachs.pdf'
    >>> output_filename('José O\\'Neil', 'J.P. Morgan', kind='Cover', ext='docx')
    'Jose_ONeil_JPMorgan_Cover.docx'
    """
    name_parts = [_token(p) for p in full_name.split() if p.strip()]
    stem = "_".join(name_parts + [firm_slug(firm_name)])
    if kind and kind.upper() != "CV":
        stem += f"_{_token(kind)}"
    return f"{stem}.{ext.lstrip('.')}"
