"""boostmatcher CLI.

  python -m boostmatcher demo
      Rate the bundled sample boosts against bundled sample exchange quotes —
      proves the pipeline end-to-end with no credentials or network.

  python -m boostmatcher rate --boosts b.json --quotes q.json [--stake 25]
      Rate your own scraped boosts against a quotes file in the same shape.

Live scraping + exchange APIs land behind `monitor` once credentials are set
(see README). The rating/report path below is exactly what live mode feeds.
"""
from __future__ import annotations

import argparse
import json
import os

from . import dashboard
from .matcher import best_runner


def _load_dotenv() -> None:
    """Tiny .env loader (no dependency): KEY=VALUE lines into os.environ.

    Looks in both the package folder (boostmatcher/.env) and the current working
    directory, so it works whether you run from the repo root or inside the
    package. Existing env vars win; an already-loaded key isn't overridden.
    """
    candidates = [
        os.path.join(os.path.dirname(__file__), ".env"),   # boostmatcher/.env
        os.path.join(os.getcwd(), ".env"),                 # ./.env
    ]
    seen: set[str] = set()
    for path in candidates:
        real = os.path.abspath(path)
        if real in seen or not os.path.exists(real):
            continue
        seen.add(real)
        with open(real, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
from .models import Boost, ExchangeQuote
from .rating import best_of


def _load_boosts(path: str) -> list[Boost]:
    with open(path, encoding="utf-8") as fh:
        return [Boost(**b) for b in json.load(fh)]


def _quotes_for(boost: Boost, book: dict, exchanges: dict[str, float]) -> list[ExchangeQuote]:
    """Turn the sample-quotes structure into ExchangeQuotes for one boost.

    `exchanges` maps exchange name -> commission. Matches the boost selection to
    a runner with the token matcher, then reads each exchange's [odds, liq].
    """
    markets = book.get(boost.event, {})
    quotes: list[ExchangeQuote] = []
    for market_name, runners in markets.items():
        runner = best_runner(boost.selection, list(runners.keys()))
        if runner is None:
            continue
        for exch, comm in exchanges.items():
            if exch in runners[runner]:
                vals = runners[runner][exch]
                odds, liq = vals[0], vals[1]
                back = vals[2] if len(vals) > 2 else None     # optional back price
                quotes.append(ExchangeQuote(exchange=exch, lay_odds=odds, available=liq,
                                            commission=comm, runner=runner,
                                            market_id=market_name, back_odds=back))
        break
    return quotes


def _report(rateds, stake: float) -> str:
    rows = sorted(rateds, key=lambda r: r.rating, reverse=True)
    out = [f"{'BOOK':<11} {'SELECTION':<34} {'BACK':>5} {'LAY':>6} {'EXCH':<9} "
           f"{'RATING':>7} {'LOCK_GBP':>8}  NOTES",
           "-" * 110]
    for r in rows:
        b = r.boost
        if r.quote is None:
            out.append(f"{b.bookie:<11} {b.selection[:34]:<34} {b.boosted_odds:>5} "
                       f"{'-':>6} {'-':<9} {'-':>7} {'-':>7}  {'; '.join(r.notes)}")
            continue
        flag = "LOCK " if r.lockable else "     "
        out.append(f"{b.bookie:<11} {b.selection[:34]:<34} {b.boosted_odds:>5} "
                   f"{r.quote.lay_odds:>6} {r.quote.exchange:<9} {r.rating:>6.2f}% "
                   f"{r.profit_if_loses:>7.2f} {flag}{'; '.join(r.notes)}")
    return "\n".join(out)


def cmd_demo(args: argparse.Namespace) -> None:
    here = os.path.dirname(__file__)
    args.boosts = os.path.join(here, "examples", "sample_boosts.json")
    args.quotes = os.path.join(here, "examples", "sample_quotes.json")
    cmd_rate(args)


def cmd_rate(args: argparse.Namespace) -> None:
    boosts = _load_boosts(args.boosts)
    with open(args.quotes, encoding="utf-8") as fh:
        book = json.load(fh)
    exchanges = {"smarkets": 0.02, "betfair": 0.05}

    rateds = [best_of(b, _quotes_for(b, book, exchanges), args.stake) for b in boosts]
    print(_report(rateds, args.stake))

    alertable = [r for r in rateds if r.quote and r.rating >= args.alert]
    print(f"\n{len(alertable)} boost(s) clear the +{args.alert}% alert threshold "
          f"at GBP{args.stake:.0f} stake.")

    if args.html:
        dashboard.write(rateds, args.html, stake=args.stake, alert_rating=args.alert)
        print(f"Dashboard written to {args.html}")


def _value_report(vbets, bankroll: float) -> str:
    rows = sorted(vbets, key=lambda v: v.edge_pct, reverse=True)
    out = [f"{'BOOK':<9} {'SELECTION':<36} {'BOOST':>6} {'FAIR':>6} {'EDGE':>7} "
           f"{'STAKE_GBP':>9}  NOTES", "-" * 108]
    for v in rows:
        b = v.boost
        fair = f"{v.fair:.2f}" if v.fair else "-"
        flag = "+EV " if v.kelly_stake > 0 else "    "
        out.append(f"{b.bookie:<9} {b.selection[:36]:<36} {b.boosted_odds:>6.2f} "
                   f"{fair:>6} {v.edge_pct:>6.1f}% {v.kelly_stake:>9.2f} {flag}"
                   f"{'; '.join(v.notes)}")
    staked = [v for v in vbets if v.kelly_stake > 0]
    out.append(f"\n{len(staked)} genuinely +EV boost(s) at bankroll GBP{bankroll:.0f} "
               f"(quarter-Kelly). These are VALUE bets, not risk-free.")
    return "\n".join(out)


def cmd_value(args: argparse.Namespace) -> None:
    """Rate boosts as +EV VALUE bets vs the exchange fair price (not laying)."""
    from . import dashboard
    from .value import rate_value

    here = os.path.dirname(__file__)
    boosts_path = args.boosts or os.path.join(here, "examples", "sample_boosts.json")
    quotes_path = args.quotes or os.path.join(here, "examples", "sample_quotes.json")
    boosts = _load_boosts(boosts_path)
    with open(quotes_path, encoding="utf-8") as fh:
        book = json.load(fh)
    exchanges = {"smarkets": 0.02, "betfair": 0.05}

    vbets = []
    for b in boosts:
        quotes = _quotes_for(b, book, exchanges)
        best = max(quotes, key=lambda q: q.available, default=None)   # deepest market
        vbets.append(rate_value(b, best, bankroll=args.bankroll))
    print(_value_report(vbets, args.bankroll))

    if args.html:
        dashboard.write_value(vbets, args.html, bankroll=args.bankroll)
        print(f"Value dashboard written to {args.html}")


def _cover_report(results) -> str:
    rows = sorted(results, key=lambda r: r.roi_pct if r.lock else -999, reverse=True)
    out = [f"{'BOOST (book@odds)':<40} {'COVER LEGS (book@odds)':<40} {'TOTAL':>7} "
           f"{'PROFIT':>7} {'ROI':>6}  ", "-" * 108]
    for r in rows:
        b = r.boost
        boost_txt = f"{b.selection[:26]} {b.bookie}@{b.boosted_odds:.2f}"
        if not r.legs:
            out.append(f"{boost_txt:<40} {'-':<40} {'-':>7} {'-':>7} {'-':>6}  "
                       f"{'; '.join(r.notes)}")
            continue
        legs = " + ".join(f"{l.selection[:14]} {l.bookie}@{l.odds:.2f}" for l in r.legs)
        flag = "LOCK" if r.lock else "    "
        out.append(f"{boost_txt:<40} {legs[:40]:<40} {r.total_stake:>7.2f} "
                   f"{r.guaranteed_profit:>7.2f} {r.roi_pct:>5.1f}% {flag}")
        if r.lock:
            stakes = ", ".join(f"GBP{s:.2f} on {l.selection[:18]} ({l.bookie})"
                               for s, l in zip(r.leg_stakes, r.legs))
            out.append(f"    -> back GBP{r.back_stake:.2f} on the boost, then {stakes}")
    locks = [r for r in results if r.lock]
    out.append(f"\n{len(locks)} cross-book lock(s) found. Both stakes are real money "
               f"until settled; arbing across books gets accounts limited fast.")
    return "\n".join(out)


def cmd_feed(args: argparse.Namespace) -> None:
    """Scrape a boosts page (oddschecker) and write the live feed website."""
    from . import dashboard
    from .scrapers import SCRAPERS

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            html = fh.read()
    else:
        import asyncio
        from .monitor import _render_html
        html = asyncio.run(_render_html(args.url))

    from . import site
    from .lockability import classify
    boosts = SCRAPERS[args.scraper](html, url=args.url or args.file)
    out = args.html or "index.html"
    site.write_site(boosts, out, lockable_only=not args.all)
    n_lock = sum(1 for b in boosts if classify(b.selection).lockable)
    print(f"Scraped {len(boosts)} boosts from {len({b.bookie for b in boosts})} books "
          f"-> {n_lock} lockable -> {out}" + ("" if args.all else f" ({len(boosts)-n_lock} props hidden)"))


def cmd_calc(args: argparse.Namespace) -> None:
    """Instant calculator: type the odds you see, get the stakes + lock/profit.

    Works tonight with no creds or scraping. Pick ONE of --lay / --cover / --fair:
      --lay 2.32                 exchange lay (risk-free if the boost beats it)
      --cover 3.5 4.0            back the opposite side(s) at other bookies
      --fair 2.28               value: is the boost +EV vs the true price?
    """
    from .cover import CoverLeg, rate_cover
    from .instructions import plan
    from .models import Boost, ExchangeQuote
    from .rating import rate
    from .value import rate_value

    boost = Boost(bookie="bookie", event=args.name or "boost", market="Boost",
                  selection=args.name or "your selection", boosted_odds=args.back)

    if args.lay is not None:
        q = ExchangeQuote(exchange="exchange", lay_odds=args.lay, available=1e9,
                          commission=args.commission)
        p = plan(rate(boost, q, args.stake))
        print(f"EXCHANGE LAY  (boost {args.back} @ stake GBP{args.stake:.2f}, "
              f"lay {args.lay}, comm {args.commission*100:.0f}%)\n")
        for step in p.steps():
            print("  " + step.replace("£", "GBP"))
        verdict = "RISK-FREE LOCK" if p.guaranteed >= 0 else "NOT a lock (boost too small)"
        print(f"\n  => {verdict}: GBP{p.guaranteed:+.2f} guaranteed")

    elif args.cover is not None:
        legs = [CoverLeg(bookie=f"book{i+1}", selection=f"opposite {i+1}", odds=o)
                for i, o in enumerate(args.cover)]
        r = rate_cover(boost, legs, args.stake)
        print(f"CROSS-BOOK COVER  (boost {args.back} @ GBP{args.stake:.2f}, "
              f"opposite odds {', '.join(str(o) for o in args.cover)})\n")
        print(f"  book sum: {r.book_sum*100:.1f}%  ({'under 100% = LOCK' if r.lock else 'over 100% = no lock'})")
        if r.lock:
            print(f"  back GBP{r.back_stake:.2f} on the boost, then:")
            for s, o in zip(r.leg_stakes, args.cover):
                print(f"    GBP{s:.2f} on the opposite @ {o}")
            print(f"  => total staked GBP{r.total_stake:.2f}, "
                  f"guaranteed profit GBP{r.guaranteed_profit:+.2f} ({r.roi_pct:.1f}% ROI)")
        else:
            print(f"  => no lock; you'd lose ~GBP{-r.guaranteed_profit:.2f} on average. {'; '.join(r.notes)}")

    elif args.fair is not None:
        q = ExchangeQuote(exchange="exchange", lay_odds=args.fair, available=1e9,
                          commission=0.0, back_odds=args.fair)
        v = rate_value(boost, q, bankroll=args.bankroll)
        print(f"VALUE  (boost {args.back} vs fair {args.fair}, bankroll GBP{args.bankroll:.0f})\n")
        print(f"  edge: {v.edge_pct:+.1f}%   ({'genuinely +EV' if v.positive else 'NOT +EV -- skip'})")
        if v.kelly_stake > 0:
            print(f"  => bet GBP{v.kelly_stake:.2f} straight (quarter-Kelly). Value bet, NOT risk-free.")
        else:
            print(f"  => stake nothing. {'; '.join(v.notes)}")
    else:
        print("Pick one of --lay, --cover, or --fair. See: python -m boostmatcher calc -h")


def cmd_cover(args: argparse.Namespace) -> None:
    """Lock boosts by backing the opposite side(s) at OTHER bookies (Dutching)."""
    from .cover import CoverLeg, complement, rate_cover

    here = os.path.dirname(__file__)
    boosts_path = args.boosts or os.path.join(here, "examples", "sample_boosts.json")
    covers_path = args.covers or os.path.join(here, "examples", "sample_covers.json")
    boosts = _load_boosts(boosts_path)
    with open(covers_path, encoding="utf-8") as fh:
        cover_book = json.load(fh)

    results = []
    for b in boosts:
        raw = cover_book.get(b.selection, [])
        legs = [CoverLeg(bookie=l["bookie"], selection=l["selection"], odds=l["odds"])
                for l in raw]
        res = rate_cover(b, legs, args.stake)
        if not legs and complement(b.selection) is None:
            res.notes.append("no clean opposite outcome (e.g. anytime scorer)")
        results.append(res)
    print(_cover_report(results))


def cmd_probe(args: argparse.Namespace) -> None:
    """Hit one real exchange market and print every runner's lay price.

    The single-command sanity check for live credentials: if this prints sane
    decimal odds, your token/keys and `_resolve` are working.
    """
    import asyncio

    if args.exchange == "smarkets":
        from .exchanges.smarkets import Smarkets
        client = Smarkets(commission=0.02)
        cred_hint = "SMARKETS_API_TOKEN"
    else:
        from .exchanges.betfair import Betfair
        client = Betfair(commission=0.05)
        cred_hint = "BETFAIR_APP_KEY + BETFAIR_SESSION_TOKEN"

    market_id, runners = asyncio.run(client.market_runners(args.event, args.market))
    if not runners:
        print(f"No runners returned. Check {cred_hint} in .env, and that the event/market "
              f"strings match a live market. (event={args.event!r}, market={args.market!r})")
        return
    print(f"{args.exchange} market {market_id or '?'} — {args.event} / {args.market}")
    print(f"{'RUNNER':<32} {'LAY ODDS':>9} {'AVAIL £':>10}")
    print("-" * 53)
    for name, (lay, liq) in sorted(runners.items(), key=lambda kv: kv[1][0]):
        print(f"{name[:32]:<32} {lay:>9.2f} {liq:>10.0f}")
    print(f"\nLooks sane if these are realistic decimal odds (~1.1-30) with non-zero liquidity.")


def cmd_scrape_test(args: argparse.Namespace) -> None:
    """Run a bookie scraper against a SAVED html file and print the boosts found.

    Save the live boost page (Ctrl-S -> 'Webpage, HTML Only') after tuning the
    SelectorSpec, then point this at it to confirm the class names are right.
    """
    from .scrapers import SCRAPERS
    with open(args.file, encoding="utf-8") as fh:
        html = fh.read()
    boosts = SCRAPERS[args.bookie](html, url=args.file)
    if not boosts:
        print(f"0 boosts parsed. The class names in scrapers.SPECS['{args.bookie}'] probably "
              f"don't match this page yet — inspect a boost card in DevTools and update them.")
        return
    print(f"Parsed {len(boosts)} boost(s) from {args.file}:\n")
    for b in boosts:
        was = f" (was {b.original_odds})" if b.original_odds else ""
        ev = f"{b.event} | " if b.event else ""
        print(f"  [{b.bookie}] {ev}{b.selection} @ {b.boosted_odds}{was}")


def cmd_betfair_login(args: argparse.Namespace) -> None:
    """Login to Betfair and print a session token to paste into .env.

    --method interactive (default): username + password only, no certificate.
    --method cert: non-interactive cert login (more robust for the always-on loop).
    """
    from .exchanges.betfair import cert_login, interactive_login
    token = cert_login() if args.method == "cert" else interactive_login()
    print("BETFAIR_SESSION_TOKEN=" + token)
    print("\nPaste that line into your .env (replacing the empty one), then run:\n"
          "  python -m boostmatcher probe --exchange betfair --event \"...\" --market \"Match Result\"")


def cmd_monitor(args: argparse.Namespace) -> None:
    import asyncio

    from . import monitor
    html = args.html or "boostmatcher_dashboard.html"
    print(f"Starting live monitor (config={args.config}); dashboard -> {html}. Ctrl-C to stop.")
    asyncio.run(monitor.run(args.config, html_path=html))


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stake", type=float, default=25.0, help="back stake to price at (£)")
    common.add_argument("--alert", type=float, default=2.0, help="rating %% threshold to flag")
    common.add_argument("--html", default=None, metavar="PATH",
                        help="also write an HTML dashboard (returns in £ + lay method) to PATH")

    p = argparse.ArgumentParser(prog="boostmatcher", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", parents=[common],
                   help="rate bundled sample data (no network)").set_defaults(fn=cmd_demo)
    pr = sub.add_parser("rate", parents=[common], help="rate your own boosts/quotes files")
    pr.add_argument("--boosts", required=True)
    pr.add_argument("--quotes", required=True)
    pr.set_defaults(fn=cmd_rate)

    pm = sub.add_parser("monitor", parents=[common],
                        help="live: scrape -> quote -> rate -> alert, on a loop")
    pm.add_argument("--config", default="config.yaml")
    pm.set_defaults(fn=cmd_monitor)

    pf = sub.add_parser("feed", parents=[common],
                        help="scrape a boosts page -> live feed website with built-in calculator")
    pf.add_argument("--file", default=None, help="saved page .html (offline)")
    pf.add_argument("--url", default="https://www.oddschecker.com/football/best-of-the-boosts",
                    help="live page to fetch if --file not given")
    pf.add_argument("--scraper", default="oddschecker", help="scraper key (default oddschecker)")
    pf.add_argument("--all", action="store_true", help="include unlockable props/combos too")
    pf.set_defaults(fn=cmd_feed)

    pca = sub.add_parser("calc", parents=[common],
                         help="instant calculator: type odds you see, get stakes + lock/profit")
    pca.add_argument("--back", type=float, required=True, help="the BOOSTED odds at the bookie")
    pca.add_argument("--name", default=None, help="optional label for the selection")
    pca.add_argument("--lay", type=float, default=None, help="exchange LAY odds")
    pca.add_argument("--commission", type=float, default=0.02, help="exchange commission (0.02=2%%)")
    pca.add_argument("--cover", type=float, nargs="+", default=None,
                     help="opposite-side odds at other book(s), space-separated")
    pca.add_argument("--fair", type=float, default=None, help="true/exchange fair odds (value mode)")
    pca.add_argument("--bankroll", type=float, default=500.0, help="bankroll for value Kelly (£)")
    pca.set_defaults(fn=cmd_calc)

    pc = sub.add_parser("cover", parents=[common],
                        help="lock boosts by backing the opposite side at other books")
    pc.add_argument("--boosts", default=None, help="boosts JSON (default: bundled sample)")
    pc.add_argument("--covers", default=None, help="opposite-prices JSON (default: bundled sample)")
    pc.set_defaults(fn=cmd_cover)

    pv = sub.add_parser("value", parents=[common],
                        help="rate boosts as +EV value bets vs exchange fair price")
    pv.add_argument("--boosts", default=None, help="boosts JSON (default: bundled sample)")
    pv.add_argument("--quotes", default=None, help="quotes JSON (default: bundled sample)")
    pv.add_argument("--bankroll", type=float, default=500.0, help="bankroll for Kelly staking (£)")
    pv.set_defaults(fn=cmd_value)

    pp = sub.add_parser("probe", parents=[common],
                        help="print live lay prices for one market (credential sanity check)")
    pp.add_argument("--exchange", choices=["smarkets", "betfair"], required=True)
    pp.add_argument("--event", required=True, help='e.g. "England v USA"')
    pp.add_argument("--market", default="Match Result", help='e.g. "Match Result"')
    pp.set_defaults(fn=cmd_probe)

    ps = sub.add_parser("scrape-test", parents=[common],
                        help="run a scraper against a saved .html to check selectors")
    ps.add_argument("--bookie",
                    choices=["oddschecker", "skybet", "bet365", "williamhill", "paddypower"],
                    required=True)
    ps.add_argument("--file", required=True, help="path to a saved boost page (.html)")
    ps.set_defaults(fn=cmd_scrape_test)

    pb = sub.add_parser("betfair-login", parents=[common],
                        help="login to Betfair, print a session token for .env")
    pb.add_argument("--method", choices=["interactive", "cert"], default="interactive",
                    help="interactive = username+password only (default); cert = non-interactive")
    pb.set_defaults(fn=cmd_betfair_login)

    args = p.parse_args(argv)
    _load_dotenv()
    args.fn(args)


if __name__ == "__main__":
    main()
