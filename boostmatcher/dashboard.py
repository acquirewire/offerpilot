"""Render rated boosts to a self-contained HTML dashboard.

Every row shows the money in £: back stake & returns, how much to lay, the
liability to hold, and profit under each outcome — plus an expandable
step-by-step method (instructions.LayPlan). Boosts that can't be laid are listed
separately as "manual only". No web server: writes a single static .html you
open in a browser (or the monitor re-writes on each tick).
"""
from __future__ import annotations

import html
from datetime import datetime

from .instructions import plan
from .models import RatedBoost

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0d1117; color: #e6edf3;
  font: 14px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
header { padding: 20px 28px; border-bottom: 1px solid #21262d; }
header h1 { margin: 0; font-size: 20px; }
header .sub { color: #8b949e; font-size: 13px; margin-top: 4px; }
.wrap { padding: 20px 28px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; text-align: right; border-bottom: 1px solid #21262d; white-space: nowrap; }
th { color: #8b949e; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
td.l, th.l { text-align: left; white-space: normal; }
tr.lock td { background: rgba(46,160,67,.07); }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.pos { color: #3fb950; } .neg { color: #f85149; }
.lockpill { background: #1f6f3f; color: #d6ffe0; }
.valpill { background: #5a3b00; color: #ffe2ad; }
.rating { font-weight: 700; }
details { margin: 0; }
details summary { cursor: pointer; color: #58a6ff; font-size: 12px; }
details pre { margin: 8px 0 2px; padding: 12px; background: #161b22; border: 1px solid #21262d;
  border-radius: 8px; white-space: pre-wrap; color: #c9d1d9; font-size: 12.5px; }
h2 { font-size: 14px; color: #8b949e; margin: 28px 0 8px; }
.muted { color: #6e7681; }
"""


def _money(x: float) -> str:
    cls = "pos" if x >= 0 else "neg"
    return f'<span class="{cls}">£{x:+,.2f}</span>'


def _row(rated: RatedBoost) -> str:
    b = rated.boost
    p = plan(rated)
    pillcls, pilltxt = ("lockpill", "LOCK") if rated.lockable else ("valpill", "value")
    method = html.escape(p.as_text()) if p else ""
    notes = html.escape("; ".join(rated.notes))
    return f"""<tr class="{'lock' if rated.lockable else ''}">
  <td class="l">{html.escape(b.bookie)}</td>
  <td class="l">{html.escape(b.event)}<br><span class="muted">{html.escape(b.selection)}</span></td>
  <td>{b.boosted_odds:.2f}</td>
  <td>£{rated.back_stake:,.2f}</td>
  <td>£{p.back_returns:,.2f}</td>
  <td>{rated.quote.lay_odds:.2f} <span class="muted">{html.escape(rated.quote.exchange)}</span></td>
  <td>£{rated.lay_stake:,.2f}</td>
  <td>£{rated.liability:,.2f}</td>
  <td>{_money(rated.profit_if_wins)}</td>
  <td>{_money(rated.profit_if_loses)}</td>
  <td class="rating"><span class="pill {pillcls}">{pilltxt}</span> {rated.rating:.2f}%</td>
  <td class="l"><details><summary>method</summary><pre>{method}</pre>
      {f'<div class="muted">{notes}</div>' if notes else ''}</details></td>
</tr>"""


def render(rateds: list[RatedBoost], *, stake: float, alert_rating: float) -> str:
    matched = sorted([r for r in rateds if r.quote is not None],
                     key=lambda r: r.rating, reverse=True)
    manual = [r for r in rateds if r.quote is None]
    nlock = sum(1 for r in matched if r.lockable and r.rating >= alert_rating)

    head = (
        '<tr><th class="l">Book</th><th class="l">Event / selection</th><th>Back</th>'
        '<th>Stake</th><th>Returns</th><th>Lay</th><th>Lay £</th><th>Liability</th>'
        '<th>If wins</th><th>If loses</th><th>Rating</th><th class="l">Method</th></tr>'
    )
    rows = "\n".join(_row(r) for r in matched) or \
        '<tr><td colspan="12" class="muted">No layable boosts right now.</td></tr>'

    manual_html = ""
    if manual:
        items = "".join(
            f'<li>{html.escape(r.boost.bookie)} — {html.escape(r.boost.event)}: '
            f'{html.escape(r.boost.selection)} @ {r.boost.boosted_odds:.2f} '
            f'<span class="muted">({html.escape("; ".join(r.notes))})</span></li>'
            for r in manual)
        manual_html = f"<h2>Manual-only (no exchange runner to lay)</h2><ul>{items}</ul>"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>boostmatcher</title><style>{_CSS}</style>
<header>
  <h1>boostmatcher — live price-boost value</h1>
  <div class="sub">Priced at £{stake:,.0f} stake · {len(matched)} layable ·
    {nlock} locking ≥ {alert_rating:.1f}% · updated {ts}</div>
</header>
<div class="wrap">
  <table><thead>{head}</thead><tbody>{rows}</tbody></table>
  {manual_html}
  <p class="muted" style="margin-top:24px">All figures in £. Place every bet
  manually. A “LOCK” profits whichever way the result goes; “value” has one
  slightly-negative leg taken for the +EV. Lay only up to the liquidity shown.</p>
</div></html>"""


def write(rateds: list[RatedBoost], path: str, *, stake: float, alert_rating: float) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(rateds, stake=stake, alert_rating=alert_rating))


def render_value(vbets, *, bankroll: float) -> str:
    """HTML for VALUE mode: boost vs exchange fair price, edge %, suggested stake."""
    rows = sorted(vbets, key=lambda v: v.edge_pct, reverse=True)
    body = []
    for v in rows:
        b = v.boost
        fair = f"{v.fair:.2f}" if v.fair else "&mdash;"
        edgecls = "pos" if v.edge_pct > 0 else "neg"
        staketxt = f"£{v.kelly_stake:,.2f}" if v.kelly_stake > 0 else "&mdash;"
        rowcls = "lock" if v.kelly_stake > 0 else ""
        body.append(f"""<tr class="{rowcls}">
  <td class="l">{html.escape(b.bookie)}</td>
  <td class="l">{html.escape(b.event or '&mdash;')}<br>
      <span class="muted">{html.escape(b.selection)}</span></td>
  <td>{b.boosted_odds:.2f}</td><td>{fair}</td>
  <td class="rating"><span class="{edgecls}">{v.edge_pct:+.1f}%</span></td>
  <td>{staketxt}</td>
  <td class="l muted">{html.escape('; '.join(v.notes))}</td>
</tr>""")
    rows_html = "\n".join(body) or '<tr><td colspan="7" class="muted">No boosts.</td></tr>'
    nbet = sum(1 for v in vbets if v.kelly_stake > 0)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    head = ('<tr><th class="l">Book</th><th class="l">Event / selection</th><th>Boost</th>'
            '<th>Fair</th><th>Edge</th><th>Stake</th><th class="l">Notes</th></tr>')
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>boostmatcher — value</title><style>{_CSS}</style>
<header><h1>boostmatcher — boost value vs exchange fair price</h1>
<div class="sub">Bankroll £{bankroll:,.0f} · quarter-Kelly · {nbet} genuinely +EV ·
  updated {ts}</div></header>
<div class="wrap"><table><thead>{head}</thead><tbody>{rows_html}</tbody></table>
<p class="muted" style="margin-top:24px">Edge = boosted price vs the margin-free
exchange price. Positive = genuinely +EV. These are <b>value bets, not risk-free</b>
— you lose individual bets; profit only emerges over many +EV bets, and +EV
betting still gets accounts limited. "Can't verify" = the exchange doesn't price
that selection (most player props).</p></div></html>"""


def write_value(vbets, path: str, *, bankroll: float) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_value(vbets, bankroll=bankroll))


def render_feed(boosts) -> str:
    """The website: live multi-book boost feed + a built-in calculator.

    Lists every scraped boost (bookie, selection, odds), sortable. Clicking a
    boost pre-fills the calculator below it, so you go from "what's boosted" to
    "what to place" in one click. Self-contained; the boosts are baked in as JSON.
    """
    import json as _json
    data = _json.dumps([
        {"bookie": b.bookie, "sel": b.selection, "odds": round(b.boosted_odds, 2),
         "prev": b.original_odds, "event": b.event}
        for b in sorted(boosts, key=lambda x: x.boosted_odds)
    ])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nbk = len({b.bookie for b in boosts})
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>boostmatcher feed</title><style>{_CSS}
.feed td {{ cursor: pointer; }} .feed tr:hover td {{ background: rgba(56,139,253,.12); }}
.calc {{ margin-top: 28px; padding: 18px; border:1px solid #30363d; border-radius:14px; background:#161b22; }}
.calc h2 {{ margin:0 0 4px; color:#e6edf3; }} .tabs {{ display:flex; gap:8px; margin:12px 0; }}
.tab {{ flex:1; text-align:center; padding:9px; border:1px solid #30363d; border-radius:9px; background:#0d1117; cursor:pointer; font-weight:600; font-size:13px; }}
.tab.active {{ background:#1f6feb; border-color:#1f6feb; color:#fff; }}
.field {{ display:inline-block; margin:6px 12px 6px 0; }} .field label {{ font-size:12px; color:#8b949e; display:block; }}
.field input {{ width:110px; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:8px; color:#e6edf3; font-size:16px; }}
#legs input {{ width:90px; margin-right:6px; }}
.res {{ margin-top:10px; font-size:18px; font-weight:800; }}
.calc .hidden {{ display:none; }}
</style>
<header><h1>boostmatcher — live boost feed</h1>
<div class="sub">{len(boosts)} boosts across {nbk} books · updated {ts} · click a boost to price it</div></header>
<div class="wrap">
  <table class="feed"><thead><tr><th class="l">Book</th><th class="l">Selection</th>
    <th>Boost</th><th>Was</th></tr></thead><tbody id="rows"></tbody></table>

  <div class="calc">
    <h2 id="calcTitle">Calculator — click a boost above, or type below</h2>
    <div class="tabs">
      <div class="tab active" data-m="lay">Lay (exchange)</div>
      <div class="tab" data-m="cover">Cover (other book)</div>
      <div class="tab" data-m="value">Value</div>
    </div>
    <div class="field"><label>Boost odds</label><input id="back" type="number" step="0.01" value="2.5"></div>
    <div class="field"><label>Stake £</label><input id="stake" type="number" value="25"></div>
    <span id="layf"><div class="field"><label>Lay odds</label><input id="lay" type="number" step="0.01" value="2.32"></div>
      <div class="field"><label>Comm %</label><input id="comm" type="number" step="0.5" value="2"></div></span>
    <span id="covf" class="hidden"><div class="field"><label>Opposite odds (space-sep)</label>
      <input id="legs2" value="3.5 4.0" style="width:160px"></div></span>
    <span id="valf" class="hidden"><div class="field"><label>Fair odds</label><input id="fair" type="number" step="0.01" value="2.28"></div></span>
    <div class="res" id="res"></div>
  </div>
  <p class="muted" style="margin-top:18px">Lay &amp; Cover are risk-free locks; Value is +EV (not risk-free).
  Most boosts are props with no lay/cover market — the calculator will say so.</p>
</div>
<script>
const BOOSTS = {data};
const $ = i => document.getElementById(i);
const gbp = x => (x<0?'-£':'£') + Math.abs(x).toFixed(2);
let mode = 'lay';
function rows() {{
  $('rows').innerHTML = BOOSTS.map((b,i) => `<tr data-i="${{i}}"><td class="l">${{b.bookie}}</td>
    <td class="l">${{b.sel}}</td><td><b>${{b.odds}}</b></td><td class="muted">${{b.prev||'—'}}</td></tr>`).join('');
  document.querySelectorAll('#rows tr').forEach(tr => tr.onclick = () => {{
    const b = BOOSTS[tr.dataset.i]; $('back').value = b.odds;
    $('calcTitle').textContent = `${{b.sel}} — ${{b.bookie}} @ ${{b.odds}}`; calc();
    $('back').scrollIntoView({{behavior:'smooth', block:'center'}});
  }});
}}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); t.classList.add('active');
  mode = t.dataset.m;
  $('layf').classList.toggle('hidden', mode!=='lay');
  $('covf').classList.toggle('hidden', mode!=='cover');
  $('valf').classList.toggle('hidden', mode!=='value'); calc();
}});
function calc() {{
  const B = parseFloat($('back').value), S = parseFloat($('stake').value);
  const r = $('res'); if(!(B>1&&S>0)){{r.textContent='';return;}}
  if (mode==='lay') {{
    const L=parseFloat($('lay').value), c=parseFloat($('comm').value)/100;
    if(!(L>1)){{r.textContent='';return;}}
    const ls=(B*S)/(L-c), liab=ls*(L-1), win=S*(B-1)-liab, lose=ls*(1-c)-S, lk=Math.min(win,lose);
    r.innerHTML = lk>=0 ? `<span class="pos">LOCK ${{gbp(lk)}}</span> — lay ${{gbp(ls)}} @ ${{L}} (liability ${{gbp(liab)}})`
      : `<span class="neg">No lock (${{gbp(lk)}})</span> — boost too small to beat ${{L}}`;
  }} else if (mode==='cover') {{
    const odds=$('legs2').value.split(/\\s+/).map(Number).filter(x=>x>1);
    if(!odds.length){{r.textContent='enter opposite odds';return;}}
    const R=S*B, ls=odds.map(o=>R/o), tot=S+ls.reduce((a,b)=>a+b,0), pf=R-tot;
    const bs=1/B+odds.reduce((a,o)=>a+1/o,0);
    r.innerHTML = bs<1 ? `<span class="pos">LOCK ${{gbp(pf)}}</span> (${{(100*pf/tot).toFixed(1)}}% ROI) — back ${{gbp(S)}} + ${{ls.map((s,i)=>gbp(s)+'@'+odds[i]).join(' + ')}}`
      : `<span class="neg">No lock</span> — combined book ${{(bs*100).toFixed(1)}}% > 100%`;
  }} else {{
    const F=parseFloat($('fair').value); if(!(F>1)){{r.textContent='';return;}}
    const edge=(B/F-1)*100;
    r.innerHTML = edge>=2 ? `<span class="pos">+${{edge.toFixed(1)}}% edge</span> — genuinely +EV vs fair ${{F}} (value bet, not risk-free)`
      : `<span class="neg">${{edge>=0?'+':''}}${{edge.toFixed(1)}}% edge</span> — not worth it vs fair ${{F}}`;
  }}
}}
['back','stake','lay','comm','legs2','fair'].forEach(i=>$(i).addEventListener('input',calc));
rows(); calc();
</script></html>"""


def write_feed(boosts, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_feed(boosts))
