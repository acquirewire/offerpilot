# mailclean — Gmail bulk-unsubscribe helper

A small local tool that scans your inbox, finds the senders that mail you most
(and that offer a real unsubscribe option), and walks you through them **one at
a time**. For each sender you see who they are and the first line of their
latest email, then press a single key. Nothing touches your mailbox without
your explicit yes for that sender.

Everything runs on your machine with your own Google credentials. No data
leaves your computer except the unsubscribe request itself.

---

## One-time setup (~5 minutes)

### 1. Install the Python packages
```powershell
cd C:\Users\henry\reselling\mailclean
pip install -r requirements.txt
```

### 2. Get a Google OAuth credential
You need a `credentials.json` so the script can ask *your* permission to read
your Gmail. This is free.

1. Go to <https://console.cloud.google.com/> and create a project (or pick one).
2. **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** (fine for personal use).
   - Fill in app name + your email where required, save.
   - Under **Audience / Test users**, add your own Gmail address as a test user.
     (Test mode is all you need — no Google review required.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app** → Create.
   - **Download JSON**, rename it to `credentials.json`, and put it in this
     `mailclean` folder.

### 3. Run it
```powershell
python unsub.py
```
The first run opens your browser to authorise access. After that a `token.json`
is saved here so you won't be asked again.

---

## What you'll see

```
[3/40]  Some Retailer
        news@email.someretailer.com
        12 emails in the scanned set
   Latest:  50% OFF EVERYTHING ENDS TONIGHT
            "Don't miss our biggest sale of the season, shop now before..."
   Unsubscribe? [y/u/n/s/q]
```

| key | action |
|-----|--------|
| `y` | unsubscribe **and** archive that sender's existing emails out of your inbox |
| `u` | unsubscribe only (leave the old emails where they are) |
| `n` | skip this sender |
| `s` | skip all the rest and stop |
| `q` | quit |

Every decision is written to `unsub_log.csv` so you have a record.

### How the unsubscribe actually happens
The script uses the standard `List-Unsubscribe` header that legitimate bulk
senders include:
1. **One-click** (RFC 8058) — a silent HTTPS request, done instantly.
2. **mailto** — sends the unsubscribe email from your account for you.
3. **Link only** — opens the sender's unsubscribe page in your browser to finish.

> It only ever shows senders that publish an unsubscribe header, which keeps you
> away from the "clicking unsubscribe confirms my address" trap that pure spam
> uses. For genuine spam with no legit unsubscribe, archive/block with a Gmail
> filter instead.

---

## Useful options
```powershell
python unsub.py --scan 1500          # look further back (more messages)
python unsub.py --min-count 5        # only senders with 5+ emails
python unsub.py --top 20             # review at most 20 senders
python unsub.py --query ""           # scan everything, not just promotions/updates
```

`gmail.modify` lets the tool archive (remove from inbox) and read — it can
**not** permanently delete anything. `gmail.send` is used only to send mailto
unsubscribe requests.

## Privacy / cleanup
- `credentials.json` and `token.json` are *yours* — don't commit them.
- To revoke access entirely: delete `token.json`, and remove the app at
  <https://myaccount.google.com/permissions>.
