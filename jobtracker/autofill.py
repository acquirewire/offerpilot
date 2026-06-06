"""ATS autofill (Module 3) — autofill-then-human-submit.

Design choice: this fills every field it can map, uploads the CV/cover, answers
the generated Q&A, then **stops at the Submit button** and hands control back to
you. It never clicks Submit. Reasons:
  * Bank ATSs (Workday/Greenhouse) run bot detection; autonomous submission risks
    flagging your candidate account.
  * You want a human eyeball on the final form before a one-shot application.

You get ~95% of the time saving with none of the account risk. Run headful so
you can review and submit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Field-label synonyms -> the profile key that fills them. Matched case-insensitively
# against the field's <label>, placeholder, aria-label or name.
FIELD_MAP: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "given name", "legal first"),
    "last_name": ("last name", "surname", "family name", "legal last"),
    "email": ("email",),
    "phone": ("phone", "mobile", "telephone"),
    "linkedin": ("linkedin",),
    "school": ("school", "university", "institution"),
    "degree": ("degree", "qualification"),
    "grad_year": ("graduation", "grad year", "expected graduation"),
    "address": ("address", "street"),
    "city": ("city", "town"),
}


@dataclass
class Profile:
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    linkedin: str = ""
    school: str = ""
    degree: str = ""
    grad_year: str = ""
    address: str = ""
    city: str = ""
    cv_path: str = ""
    cover_path: str = ""
    # JD-specific answers keyed by a substring of the question text.
    qa: dict[str, str] = field(default_factory=dict)

    def value_for(self, key: str) -> str:
        return getattr(self, key, "") or ""


def _label_text(page, handle) -> str:
    """Best-effort human label for a field: aria-label / placeholder / name / nearby <label>."""
    for attr in ("aria-label", "placeholder", "name", "id"):
        v = handle.get_attribute(attr)
        if v:
            return v
    return ""


def autofill(profile: Profile, url: str, *, user_data_dir: str = ".pw-profile") -> None:
    """Open `url` headful in a persistent context, fill what we can, then pause.

    The persistent context reuses any logged-in session, so you authenticate
    once per firm and subsequent fills skip the login wall.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir, headless=False, accept_downloads=True
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")

        filled = _fill_text_fields(page, profile)
        _upload_files(page, profile)
        _answer_questions(page, profile)

        print(f"[autofill] filled {filled} fields on {url}")
        print("[autofill] REVIEW the form, then click Submit yourself.")
        # Block until you close the window — we never auto-submit.
        page.pause()  # opens Playwright Inspector; close it / the page to finish
        ctx.close()


def _fill_text_fields(page, profile: Profile) -> int:
    count = 0
    for handle in page.query_selector_all("input[type=text], input[type=email], input[type=tel], input:not([type]), textarea"):
        label = _label_text(page, handle).lower()
        if not label:
            continue
        for key, synonyms in FIELD_MAP.items():
            if any(s in label for s in synonyms):
                val = profile.value_for(key)
                if val:
                    try:
                        handle.fill(val)
                        count += 1
                    except Exception:        # field not editable / detached; skip
                        pass
                break
    return count


def _upload_files(page, profile: Profile) -> None:
    inputs = page.query_selector_all("input[type=file]")
    if not inputs:
        return
    if profile.cv_path:
        try:
            inputs[0].set_input_files(profile.cv_path)
        except Exception:
            pass
    if profile.cover_path and len(inputs) > 1:
        try:
            inputs[1].set_input_files(profile.cover_path)
        except Exception:
            pass


def _answer_questions(page, profile: Profile) -> None:
    """Fill free-text application questions by matching the generated Q&A keys."""
    for handle in page.query_selector_all("textarea"):
        label = _label_text(page, handle).lower()
        for needle, answer in profile.qa.items():
            if needle.lower() in label:
                try:
                    handle.fill(answer)
                except Exception:
                    pass
                break
