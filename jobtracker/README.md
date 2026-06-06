# jobtracker — AI job-application & tracking suite

An automated assistant for high-finance internship hunting (IBD / PE / AM). It
monitors firm career pages for new cycles, tailors application materials, scores
them against the JD, autofills the ATS, and keeps a pristine pipeline database.

Built as a sibling to the Fatsoma ticket monitor in this repo — Module 1 reuses
the same poll → fingerprint → diff → alert pattern (`src/detector.py`).

## Modules

| # | Module | Files | What it does |
|---|--------|-------|--------------|
| 1 | **Drop Tracker** | `parsers.py`, `diff.py`, `monitor.py`, `config.py`, `notify.py` | Polls Workday/Greenhouse JSON endpoints; smart-diffs to alert only on relevant new/opened roles (keyword + region + language filters, incl. Hong Kong/APAC). |
| 2 | **Doc Tailoring** | `tailor.py`, `naming.py` | Rewrites master-CV bullets to the XYZ formula in the original layout (python-docx in-place edits → PDF via LibreOffice); tone-matched cover letters; `First_Last_Firm.pdf` naming. |
| 3 | **ATS** | `ats.py`, `autofill.py` | Mock ATS scanner (keyword match-rate + missing-skill flags); Playwright **autofill-then-human-submit** (never auto-submits). |
| 4 | **Tracker** | `db.py`, `export.py`, `dashboard.py` | SQLite source-of-truth, per-firm application-cap Rule Engine, Excel export, Streamlit pipeline board. |

## Quick start

```powershell
# from repo root, using the existing venv
.venv\Scripts\python.exe -m pip install -r jobtracker\requirements.txt
.venv\Scripts\python.exe -m playwright install chromium

# 1. set up the DB + config
.venv\Scripts\python.exe -m jobtracker init-db
copy jobtracker\config.example.yaml jobtracker\config.yaml   # then edit endpoints

# 2. run the Drop Tracker (Ctrl-C to stop)
.venv\Scripts\python.exe -m jobtracker poll --config jobtracker\config.yaml

# 3. score a CV against a JD
.venv\Scripts\python.exe -m jobtracker scan --cv my_cv.txt --jd jd.txt

# 4. tailor a CV (needs ANTHROPIC_API_KEY + python-docx)
$env:ANTHROPIC_API_KEY="sk-..."
.venv\Scripts\python.exe -m jobtracker tailor --master master.docx --jd jd.txt --name "Henry Smith" --firm "Goldman Sachs"

# 5. autofill an application (headful; you review + click Submit)
.venv\Scripts\python.exe -m jobtracker autofill --url "<apply-url>" --profile jobtracker\profile.yaml

# 6. export the tracker to Excel
.venv\Scripts\python.exe -m jobtracker export --out job_tracker.xlsx

# 7. dashboard
.venv\Scripts\streamlit run jobtracker\dashboard.py
```

## Design notes & honest caveats

- **No autonomous submission.** Bank ATSs run bot detection; auto-submitting risks
  flagging your candidate account. `autofill.py` fills everything and stops at
  Submit for a human. This is deliberate, not a TODO.
- **Respect each site's ToS / robots.** Prefer the JSON endpoints the site itself
  serves; keep poll intervals sane (the default 300s ± jitter is gentle).
- **`req_id` is identity.** The diff keys on the ATS requisition id so a re-rendered
  page reads as "same role," not a new drop. Title is only a fallback.
- **SQLite is the source of truth;** Excel is an exported view, so the monitor can
  write while you read.
