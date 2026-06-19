#!/usr/bin/env python3
"""Gmail bulk-unsubscribe helper.

Scans your recent inbox, ranks the senders that mail you the most (and that
expose a real unsubscribe mechanism), then walks you through them one at a
time. For each sender you see who they are, the subject + first line of their
latest email, and a simple y/n. Nothing happens to your mailbox without your
explicit key-press for that sender.

Run:  python unsub.py
First-run setup is in README.md (you need a credentials.json from Google).
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import time
import webbrowser
from collections import OrderedDict
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(HERE, "token.json")
CREDS_PATH = os.path.join(HERE, "credentials.json")
LOG_PATH = os.path.join(HERE, "unsub_log.csv")

# gmail.modify = read + change labels/archive (NOT permanent delete).
# gmail.send   = needed only for mailto:-style unsubscribe requests.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# ---- dependency check -------------------------------------------------------
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import requests
except ImportError as e:  # pragma: no cover
    sys.exit(
        f"Missing dependency ({e.name}).\n"
        f"Install them first:\n    pip install -r {os.path.join(HERE, 'requirements.txt')}"
    )


# ---- auth -------------------------------------------------------------------
def get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                sys.exit(
                    f"\nNo credentials.json found in {HERE}\n"
                    "Follow the one-time setup in README.md to download it from\n"
                    "Google Cloud Console, then run this script again."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            print("A browser window will open so you can authorise access to your Gmail.")
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


# ---- scanning ---------------------------------------------------------------
def list_message_ids(service, query, max_scan):
    ids = []
    page_token = None
    while len(ids) < max_scan:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(500, max_scan - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_scan]


WANT_HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "List-Unsubscribe-Post"]


def fetch_metadata(service, ids):
    """Batch-fetch metadata for many message ids. Returns list of dicts."""
    out = []

    def _cb(_request_id, response, exception):
        if exception is not None:
            return
        headers = {
            h["name"].lower(): h["value"]
            for h in response.get("payload", {}).get("headers", [])
        }
        out.append(
            {
                "id": response.get("id"),
                "snippet": response.get("snippet", "").strip(),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "list_unsub": headers.get("list-unsubscribe", ""),
                "list_unsub_post": headers.get("list-unsubscribe-post", ""),
            }
        )

    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        batch = service.new_batch_http_request(callback=_cb)
        for mid in chunk:
            batch.add(
                service.users().messages().get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=WANT_HEADERS,
                )
            )
        batch.execute()
        print(f"  scanned {min(start + 50, len(ids))}/{len(ids)} messages", end="\r")
    print(" " * 60, end="\r")
    return out


def aggregate(messages):
    """Group messages by sender email. Keep the most recent sample + unsub info."""
    senders = OrderedDict()
    for m in messages:
        name, addr = parseaddr(m["from"])
        addr = addr.lower()
        if not addr:
            continue
        s = senders.get(addr)
        if s is None:
            s = {
                "email": addr,
                "name": name or addr,
                "count": 0,
                "ids": [],
                "sample": m,
                "list_unsub": m["list_unsub"],
                "list_unsub_post": m["list_unsub_post"],
            }
            senders[addr] = s
        s["count"] += 1
        s["ids"].append(m["id"])
        # keep the message with a List-Unsubscribe header as the sample/unsub source
        if m["list_unsub"] and not s["list_unsub"]:
            s["list_unsub"] = m["list_unsub"]
            s["list_unsub_post"] = m["list_unsub_post"]
            s["sample"] = m
    return senders


# ---- unsubscribe mechanics --------------------------------------------------
_LINK_RE = re.compile(r"<\s*([^>]+?)\s*>")


def parse_unsub_targets(list_unsub_header):
    """Return (https_urls, mailto_targets) from a List-Unsubscribe header."""
    https, mailto = [], []
    for raw in _LINK_RE.findall(list_unsub_header or ""):
        raw = raw.strip()
        if raw.lower().startswith("mailto:"):
            mailto.append(raw[len("mailto:") :])
        elif raw.lower().startswith("http"):
            https.append(raw)
    return https, mailto


def one_click_unsubscribe(url):
    """RFC 8058 one-click POST. Returns True on a 2xx response."""
    try:
        r = requests.post(
            url,
            data={"List-Unsubscribe": "One-Click"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        return 200 <= r.status_code < 300
    except requests.RequestException:
        return False


def send_mailto_unsubscribe(service, mailto_target, my_address):
    """Send the unsubscribe email Gmail-side. mailto_target may carry ?subject=."""
    to_addr, subject, body = mailto_target, "unsubscribe", "unsubscribe"
    if "?" in mailto_target:
        to_addr, _, query = mailto_target.partition("?")
        for part in query.split("&"):
            k, _, v = part.partition("=")
            if k.lower() == "subject":
                subject = unquote(v)
            elif k.lower() == "body":
                body = unquote(v)
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["From"] = my_address
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except HttpError:
        return False


def do_unsubscribe(service, sender, my_address):
    """Attempt to unsubscribe. Returns (status_str, detail)."""
    https, mailto = parse_unsub_targets(sender["list_unsub"])
    one_click = "one-click" in (sender["list_unsub_post"] or "").lower()

    # 1. Preferred: silent one-click POST (RFC 8058)
    if https and one_click:
        if one_click_unsubscribe(https[0]):
            return "done", f"one-click POST {https[0]}"

    # 2. mailto: we can send this ourselves, no browser needed
    if mailto:
        if send_mailto_unsubscribe(service, mailto[0], my_address):
            return "done", f"emailed {mailto[0]}"

    # 3. Fall back to opening the unsubscribe page in your browser
    if https:
        webbrowser.open(https[0])
        return "browser", f"opened {https[0]} — finish it in your browser if needed"

    return "manual", "no usable unsubscribe target found"


def archive_sender(service, sender):
    """Remove these messages from the inbox (archive). Not a delete."""
    ids = sender["ids"]
    archived = 0
    for start in range(0, len(ids), 1000):
        chunk = ids[start : start + 1000]
        try:
            service.users().messages().batchModify(
                userId="me",
                body={"ids": chunk, "removeLabelIds": ["INBOX"]},
            ).execute()
            archived += len(chunk)
        except HttpError:
            pass
    return archived


# ---- presentation -----------------------------------------------------------
def truncate(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def log_action(sender, action, detail):
    new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", encoding="utf-8", newline="") as f:
        if new:
            f.write("timestamp,sender,count,action,detail\n")
        safe_detail = detail.replace('"', "'")
        f.write(
            f'{datetime.now().isoformat(timespec="seconds")},'
            f'"{sender["email"]}",{sender["count"]},{action},"{safe_detail}"\n'
        )


def main():
    ap = argparse.ArgumentParser(description="Walk through your noisiest senders and unsubscribe.")
    ap.add_argument("--scan", type=int, default=600,
                    help="how many recent messages to scan (default 600)")
    ap.add_argument("--query", default="category:promotions OR category:updates OR unsubscribe",
                    help="Gmail search to scope the scan")
    ap.add_argument("--min-count", type=int, default=2,
                    help="only show senders with at least this many emails (default 2)")
    ap.add_argument("--top", type=int, default=40,
                    help="max number of senders to review (default 40)")
    args = ap.parse_args()

    service = get_service()
    profile = service.users().getProfile(userId="me").execute()
    my_address = profile["emailAddress"]
    print(f"Signed in as {my_address}\n")

    print(f"Scanning up to {args.scan} recent messages …")
    ids = list_message_ids(service, args.query, args.scan)
    if not ids:
        print("No messages matched. Try a broader --query, e.g. --query \"\".")
        return
    messages = fetch_metadata(service, ids)
    senders = aggregate(messages)

    # Only senders that actually offer an unsubscribe mechanism, ranked by volume.
    candidates = [
        s for s in senders.values()
        if s["list_unsub"] and s["count"] >= args.min_count
    ]
    candidates.sort(key=lambda s: s["count"], reverse=True)
    candidates = candidates[: args.top]

    if not candidates:
        print("No unsubscribable bulk senders found in that scan. "
              "Try increasing --scan or lowering --min-count.")
        return

    total = len(candidates)
    print(f"\nFound {total} bulk sender(s) with an unsubscribe option.\n")
    print("For each one:  [y] unsubscribe + archive its emails   [u] unsubscribe only")
    print("               [n] skip   [s] skip all rest   [q] quit\n")

    done = 0
    for i, sender in enumerate(candidates, 1):
        sample = sender["sample"]
        print("─" * 70)
        print(f"[{i}/{total}]  {truncate(sender['name'], 45)}")
        print(f"           {sender['email']}")
        print(f"           {sender['count']} emails in the scanned set")
        print(f"   Latest:  {truncate(sample['subject'], 60)}")
        print(f"            “{truncate(sample['snippet'], 90)}”")
        try:
            choice = input("   Unsubscribe? [y/u/n/s/q] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nStopping.")
            break

        if choice == "q":
            break
        if choice == "s":
            print("Skipping the rest.")
            break
        if choice not in ("y", "u"):
            log_action(sender, "skipped", "")
            continue

        status, detail = do_unsubscribe(service, sender, my_address)
        if status == "done":
            print(f"   ✓ Unsubscribed ({detail})")
        elif status == "browser":
            print(f"   → {detail}")
        else:
            print(f"   ! Could not auto-unsubscribe: {detail}")

        archived = 0
        if choice == "y":
            archived = archive_sender(service, sender)
            print(f"   ✓ Archived {archived} email(s) from your inbox")

        log_action(sender, status if choice == "u" else f"{status}+archived{archived}", detail)
        done += 1
        time.sleep(0.3)  # be gentle on unsubscribe endpoints

    print("─" * 70)
    print(f"\nProcessed {done} sender(s). Full record: {LOG_PATH}")
    print("Note: a few senders are slow to stop — give legit lists a couple of days.")


if __name__ == "__main__":
    main()
