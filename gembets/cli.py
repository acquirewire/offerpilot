"""gembets CLI.

  python -m gembets demo
      Run both detectors over the bundled sample odds + stats — proves the whole
      pipeline (de-vig consensus, outlier flag, Poisson edges) with no key/network.

  python -m gembets scan --odds dump.json [--stats stats.json]
      Run the detectors over a saved The Odds API JSON dump (and optional stats),
      print every gem. The same path the live loop feeds.

  python -m gembets calc --decimal 4.20 --fair-prob 0.26
      One-off: EV + edge for a single price against a probability you believe.

  python -m gembets monitor --config config.yaml
      Live loop: fetch -> detect -> ntfy, every poll_interval (needs ODDS_API_KEY).
"""
from __future__ import annotations

import argparse
import os


def _load_dotenv() -> None:
    """Tiny .env loader (no dependency): KEY=VALUE lines into os.environ.

    Looks in the package folder, the cwd, and the sibling boostmatcher/.env — the
    Betfair creds live there and are refreshed by `boostmatcher betfair-login`, so
    we read the same file rather than duplicating an expiring session token.
    Existing env vars win; earlier files win over later ones.
    """
    repo = os.path.dirname(os.path.dirname(__file__))      # .../reselling
    for path in (os.path.join(os.path.dirname(__file__), ".env"),     # gembets/.env
                 os.path.join(os.getcwd(), ".env"),                   # ./.env
                 os.path.join(repo, "boostmatcher", ".env"),          # shared Betfair creds
                 os.path.join(os.getcwd(), "boostmatcher", ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _print_gems(gems, header: str) -> None:
    if not gems:
        print(f"{header}: no gems clear the threshold (this is normal — most "
              f"markets are efficiently priced).")
        return
    print(f"{header}: {len(gems)} gem(s)\n" + "-" * 78)
    for g in sorted(gems, key=lambda x: x.edge, reverse=True):
        print(f"[{g.kind:8}] +{g.edge_pct:5.1f}% EV  {g.fixture}")
        print(f"            {g.market}  | {g.book} @ {g.decimal_odds:.2f}  "
              f"(implied {g.implied_prob*100:.1f}% vs fair {g.fair_prob*100:.1f}%)")
        print(f"            > {g.reason}\n")


def cmd_demo(args: argparse.Namespace) -> None:
    here = os.path.dirname(__file__)
    args.odds = os.path.join(here, "examples", "sample_odds.json")
    args.stats = os.path.join(here, "examples", "sample_stats.json")
    cmd_scan(args)


def cmd_scan(args: argparse.Namespace) -> None:
    from . import outlier, statedge
    from .odds_api import load_sample as load_odds

    snaps = load_odds(args.odds)
    print(f"Loaded {len(snaps)} market snapshot(s) across "
          f"{len({s.fixture for s in snaps})} fixture(s).\n")
    books = {b.strip() for b in args.books.split(",")} if args.books else None
    gems = outlier.scan_all(snaps, min_lift=args.min_lift, min_books=args.min_books,
                            max_odds=args.max_odds, allowed_books=books)
    _print_gems(gems, "DETECTOR A (consensus outliers)")

    if args.stats:
        from .stats_api import load_sample as load_stats
        fouls, cards = load_stats(args.stats)
        sgems = []
        for m in fouls:
            if (g := statedge.foul_edge(m, min_edge=args.min_edge_stat)):
                sgems.append(g)
        for m in cards:
            if (g := statedge.cards_edge(m, min_edge=args.min_edge_stat)):
                sgems.append(g)
        print()
        _print_gems(sgems, "DETECTOR B (statistical mispricing)")


def cmd_calc(args: argparse.Namespace) -> None:
    from .odds import evaluate_value
    sig = evaluate_value(args.decimal, args.fair_prob, min_edge=args.min_edge)
    print(f"price {args.decimal:.2f} (implied {sig.offered_prob*100:.1f}%) vs "
          f"fair {args.fair_prob*100:.1f}%")
    print(f"  EV per unit: {sig.edge*100:+.1f}%   "
          f"({'FLAG - gem' if sig.has_edge else 'below threshold - skip'})")
    print(f"  payout lift vs market: {sig.lift_vs_market*100:+.1f}%")


def cmd_report(args: argparse.Namespace) -> None:
    """Per-detector CLV + P&L from the ledger — see what's actually working."""
    from . import ledger
    from .config import load as load_cfg
    path = args.ledger or (load_cfg(args.config).ledger_path if args.config else "gembets_ledger.db")
    conn = ledger.connect(path)
    stats = ledger.report(conn)
    if not stats:
        print(f"No bets logged yet in {path}. Run the monitor first.")
        return
    print(f"Ledger: {path}\n")
    print(f"{'DETECTOR':<14}{'BETS':>5}{'AVG EDGE':>10}{'AVG CLV':>9}{'(n)':>6}"
          f"{'SETTLED':>8}{'HIT%':>6}{'P&L':>9}{'ROI':>7}")
    print("-" * 74)
    for s in sorted(stats, key=lambda x: x.pnl, reverse=True):
        clv = f"{s.avg_clv*100:+.1f}%" if s.avg_clv is not None else "  -"
        hit = f"{s.hit_rate*100:.0f}%" if s.hit_rate is not None else "-"
        roi = f"{s.roi*100:+.0f}%" if s.roi is not None else "-"
        print(f"{s.kind:<14}{s.bets:>5}{s.avg_edge*100:>9.1f}%{clv:>9}{s.clv_n:>6}"
              f"{s.settled:>8}{hit:>6}{s.pnl:>9.2f}{roi:>7}")
    print("\nCLV is the truth serum: a detector that doesn't show positive avg CLV "
          "over a real sample (n) is not finding real edges, whatever its P&L.")


def cmd_settle(args: argparse.Namespace) -> None:
    """Mark a bet won/loss/void by its key (from the ledger) to record P&L."""
    from . import ledger
    conn = ledger.connect(args.ledger)
    if args.key:
        pnl = ledger.settle(conn, args.key, args.result)
        print(f"settled {args.key}: {args.result} -> P&L {pnl:+.2f}" if pnl is not None
              else f"no bet with key {args.key}")
        return
    rows = ledger.pending_bets(conn)
    print(f"{len(rows)} unsettled bet(s). Settle with: "
          f"gembets settle --key <key> --result win|loss|void\n")
    for r in rows[:30]:
        print(f"  {r['key']}")


def cmd_monitor(args: argparse.Namespace) -> None:
    import asyncio

    from . import monitor
    print(f"Starting live monitor (config={args.config}). Ctrl-C to stop.")
    asyncio.run(monitor.run(args.config))


def cmd_scrape_test(args: argparse.Namespace) -> None:
    """Parse a SAVED oddschecker page and print the multi-book grid found.

    Save the live odds page (Ctrl-S -> 'Webpage, HTML Only'), then point this at
    it to confirm the selectors in scrape.SPECS match before trusting the scrape
    fallback. If it prints 0 books, adjust the GridSpec and re-run.
    """
    from . import outlier
    from .scrape import SCRAPERS, fixture_from_url

    with open(args.file, encoding="utf-8") as fh:
        html = fh.read()
    fixture = args.fixture or (fixture_from_url(args.url) if args.url else "Saved fixture")
    snap = SCRAPERS[args.scraper](html, fixture=fixture, url=args.url or args.file)
    if snap is None:
        print(f"0 usable book rows parsed from {args.file}. The selectors in "
              f"scrape.SPECS['{args.scraper}'] probably don't match this page yet — "
              f"inspect a row in DevTools and update row/bookie/cell.")
        return
    print(f"Parsed {len(snap.lines)} book(s) for {snap.fixture} ({snap.market}):\n")
    print(f"{'BOOK':<16} " + "  ".join(f"{l:>6}" for l in snap.labels))
    for ln in snap.lines:
        print(f"{ln.book[:16]:<16} " + "  ".join(f"{d:>6.2f}" for d in ln.decimals))
    books = {b.strip() for b in args.books.split(",")} if args.books else None
    gems = outlier.scan_snapshot(snap, min_lift=args.min_lift, min_books=args.min_books,
                                 max_odds=args.max_odds, allowed_books=books)
    print()
    _print_gems(gems, "Outliers in this grid")


def cmd_model(args: argparse.Namespace) -> None:
    """Free multi-market model: fair lines for a fixture from a results CSV.

    Data is a football-data.co.uk league CSV (file path or URL) — it carries
    goals, shots, fouls, corners, cards and the referee, so one fetch prices
    every market. Compare the printed fair odds to what your bookie offers; or
    pass --market/--line/--odds to get an instant gem verdict on a price.
    """
    import asyncio

    from . import totals

    if args.csv.lower().startswith("http"):
        matches = asyncio.run(totals.fetch_matches(args.csv))
    else:
        with open(args.csv, encoding="utf-8") as fh:
            matches = totals.parse_matches(fh.read())
    model = totals.build(matches)
    print(f"Fitted from {len(matches)} matches | markets: {', '.join(model.markets())}")
    rf = model.referees.factor(args.ref) if args.ref else 1.0
    if args.ref:
        print(f"Referee {args.ref}: x{rf:.2f} cards vs league "
              f"({model.referees.league_avg:.1f}/game)")

    if args.market and args.line is not None and args.odds is not None:
        res = totals.check(model, args.home, args.away, args.market, args.line,
                           args.odds, side=args.side, referee=args.ref, min_edge=args.min_edge)
        if res is None:
            print(f"Can't model {args.market} for {args.home} vs {args.away} "
                  f"(team not in this CSV?)")
            return
        print(f"\n{args.home} vs {args.away} | {args.market} {args.side} {args.line} @ {args.odds:.2f}")
        print(f"  model expects {res['expected']:.2f}; P({args.side} {args.line}) = "
              f"{res['model_prob']*100:.0f}% vs implied {res['implied']*100:.0f}%")
        print(f"  EV {res['edge']*100:+.1f}%  ->  "
              f"{'GEM' if res['has_edge'] else 'no edge - skip'}")
        return

    rows = totals.fair_lines(model, args.home, args.away, referee=args.ref)
    if not rows:
        print(f"\nNo model for {args.home} vs {args.away} - check the names match "
              f"this league's CSV (e.g. 'Man City', 'Tottenham').")
        return
    print(f"\nFair lines - {args.home} vs {args.away}:")
    print(f"{'MARKET':<16}{'LINE':>6}{'EXP':>7}{'P(OVER)':>9}{'FAIR OVER':>11}{'FAIR UNDER':>12}")
    print("-" * 62)
    for r in rows:
        print(f"{r.market:<16}{r.line:>6.1f}{r.expected:>7.1f}{r.prob_over*100:>8.0f}%"
              f"{r.fair_over:>11.2f}{r.fair_under:>12.2f}")
    print("\nBet OVER if the bookie's over odds are ABOVE 'fair over' (and vice versa).")


def cmd_betfair_probe(args: argparse.Namespace) -> None:
    """List the soccer market-type codes Betfair returns now (needs Betfair creds).

    Use it to confirm the corners/bookings codes for `betfair_market_types`, and
    to check a few live totals quotes flow through. Mint a token first with
    `python -m boostmatcher betfair-login`.
    """
    import asyncio

    from .betfair_odds import BetfairOdds
    bf = BetfairOdds()
    if not bf.ready:
        print("BETFAIR_APP_KEY / BETFAIR_SESSION_TOKEN not set. Get a token with "
              "`python -m boostmatcher betfair-login`, then add both to .env.")
        return
    types = asyncio.run(bf.probe_market_types(hours_ahead=args.hours))
    print(f"Soccer market types in the next {args.hours}h ({len(types)} types):")
    for mt, count in sorted(types.items(), key=lambda kv: -kv[1]):
        tag = ""
        from .betfair_odds import classify_market
        if classify_market(mt.replace("_", " ")):
            tag = "  <- modelled"
        print(f"  {mt:<28}{count:>5}{tag}")
    quotes = asyncio.run(bf.list_total_markets(hours_ahead=args.hours, max_results=60))
    print(f"\nSample totals quotes parsed: {len(quotes)}")
    for q in quotes[:8]:
        print(f"  {q.fixture:<28} {q.market:<14} {q.line:>5} "
              f"O={q.over_decimal} U={q.under_decimal}")

    pquotes = asyncio.run(bf.list_player_foul_markets(hours_ahead=args.hours, max_results=60))
    print(f"\nSample player-foul quotes parsed: {len(pquotes)}")
    for q in pquotes[:8]:
        print(f"  {q.fixture:<26} {q.player:<20} {q.line:>4} "
              f"O={q.over_decimal} U={q.under_decimal}")


def cmd_sportmonks_probe(args: argparse.Namespace) -> None:
    """Live Sportmonks sanity check: prove the key works + field paths parse.

    Needs STATS_API_KEY in .env. Prints one fixture's parsed home/away, main
    referee, confirmed-XI counts, and the winger-vs-fullback pairs we derived —
    so you can confirm Detector B reads the live data correctly before enabling it.
    """
    import asyncio
    import json as _json

    from .stats_api import SportmonksError, probe_fixture
    leagues = [int(x) for x in args.leagues.split(",")] if args.leagues else None
    try:
        result = asyncio.run(probe_fixture(date=args.date, league_ids=leagues))
    except SportmonksError as exc:
        print(f"Probe failed: {exc}")
        return
    print(_json.dumps(result, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--min-lift", type=float, default=0.33,
                        help="flag only if book odds are this fraction above typical "
                             "(0.33 = 4.0 vs 3.0)")
    common.add_argument("--max-odds", type=float, default=5.0,
                        help="ignore longshots priced above this (default 5.0)")
    common.add_argument("--min-books", type=int, default=4,
                        help="books required before a typical price is trusted")
    common.add_argument("--books", default=None,
                        help="comma-separated bookmakers to flag (default: all soft books)")
    common.add_argument("--min-edge-stat", type=float, default=0.06,
                        help="min EV to flag a statistical edge (0.06 = +6%%)")

    p = argparse.ArgumentParser(prog="gembets", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", parents=[common],
                   help="run both detectors on bundled samples (no key/network)"
                   ).set_defaults(fn=cmd_demo)

    ps = sub.add_parser("scan", parents=[common],
                        help="run detectors over a saved odds dump (+ optional stats)")
    ps.add_argument("--odds", required=True, help="The Odds API JSON dump")
    ps.add_argument("--stats", default=None, help="stats JSON (fouls/cards) for Detector B")
    ps.set_defaults(fn=cmd_scan)

    pc = sub.add_parser("calc", parents=[common],
                        help="EV for one price vs a probability you believe")
    pc.add_argument("--decimal", type=float, required=True, help="the offered decimal odds")
    pc.add_argument("--fair-prob", type=float, required=True, help="true probability (0-1)")
    pc.set_defaults(fn=cmd_calc)

    pm = sub.add_parser("monitor", parents=[common],
                        help="live: fetch -> detect -> ntfy, on a loop")
    pm.add_argument("--config", default="config.yaml")
    pm.set_defaults(fn=cmd_monitor)

    prp = sub.add_parser("report", parents=[common],
                         help="per-detector CLV + P&L from the ledger")
    prp.add_argument("--ledger", default=None, help="ledger db path")
    prp.add_argument("--config", default=None, help="read ledger_path from this config")
    prp.set_defaults(fn=cmd_report)

    pse = sub.add_parser("settle", parents=[common], help="record a bet's outcome (P&L)")
    pse.add_argument("--ledger", default="gembets_ledger.db")
    pse.add_argument("--key", default=None, help="bet key (omit to list unsettled)")
    pse.add_argument("--result", choices=["win", "loss", "void"], default="win")
    pse.set_defaults(fn=cmd_settle)

    pst = sub.add_parser("scrape-test", parents=[common],
                         help="parse a saved oddschecker page to check scrape selectors")
    pst.add_argument("--file", required=True, help="path to a saved odds page (.html)")
    pst.add_argument("--scraper", default="oddschecker")
    pst.add_argument("--url", default=None, help="original page URL (for the fixture name)")
    pst.add_argument("--fixture", default=None, help="override the fixture name")
    pst.set_defaults(fn=cmd_scrape_test)

    pmo = sub.add_parser("model", parents=[common],
                         help="free multi-market model: fair cards/corners/fouls/shots/goals lines")
    pmo.add_argument("--csv", required=True, help="football-data.co.uk league CSV (file or URL)")
    pmo.add_argument("--home", required=True)
    pmo.add_argument("--away", required=True)
    pmo.add_argument("--ref", default=None, help="referee name (cards multiplier; EPL CSVs)")
    pmo.add_argument("--market", default=None,
                     help="check a price: goals|cards|corners|fouls|shots|shots_on_target")
    pmo.add_argument("--line", type=float, default=None, help="the over/under line, e.g. 4.5")
    pmo.add_argument("--odds", type=float, default=None, help="the offered decimal odds")
    pmo.add_argument("--side", default="over", choices=["over", "under"])
    pmo.add_argument("--min-edge", type=float, default=0.05, help="EV to call it a gem")
    pmo.set_defaults(fn=cmd_model)

    pbf = sub.add_parser("betfair-probe", parents=[common],
                         help="list Betfair soccer market types + sample totals quotes")
    pbf.add_argument("--hours", type=int, default=48, help="look-ahead window (hours)")
    pbf.set_defaults(fn=cmd_betfair_probe)

    pp = sub.add_parser("sportmonks-probe", parents=[common],
                        help="live Sportmonks sanity check (needs STATS_API_KEY)")
    pp.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    pp.add_argument("--leagues", default=None, help="comma-separated Sportmonks league ids")
    pp.set_defaults(fn=cmd_sportmonks_probe)

    args = p.parse_args(argv)
    _load_dotenv()
    args.fn(args)


if __name__ == "__main__":
    main()
