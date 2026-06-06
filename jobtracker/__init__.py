"""jobtracker — AI job-application & tracking suite.

Modules:
  parsers / diff / monitor   Module 1  Drop Tracker (career-page monitor)
  tailor / naming            Module 2  Document generation & tailoring
  ats / autofill             Module 3  ATS scanner + autofill-then-human-submit
  db / export / dashboard    Module 4  Tracker DB, Excel export, pipeline board
"""
from __future__ import annotations

# Load .env (repo root) so ANTHROPIC_API_KEY, SMTP_*, NTFY_* are available to
# every command without the user exporting them by hand. Same .env as the
# ticket bot. No-op if python-dotenv isn't installed.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

__version__ = "0.1.0"
