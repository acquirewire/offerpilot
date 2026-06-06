# Ticket Drop Monitor

Polls London clubbing event pages (Fatsoma, Milkshake) for ticket-tier state
changes (e.g. `Coming Soon` / `Sold Out` -> `Buy`, or a brand-new release
appearing) and fires an **SMS + email** alert with a direct link the instant a
change is detected.

This is a **monitor-and-alert** tool. It notifies *you* so you can buy
manually. It does not auto-purchase.

## How it works

```
              ┌──────────────┐
              │  main.py     │  asyncio loop, one task per target,
              │  scheduler   │  jittered 30–60s interval + backoff
              └──────┬───────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
  ┌───────────┐            ┌──────────────┐
  │ Fetcher   │            │ Fetcher      │
  │ (HTTP/2)  │  fallback  │ (Playwright  │
  │ httpx     │ ─────────► │  + stealth)  │
  └─────┬─────┘            └──────┬───────┘
        │  raw html / json        │
        ▼                         ▼
  ┌─────────────────────────────────────┐
  │ Parser (per site)                   │  -> { tier_name: STATUS }
  │ JSON-state first, DOM heuristic 2nd  │
  └──────────────┬──────────────────────┘
                 ▼
        ┌─────────────────┐
        │ Detector        │  diff vs last state -> "drop" events
        │ + State store   │  (atomic JSON file, survives restarts)
        └────────┬────────┘
                 ▼ (only on a real transition)
        ┌─────────────────┐
        │ Notifiers       │  Twilio SMS  +  SMTP/SendGrid email
        └─────────────────┘
```

The design choice that matters: **prefer the JSON API over rendering the page.**
Open the event page in your browser's DevTools → Network tab, find the
`fetch`/XHR that returns the ticket tiers as JSON, and point the parser at that.
Polling a JSON endpoint with `httpx` is faster, lighter, and far less
fingerprintable than a headless browser. The Playwright fetcher is only a
fallback for pages that hard-block plain HTTP.

## Setup

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium        # only needed for the browser fallback

cp .env.example .env               # then fill in your keys
cp config.example.yaml config.yaml # then fill in your target URLs
python -m src.main
```

## Configuration

- `config.yaml` — the list of targets (URLs, site type, fetch method, checkout
  link). See `config.example.yaml`.
- `.env` — secrets (Twilio, email, proxies). See `.env.example`.

## Adapting the parsers (required)

I cannot ship verified CSS selectors / endpoints for these sites — they change,
and they vary per event. Each parser (`src/parsers/*.py`) has a clearly marked
`# TODO: VERIFY AGAINST LIVE PAGE` block. Steps:

1. Open the event page, DevTools → Network, filter to `Fetch/XHR`.
2. Reload. Find the response that contains the ticket tiers / "Sold Out" text.
3. If it's JSON → set `fetch.method: http` and map the fields in the parser.
4. If only the rendered HTML has it → set `fetch.method: browser` and adjust the
   DOM selectors / status keywords.

## Deployment

A small always-on Linux VPS with **systemd** is the right home — not serverless.
The process is long-running and stateful (it remembers the last seen state), and
a stealth browser can't cold-start inside a Lambda cleanly. See
`deploy/ticket-monitor.service`.

## Responsible use

- Respect each event's terms of service. Some prohibit automated access.
- Keep the interval reasonable (30–60s is plenty). Don't hammer.
- This alerts you to buy manually; it is not a bulk-purchase bot.
