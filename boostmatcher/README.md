# boostmatcher

Find and rate **+EV bookmaker price boosts / superboosts** for matched betting.
A boost is profitable when the boosted BACK price at a bookie beats the LAY
price on an exchange by enough to clear commission. This tool monitors boost
pages, pulls live exchange lay prices, and ranks every boost by guaranteed
locked profit — so you only place the ones worth placing. **You place every
bet manually** (auto-placement gets accounts banned); the tool only finds, prices
and alerts.

## The maths (`rating.py`)
Back £S at boosted price `B`, lay at exchange price `L` with commission `c`:

```
lay_stake = (B * S) / (L - c)
profit_if_back_wins  = S*(B-1) - lay_stake*(L-1)
profit_if_back_loses = lay_stake*(1-c) - S      # equal to the above by construction
rating = 100 * locked_profit / S                # the rank key, % of stake kept
```

`rating >= 0` means at worst break-even with +EV upside; a positive `LOCK` means
both outcomes profit — risk-free. Proven to the penny in `test_rating.py`.

## Try it now (no credentials, no network)
```
python -m boostmatcher demo --html out.html   # rate sample boosts, write the £ dashboard
python -m boostmatcher rate --boosts mine.json --quotes q.json --stake 25 --html out.html
python -m boostmatcher monitor --config config.yaml   # live loop (needs creds + Playwright)
python -m unittest boostmatcher.test_rating boostmatcher.test_instructions \
                   boostmatcher.test_scrapers boostmatcher.test_monitor   # 22 tests
```

`out.html` is a self-contained dashboard: every boost with back stake, **returns
in £**, how much to **lay**, the **liability** to hold, profit under each outcome,
and an expandable step-by-step method. Locks are highlighted green.

## Architecture (mirrors jobtracker)
| Module | Role | Status |
|---|---|---|
| `models.py` | `Boost`, `ExchangeQuote`, `RatedBoost` | done |
| `rating.py` | EV maths, ranking | **done + tested** |
| `instructions.py` | £ lay-plan (stake/lay/liability/profit + steps) | **done + tested** |
| `dashboard.py` | self-contained HTML, returns in £ + method | done |
| `matcher.py` | boost selection -> exchange runner (token Jaccard) | done (heuristic) |
| `dom.py` | tiny stdlib DOM + CSS-ish selectors (class-prefix, attrs, `::attr()`) | **done + tested** |
| `scrapers.py` | bookie boost page -> `Boost[]` (stdlib, SelectorSpec) | **logic tested**; confirm live selectors |
| `exchanges/smarkets.py` | live lay prices (2% comm, free API) | implemented; verify with `SMARKETS_API_TOKEN` |
| `exchanges/betfair.py` | live lay prices (deepest liquidity) | implemented; verify with app key + cert session |
| `monitor.py` | scrape->quote->rate->alert loop + dashboard | **done + tested (fakes)** |
| `notify.py` | ntfy + email alerts (jobtracker env vars) | done |
| `cli.py` | `demo` / `rate` / `monitor` | done |

## Going live — what still needs YOUR input
Everything is built and unit-tested offline. Three things need real-world values
that can't be tested from a dev box, in priority order:
1. **Betfair (free) first** — get the free, self-serve **delayed** app key at
   developer.betfair.com -> `.env` `BETFAIR_APP_KEY`. Get a session token with
   `python -m boostmatcher betfair-login` (interactive: username+password, no
   cert). Verify: `python -m boostmatcher probe --exchange betfair --event "..."`.
   Delayed snapshots are fine for spotting; you lay manually on the live site.
2. **Sky Bet selectors** — open the live super-boosts page in DevTools and replace
   the placeholder selectors in `scrapers.SPECS["skybet"]` with the real ones.
   Verify with `python -m boostmatcher scrape-test --bookie skybet --file saved.html`.
   `parse_with` + odds conversion + the selector engine are tested; only the
   selector strings change. Selector grammar (see `dom.py`), robust to real markup:

   | want to match… | selector |
   |---|---|
   | exact class | `.boost-card` |
   | **hashed class** (`Card_root__a8F2x`) | `.Card_root*` (prefix) |
   | data hook | `[data-test-id=boost-card]` |
   | attribute equals / starts / contains | `[data-x=v]` `[data-x^=v]` `[data-x*=v]` |
   | compound | `span.price[data-odds]` |
   | **odds hidden in an attribute** | `span::attr(aria-label)` / `[data-odds]::attr(data-odds)` |
3. **Smarkets (optional, later)** — lower 2% commission but NOT free/self-serve:
   needs a verified account + one-off £150 admin fee + a manually-approved API
   Request Form. Only worth it if the 2% rate matters to you at volume.

## Honest caveats
- **Player-prop boosts** (anytime scorer, shots-on-target) usually have **no
  exchange runner to lay** — the tool flags them `lay manually`, not as locks.
- **Thin liquidity**: a great rating you can't get matched on isn't real; the
  rater flags when available liquidity < your liability.
- **Scrapers are the maintenance surface** — bookie DOMs change; expect upkeep.
- This is a few-hundred-to-low-thousands-£/season grind, repeatable weekly —
  not a get-rich scheme. Accounts may still get limited ("gubbed") over time.
