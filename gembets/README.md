# gembets

Find football (soccer) **"gem bets"** — value bets and statistically mispriced
odds — and push them to your phone via **ntfy**. Five detectors feed one notifier.
**You place every bet manually** (this only finds and alerts); positive-EV betting
is a long-run grind, not risk-free money.

## The detectors

**Four are FREE; only the player-prop one (B) needs paid data.**

**A — Consensus outliers (`outlier.py`) · FREE.** A book's price for an outcome is
flagged when it sits `min_lift` (default 33%) above the *typical* price across the
books — your "majority is 3.0, tell me about 4.0" rule — capped at `max_odds` and
limited to your `allowed_books`. Exchanges feed the consensus but are never flagged.

**C — Goals model (`goals.py`) · FREE.** Builds an INDEPENDENT view of a match from
team scoring strength (Poisson ratings fit from free results data) and flags where
the market's **1X2 / Over-Under 2.5 / BTTS** prices disagree with the model. A true
model gem on the markets the free feed carries. Best for domestic leagues in season.

**D — Line-movement / steam (`steam.py`) · FREE.** Tracks the sharp **exchange**
prices over time; when they steam (move) toward an outcome but one of your books
hasn't followed, the stale soft price is flagged before it corrects. Works for any
competition, including tournaments.

**E — Team-totals model (`totals.py`) · FREE.** One free football-data.co.uk CSV
carries per-match fouls, corners, cards, **booking points**, shots and SOT **and the
referee**. The model prices the fair line for each (cards/booking-points × a referee
factor) and then **auto-spots mispricing against the free Betfair Exchange API**
(`betfair_odds.py`) — Betfair lists Over/Under Goals, Corners and Bookings, so its
prices feed straight into `scan_quotes`. Or use `gembets model` to print fair lines
for a fixture / get an instant verdict on a price. Referee data is EPL; rates need
league history. Betfair auth reuses boostmatcher (`betfair-login`).

**F — Arbitrage (`arb.py`) · FREE.** Pure odds: if the best price per outcome across
your *bookmakers* (exchanges excluded — their commission would erase it) sums under
1, that's a guaranteed locked profit, with the stake split per leg. Opportunistic
and short-lived.

### Money management (not just spotting — sizing, proof, P&L)
- **Kelly staking (`staking.py`)** turns every gem into a £ stake (quarter-Kelly,
  capped at 5% of bank). It's also the final gate: a flagged price that isn't
  genuinely +EV after de-vig gets stake £0 and is **not** alerted — so every alert
  is a real, sized bet.
- **CLV + P&L ledger (`ledger.py`)** logs every bet, auto-captures **closing-line
  value** (did your price beat the close — the only real proof of edge, needs no
  result), and tracks settled P&L/ROI/hit-rate per detector. `gembets report` shows
  it; `gembets settle` records outcomes.
- **Auto-weighting:** a detector whose flags don't beat the close over a real sample
  (`min_clv_sample`) is muted automatically (`clv_cutoff`) — the system kills its own
  noise.

**B — Player fouls (`player_fouls.py`) · FREE.** Your winger-vs-foul-heavy-fullback
gem, now free: **Betfair lists the player-fouls odds** (`PLAYER_FOULS` market) and
**FBref/API-Football give the per-90 rates** for nothing. The model takes a player's
fouls/90, lifts it by the opponent he's matched against, and flags when Betfair's
line is off. (The older paid Sportmonks path is still in `statedge.py` but
superseded.) Player-to-be-carded / shots props fit the same frame next.

## The maths (`odds.py`, pure stdlib incl. Poisson)
```
typical      = median(book_odds across bookmakers)    # the price most books show
lift         = book_odds / typical - 1                # Detector A flag: 4.00 vs 3.00 = +33%
devig        = implied_i / sum(implied)               # strip margin -> fair prob (for context)
P(Over n.5)  = 1 - PoissonCDF(floor(n.5), mu)         # Detector B, mu = modelled rate
```
**Detector A flags when `lift >= min_lift`** (default 33%), the price is under
`max_odds` (default 5.0, so no longshots), and the book is one you use
(`allowed_books`). Exchanges are kept out of the typical price and never flagged
(their margin-free prices aren't soft value). The de-vigged fair prob + EV ride
along in the alert for context. Proven in `test_odds.py` / `test_detectors.py`.

## Try it now (no key, no network)
```
python -m gembets demo                         # both detectors on bundled samples
python -m gembets scan --odds dump.json --stats stats.json
python -m gembets calc --decimal 4.20 --fair-prob 0.26     # EV for one price
# Free multi-market model (cards/corners/fouls/shots) from a free results CSV:
python -m gembets model --csv https://www.football-data.co.uk/mmz4281/2425/E0.csv \
       --home Arsenal --away Chelsea --ref "M Oliver"
python -m gembets model --csv <url> --home Arsenal --away Chelsea \
       --market cards --line 4.5 --odds 2.10        # instant gem verdict on a price
python -m gembets monitor --config config.yaml             # live loop (free defaults)
python -m unittest gembets.test_odds gembets.test_detectors gembets.test_monitor gembets.test_stats \
   gembets.test_sources gembets.test_goals gembets.test_steam gembets.test_totals gembets.test_betfair_odds
# (88 tests)
```
`demo` prints the worked example: a +9.7% away-win outlier (one book at 4.20 vs
a 26% fair consensus), a +20.7% referee-cards edge, and a +19.5% foul-matchup edge.

## Architecture (mirrors boostmatcher / jobtracker)
| Module | Role | Status |
|---|---|---|
| `models.py` | `BookLine`, `MarketSnapshot`, `GemBet` | done |
| `odds.py` | conversions, de-vig, consensus, EV, Poisson | **done + tested** |
| `outlier.py` | Detector A — consensus outliers (FREE) | **done + tested** |
| `goals.py` | Detector C — goals Poisson model -> 1X2/O-U/BTTS (FREE) | **done + tested** |
| `steam.py` | Detector D — line-movement / steam vs exchanges (FREE) | **done + tested** |
| `totals.py` | Detector E — cards/corners/fouls/shots model + referee (FREE) | **done + tested** |
| `betfair_odds.py` | Free Betfair odds: totals + PLAYER_FOULS -> quotes | **normaliser tested**; live needs Betfair creds (`betfair-probe`) |
| `player_fouls.py` | Detector B — player fouls vs Betfair, free (FBref rates) | **done + tested** |
| `statedge.py` | Detector B (legacy, paid props) — superseded by `player_fouls.py` | done + tested |
| `arb.py` | Detector F — guaranteed cross-bookmaker arbitrage (FREE) | **done + tested** |
| `staking.py` | Kelly stake sizing — every alert gets a £ stake + acts as the +EV gate | **done + tested** |
| `ledger.py` | SQLite CLV + P&L log; `report`/`settle` CLI | **done + tested** |
| `odds_api.py` | The Odds API fetch + normaliser -> `MarketSnapshot` | done + quota-aware; live needs `ODDS_API_KEY` |
| `scrape.py` | oddschecker grid -> `MarketSnapshot` (free scrape fallback) | **parser tested**; live selectors are PLACEHOLDERS, calibrate with `scrape-test` |
| `sources.py` | router: free API primary, scrape fallback, credit-budget guard | **done + tested** |
| `stats_api.py` | Sportmonks v3 client: fixtures/lineups/referees/players -> matchups | **implemented + tested (mocked)**; verify field paths live with `sportmonks-probe`; the price-join is the last seam |
| `monitor.py` | fetch -> detect -> dedupe -> ntfy loop | **done + tested (fakes)** |
| `notify.py` | ntfy + email (jobtracker/Fatsoma env vars) | done |
| `cli.py` | `demo`/`scan`/`calc`/`scrape-test`/`monitor`/`sportmonks-probe` | done |

## Running it FREE
Detector A runs at zero cost; the defaults are tuned for it.
- **The Odds API free tier** = 500 credits/month. Each call costs ~`markets x
  regions`, so the defaults (1 region, 2 markets ≈ 2 credits) + a 30-min loop
  stay well under budget. `sources.py` reads the credits-remaining header and
  **stops calling the API at `credit_floor`**, so you can never overrun the month.
- **Scrape fallback (`odds_source: both`)** keeps you running once credits are
  gone: it scrapes oddschecker (reusing boostmatcher's renderer + selector
  engine) for the same multi-book 1X2 grid. Free and unlimited, but fragile and
  against the site's ToS — the parser is tested, but you must confirm the live
  selectors once with `scrape-test` and list match URLs in `scrape_urls`.

**Detector B is not free** — and can't be made free. The blocker isn't the stats
(Sportmonks has a limited free plan); it's that **player-foul and card-total
*odds* don't exist on any free feed**, and without a price there's no EV to
compute. Referee card history is paid too. So Detector B needs a paid props feed
([OpticOdds](https://opticodds.com)) + [Sportmonks](https://sportmonks.com);
leave `enable_statedge: false` on the free plan.

## Going live — what still needs YOUR input
1. **The free Odds API key.** Free tier at the-odds-api.com -> `.env`
   `ODDS_API_KEY=...`. Copy `config.example.yaml` to `config.yaml` and run
   `python -m gembets monitor`. Detector A works immediately, for free.
1b. **(Optional) calibrate the scrape fallback.** Save an oddschecker match
   "winner" page, run `python -m gembets scrape-test --file saved.html`, adjust
   `scrape.SPECS["oddschecker"]` until it prints the book grid, then list match
   URLs in `scrape_urls`. Only needed if you want to keep running after the
   monthly API credits are exhausted.
2. **Validate before staking real money — CLV.** Paper-trade 2–4 weeks: log every
   flagged price, then compare to the **closing** line. If your flags consistently
   beat the close, the edge is real. Do not stake before closing-line value is positive.
3. **Sportmonks for Detector B (the v3 client is built).** `.env`
   `STATS_API_KEY=...`, then **verify the live field paths**:
   ```
   python -m gembets sportmonks-probe --leagues 8        # 8 = Premier League
   ```
   That fetches one fixture and prints the parsed home/away, main referee,
   confirmed-XI counts, and the winger-vs-fullback pairs. `stats_api` parses
   Sportmonks **defensively by name** (the confirmed stat `type_id`s — fouls
   committed 56, fouls won 96, yellow 84, red 83, minutes 119 — are pinned, but
   the lineup/referee/team *shapes* aren't fully documented). If the probe shows
   a mismatch, adjust the parser helpers and the matching test fixture.
4. **The price-join (last seam).** Sportmonks gives STATS, not ODDS.
   `stats_api.fetch_sportmonks` takes a `price_lookup(fixture, market, line)`
   that supplies the bookmaker's offered price; without it, matchups are computed
   and **logged** but not emitted (no price = no gem). Wire it to a props-capable
   odds feed — **OpticOdds** for player foul props; the cards-total market is on
   more books. Then set `enable_statedge: true`. Gate stays on **confirmed
   lineups** (~1h pre-kickoff). Backtest + tune the blend weights in `statedge.py`.

## Honest caveats
- **A lone book above consensus is often the book being *right*** (injury/lineup
  news you don't have) or a soft line that gets cut in minutes. De-vig + median
  filters most noise; CLV proves the rest.
- **Player-foul props + referee data are the scarce, premium inputs** — far fewer
  opportunities than 1X2/totals, and only on better feeds.
- **The Poisson model is only as good as its rates and weights** — Detector B is
  noisier than A by design (hence the higher 6% bar) and needs backtesting.
- Reuses the same ntfy + SMTP `.env` as the Fatsoma/jobtracker/boostmatcher bots;
  drop it on the Oracle VM next to them. Mind your odds-API quota in `poll_interval`.
