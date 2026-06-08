"""Measure how CV bullet text wraps on the page, so rewrites fill clean lines.

The rule we enforce: every bullet should wrap to EXACTLY one full line, or to a
nearly-full two lines — never the ugly in-between (a line and a quarter), and
never more than two (which would push the CV past one page).

We measure real wrap width using Pillow + the document's actual font, so the
character budgets we hand the model are accurate rather than guessed. Falls back
to a rough character estimate if Pillow/the font isn't available.
"""
from __future__ import annotations

import os
from functools import lru_cache

# docx font name -> candidate TTF filenames, Windows first then the Linux
# metric-compatible equivalents (Carlito≈Calibri, Liberation≈Arial/Times). This
# keeps line measurement accurate on the Linux host the same as on Windows.
_FONTS = {
    "Calibri": ["calibri.ttf", "Carlito-Regular.ttf"],
    "Calibri Light": ["calibril.ttf", "Carlito-Regular.ttf"],
    "Arial": ["arial.ttf", "LiberationSans-Regular.ttf"],
    "Helvetica": ["arial.ttf", "LiberationSans-Regular.ttf"],
    "Times New Roman": ["times.ttf", "LiberationSerif-Regular.ttf"],
    "Cambria": ["cambria.ttc", "Caladea-Regular.ttf", "LiberationSerif-Regular.ttf"],
    "Georgia": ["georgia.ttf", "LiberationSerif-Regular.ttf"],
    "Verdana": ["verdana.ttf", "DejaVuSans.ttf"],
    "Tahoma": ["tahoma.ttf", "DejaVuSans.ttf"],
    "Garamond": ["GARA.TTF", "LiberationSerif-Regular.ttf"],
    "Book Antiqua": ["BKANT.TTF", "LiberationSerif-Regular.ttf"],
}
_FALLBACK_FILES = ["Carlito-Regular.ttf", "DejaVuSans.ttf", "calibri.ttf"]
_FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/usr/share/fonts/truetype/crosextra",   # Carlito / Caladea
    "/usr/share/fonts/truetype/liberation",  # Liberation Sans/Serif
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts",
]

try:
    from PIL import ImageFont
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False


def _find_font_path(name: str) -> str | None:
    """First existing TTF for `name` across Windows + Linux font dirs."""
    for fname in _FONTS.get(name, []) + _FALLBACK_FILES:
        for d in _FONT_DIRS:
            p = os.path.join(d, fname)
            if os.path.exists(p):
                return p
    return None


@lru_cache(maxsize=32)
def _font(name: str, size_pt: int):
    path = _find_font_path(name)
    if path is None:
        raise FileNotFoundError(name)   # _width() falls back to the char estimate
    return ImageFont.truetype(path, max(size_pt, 1))


def _width(text: str, name: str, size_pt: float) -> float:
    """Rendered width of text. Points and pixels share one scale here, so the
    ratio against the page width (also in points) is what matters, not the unit."""
    if _HAVE_PIL:
        try:
            return _font(name, int(round(size_pt))).getlength(text)
        except Exception:
            pass
    return len(text) * size_pt * 0.5   # rough fallback: ~0.5em average glyph


def wrap_info(text: str, width_pt: float, name: str = "Calibri",
              size_pt: float = 11.0) -> tuple[int, float]:
    """Greedy word-wrap. Returns (line_count, last_line_fill_fraction)."""
    words = text.split()
    if not words:
        return (0, 0.0)
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if not cur or _width(trial, name, size_pt) <= width_pt:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    last_frac = _width(lines[-1], name, size_pt) / width_pt if width_pt else 0.0
    return (len(lines), last_frac)


def chars_per_line(width_pt: float, name: str = "Calibri", size_pt: float = 11.0) -> int:
    sample = "the quick brown fox jumps over the lazy dog and then runs"
    avg = _width(sample, name, size_pt) / len(sample)
    return max(int(width_pt / avg), 12) if avg else 80


def is_clean(n_lines: int, last_frac: float, target_lines: int) -> bool:
    """Clean = lands on the target line count, with the last line acceptably full,
    and never spilling past two lines. A two-line target that collapses to one
    line is NOT clean — we don't shorten a bullet that had room to stay full."""
    if n_lines > 2 or n_lines != target_lines:
        return False
    return last_frac >= 0.5   # last line at least ~half full -> no stub, no over-compress


def char_budget(target_lines: int, cpl: int) -> tuple[int, int]:
    """Character range that fills `target_lines` cleanly, for the rewrite prompt.

    The lower bound makes the model USE the available space (so a two-line bullet
    stays ~two lines), the upper bound leaves a margin so it fits without trimming."""
    if target_lines == 1:
        return (int(cpl * 0.62), int(cpl * 0.90))   # comfortably one line
    return (int(cpl * 1.60), int(cpl * 1.92))        # fill ~1.6–1.9 lines, not collapse to 1
