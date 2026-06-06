"""Auto-discover which firms have a public Greenhouse or Lever job board.

Big banks on Workday can't be guessed (tenant URLs are opaque), but a large
share of funds / trading firms / fintechs use Greenhouse or Lever, whose public
APIs have *guessable* tokens derived from the firm name:

    Greenhouse : https://boards-api.greenhouse.io/v1/boards/<token>/jobs
    Lever      : https://api.lever.co/v0/postings/<token>?mode=json

For each firm we try a few candidate tokens, and for every hit we fetch the
board's own name and fuzzy-match it against the firm name to reject coincidental
collisions. Output is paste-ready config plus a review table flagging weak name
matches so you can eyeball them.

Run:  python -m jobtracker.discover --firms jobtracker/firms.txt --out jobtracker/discovered.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import re

import httpx

try:
    from rapidfuzz import fuzz
    def _name_match(a: str, b: str) -> int:
        return int(fuzz.token_set_ratio(a.lower(), b.lower()))
except ImportError:
    from difflib import SequenceMatcher
    def _name_match(a: str, b: str) -> int:
        return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)

GH_JOBS = "https://boards-api.greenhouse.io/v1/boards/{tok}/jobs"
GH_META = "https://boards-api.greenhouse.io/v1/boards/{tok}"
LEVER = "https://api.lever.co/v0/postings/{tok}?mode=json"

# Company-name noise we strip when forming a short candidate token.
_SUFFIXES = {
    "group", "capital", "partners", "management", "advisors", "advisory",
    "asset", "investments", "investment", "securities", "global", "international",
    "llp", "plc", "ltd", "co", "company", "trading", "technologies", "holdings",
    "markets", "bank", "insurance", "fund", "associates", "and",
}


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def candidates(firm: str) -> list[str]:
    """A few plausible board tokens for a firm name, most specific first."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", firm) if w]
    full = _alnum(firm)
    core = "".join(w for w in words if w.lower() not in _SUFFIXES).lower()
    core = _alnum(core)
    first = words[0].lower() if words else ""
    out: list[str] = []
    for c in (full, core, first):
        if c and len(c) >= 3 and c not in out:
            out.append(c)
    return out[:3]


async def _try_greenhouse(client, firm, tok) -> dict | None:
    try:
        r = await client.get(GH_JOBS.format(tok=tok))
        if r.status_code != 200:
            return None
        jobs = r.json().get("jobs", [])
        if not jobs:
            return None
        meta = await client.get(GH_META.format(tok=tok))
        board_name = meta.json().get("name", tok) if meta.status_code == 200 else tok
        return {
            "firm": firm, "ats": "greenhouse", "token": tok,
            "jobs": len(jobs), "board_name": board_name,
            "score": _name_match(firm, board_name),
            "url": GH_JOBS.format(tok=tok) + "?content=true",
        }
    except Exception:
        return None


async def _try_lever(client, firm, tok) -> dict | None:
    try:
        r = await client.get(LEVER.format(tok=tok))
        if r.status_code != 200:
            return None
        postings = r.json()
        if not isinstance(postings, list) or not postings:
            return None
        return {
            "firm": firm, "ats": "lever", "token": tok,
            "jobs": len(postings), "board_name": tok,
            "score": _name_match(firm, tok),
            "url": f"https://api.lever.co/v0/postings/{tok}?mode=json",
        }
    except Exception:
        return None


async def discover(firms: list[str], concurrency: int = 20) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    hits: dict[str, dict] = {}      # firm -> best hit

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        async def probe(firm: str, coro_factory, tok):
            async with sem:
                res = await coro_factory(client, firm, tok)
            if res and (firm not in hits or res["jobs"] > hits[firm]["jobs"]):
                # Prefer a strong name match; keep best-scoring/most-jobs hit.
                if firm not in hits or res["score"] >= hits[firm]["score"]:
                    hits[firm] = res

        tasks = []
        for firm in firms:
            for tok in candidates(firm):
                tasks.append(probe(firm, _try_greenhouse, tok))
                tasks.append(probe(firm, _try_lever, tok))
        await asyncio.gather(*tasks)

    return sorted(hits.values(), key=lambda h: (-h["score"], h["firm"]))


def _slug(firm: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", firm) if w]
    return "".join(w[:1].upper() + w[1:] for w in words)


def is_confident(h: dict, min_score: int) -> bool:
    """Greenhouse hits are board-name-verified; Lever has no name to check, so
    those always need a human eyeball regardless of the (token-based) score."""
    return h["ats"] == "greenhouse" and h["score"] >= min_score


def _entry(h: dict, comment_out: bool) -> list[str]:
    pre = "  # " if comment_out else "  "
    flag = "   # ⚠ VERIFY board name below" if comment_out else ""
    return [
        f'{pre}- name: "{h["firm"]}"{flag}',
        f'{pre}  slug: "{_slug(h["firm"])}"',
        f'{pre}  ats: {h["ats"]}',
        f'{pre}  url: "{h["url"]}"',
        f'{pre}  # board: "{h["board_name"]}"  jobs={h["jobs"]}  match={h["score"]}',
    ]


def emit_yaml(hits: list[dict], min_score: int) -> str:
    confident = [h for h in hits if is_confident(h, min_score)]
    verify = [h for h in hits if not is_confident(h, min_score)]
    lines = ["# Auto-discovered firms. Confident (Greenhouse, name-verified) are active.",
             "firms:"]
    for h in confident:
        lines += _entry(h, comment_out=False)
    if verify:
        lines += ["", "# --- NEEDS VERIFICATION (Lever = no name check, or weak match). ---",
                  "# Open the url; if it's really the firm, uncomment and move above."]
        for h in verify:
            lines += _entry(h, comment_out=True)
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--firms", required=True)
    p.add_argument("--out", default="jobtracker/discovered.yaml")
    p.add_argument("--min-score", type=int, default=70,
                   help="flag hits whose board-name match is below this")
    args = p.parse_args(argv)

    with open(args.firms, encoding="utf-8") as fh:
        firms = [ln.strip() for ln in fh if ln.strip()]

    hits = asyncio.run(discover(firms))
    yaml_text = emit_yaml(hits, args.min_score)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(yaml_text)

    strong = [h for h in hits if is_confident(h, args.min_score)]
    weak = [h for h in hits if not is_confident(h, args.min_score)]
    print(f"probed {len(firms)} firms")
    print(f"  {len(strong)} confident (Greenhouse, name-verified), {len(weak)} need verify, "
          f"{len(firms) - len(hits)} not found (likely Workday/own ATS)")
    print(f"  -> {args.out}")
    print("\nConfident (added to config, active):")
    for h in strong:
        print(f"  {h['firm']:32} {h['token']:24} jobs={h['jobs']:<4} board='{h['board_name']}'")
    if weak:
        print("\nNeeds verification (commented out in config — open the url to confirm):")
        for h in weak:
            print(f"  {h['firm']:32} -> '{h['board_name']}' ({h['ats']}/{h['token']}) match={h['score']}")


if __name__ == "__main__":
    main()
