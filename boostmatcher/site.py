"""The public-facing BoostLock website: a polished, sellable single page.

Combines the live multi-book boost feed, a built-in lay/cover/value calculator
(Matchbook as the default exchange), and complete beginner instructions so
someone with zero prior knowledge can follow it. Self-contained static HTML —
no build step, no external network — so it deploys anywhere (GitHub Pages etc.).

Honesty is baked into the copy on purpose: it's a matched-betting *tool*, not a
money printer. Most boosts don't lock (the calculator says so), accounts get
limited, and there are 18+/responsible-gambling notices throughout — which also
happens to make it look more trustworthy, not less.
"""
from __future__ import annotations

import json
from datetime import datetime


def render_site(boosts, *, lockable_only: bool = True) -> str:
    """Render the site. By default only LOCKABLE boosts are shown — props/combos
    with no exchange market are filtered out (the rest are counted as 'hidden')."""
    from .lockability import classify
    rated = [(b, classify(b.selection)) for b in boosts]
    n_lockable = sum(1 for _, l in rated if l.lockable)
    shown = [(b, l) for b, l in rated if l.lockable or not lockable_only]

    data = json.dumps([
        {"bookie": b.bookie, "sel": b.selection, "odds": round(b.boosted_odds, 2),
         "prev": b.original_odds, "market": l.market, "lay": l.lay,
         "note": l.note, "lockable": l.lockable}
        for b, l in sorted(shown, key=lambda x: x[0].boosted_odds)
    ])
    return (_TEMPLATE
            .replace("__BOOSTS_JSON__", data)
            .replace("__COUNT__", str(n_lockable))
            .replace("__SCANNED__", str(len(boosts)))
            .replace("__HIDDEN__", str(len(boosts) - n_lockable))
            .replace("__BOOKS__", str(len({b.bookie for b in boosts})))
            .replace("__TS__", datetime.now().strftime("%d %b %Y, %H:%M")))


def write_site(boosts, path: str, *, lockable_only: bool = True) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_site(boosts, lockable_only=lockable_only))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BoostLock — turn bookmaker price boosts into locked-in profit</title>
<meta name="description" content="BoostLock finds boosted odds across UK bookmakers and shows you the exact stakes to place so you lock in profit whatever the result. A matched-betting tool. 18+.">
<style>
  :root{
    --bg:#0a0e17; --panel:#111826; --panel2:#0e1420; --line:#1d2738;
    --text:#e8eef7; --muted:#93a0b5; --accent:#19e29a; --accent2:#11b87e;
    --blue:#4d8dff; --red:#ff5c5c; --amber:#ffb020;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--text);
    font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  a{color:inherit;text-decoration:none}
  .wrap{max-width:980px;margin:0 auto;padding:0 20px}
  h1,h2,h3{line-height:1.2;margin:0}
  /* nav */
  nav{position:sticky;top:0;z-index:30;background:rgba(10,14,23,.85);backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line)}
  nav .wrap{display:flex;align-items:center;gap:20px;height:62px}
  .brand{font-weight:800;font-size:19px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
  .brand .dot{width:11px;height:11px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent)}
  nav .links{display:flex;gap:22px;margin-left:auto;font-size:14px;color:var(--muted)}
  nav .links a:hover{color:var(--text)}
  .chip{font-size:12px;font-weight:700;border:1px solid var(--line);border-radius:999px;padding:4px 10px;color:var(--muted)}
  @media(max-width:720px){nav .links{display:none}}
  /* hero */
  .hero{padding:74px 0 50px;text-align:center}
  .hero .tagchip{display:inline-block;font-size:12.5px;font-weight:700;color:var(--accent);
    background:rgba(25,226,154,.1);border:1px solid rgba(25,226,154,.25);border-radius:999px;padding:6px 14px;margin-bottom:22px}
  .hero h1{font-size:46px;font-weight:850;letter-spacing:-.03em}
  .hero h1 .g{background:linear-gradient(90deg,var(--accent),#5ad);-webkit-background-clip:text;background-clip:text;color:transparent}
  .hero p{font-size:18.5px;color:var(--muted);max-width:620px;margin:18px auto 0}
  .cta{display:flex;gap:12px;justify-content:center;margin-top:30px;flex-wrap:wrap}
  .btn{display:inline-block;padding:13px 22px;border-radius:11px;font-weight:700;font-size:15px;cursor:pointer;border:1px solid transparent}
  .btn.primary{background:var(--accent);color:#04130d}
  .btn.primary:hover{background:var(--accent2)}
  .btn.ghost{border-color:var(--line);color:var(--text)}
  .btn.ghost:hover{background:var(--panel)}
  .heronote{margin-top:18px;font-size:13px;color:var(--muted)}
  @media(max-width:720px){.hero h1{font-size:33px}.hero{padding:48px 0 36px}}
  /* sections */
  section{padding:54px 0;border-top:1px solid var(--line)}
  .eyebrow{color:var(--accent);font-weight:700;font-size:13px;letter-spacing:.08em;text-transform:uppercase}
  .h2{font-size:30px;font-weight:800;letter-spacing:-.02em;margin:8px 0 6px}
  .lead{color:var(--muted);max-width:680px;margin-bottom:8px}
  /* steps */
  .steps{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:26px}
  @media(max-width:720px){.steps{grid-template-columns:1fr}}
  .step{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px}
  .step .n{width:32px;height:32px;border-radius:9px;background:rgba(25,226,154,.12);color:var(--accent);
    font-weight:800;display:flex;align-items:center;justify-content:center;margin-bottom:12px}
  .step h3{font-size:17px;margin-bottom:6px}
  .step p{color:var(--muted);font-size:14.5px;margin:0}
  .step b{color:var(--text)}
  /* mode cards */
  .modes{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:24px}
  @media(max-width:720px){.modes{grid-template-columns:1fr}}
  .mode{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:18px}
  .mode .tag{font-size:12px;font-weight:800;padding:3px 9px;border-radius:7px;display:inline-block;margin-bottom:8px}
  .mode.l .tag{background:rgba(77,141,255,.16);color:var(--blue)}
  .mode.c .tag{background:rgba(25,226,154,.14);color:var(--accent)}
  .mode.v .tag{background:rgba(255,176,32,.15);color:var(--amber)}
  .mode p{color:var(--muted);font-size:14px;margin:6px 0 0}
  /* feed */
  table{width:100%;border-collapse:collapse;margin-top:18px;font-size:15px}
  th,td{text-align:right;padding:12px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
  td.l,th.l{text-align:left;white-space:normal}
  .feed tbody tr{cursor:pointer}
  .feed tbody tr:hover td{background:rgba(77,141,255,.09)}
  .bk{font-size:12px;font-weight:700;color:var(--muted);text-transform:capitalize}
  .od{font-weight:800}
  .pill{font-size:11px;font-weight:800;padding:2px 7px;border-radius:6px;background:rgba(255,92,92,.14);color:var(--red)}
  /* calculator */
  .calc{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin-top:22px}
  .tabs{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}
  .tab{flex:1;min-width:120px;text-align:center;padding:11px;border:1px solid var(--line);border-radius:11px;
    background:var(--panel2);cursor:pointer;font-weight:700;font-size:14px;color:var(--muted)}
  .tab.active{background:var(--accent);border-color:var(--accent);color:#04130d}
  .grid{display:flex;flex-wrap:wrap;gap:14px}
  .f{flex:1;min-width:130px}
  .f label{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}
  .f input,.f select{width:100%;padding:12px;background:var(--bg);border:1px solid var(--line);
    border-radius:10px;color:var(--text);font-size:17px}
  .f input:focus,.f select:focus{outline:none;border-color:var(--accent)}
  .hidden{display:none}
  .out{margin-top:18px;padding:16px 18px;border-radius:13px;background:var(--panel2);border:1px solid var(--line)}
  .out .v{font-size:24px;font-weight:850}
  .out .sub{color:var(--muted);font-size:14px;margin-top:4px}
  .pos{color:var(--accent)} .neg{color:var(--red)}
  .out ol{margin:12px 0 0;padding-left:20px;color:var(--text);font-size:14.5px}
  .out ol li{margin:5px 0}
  /* example + faq */
  .ex{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px;margin-top:22px}
  .ex .row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px dashed var(--line);font-size:15px}
  .ex .row:last-child{border:0}
  .ex .muted{color:var(--muted)}
  details{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:4px 18px;margin-top:12px}
  details summary{cursor:pointer;font-weight:700;padding:14px 0;list-style:none}
  details summary::-webkit-details-marker{display:none}
  details p{color:var(--muted);margin:0 0 16px;font-size:14.5px}
  /* footer */
  footer{border-top:1px solid var(--line);padding:34px 0 60px;color:var(--muted);font-size:13px}
  footer .rg{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
  footer .age{font-weight:800;border:2px solid var(--muted);border-radius:50%;width:34px;height:34px;
    display:flex;align-items:center;justify-content:center;font-size:13px}
  .warn{background:rgba(255,176,32,.08);border:1px solid rgba(255,176,32,.25);color:#f3d6a0;
    border-radius:12px;padding:14px 16px;font-size:13.5px;margin-top:18px}
</style>
</head>
<body>

<nav><div class="wrap">
  <div class="brand"><span class="dot"></span>BoostLock</div>
  <div class="links">
    <a href="#how">How it works</a><a href="#feed">Today's boosts</a>
    <a href="#calc">Calculator</a><a href="#risks">Risks &amp; FAQ</a>
  </div>
  <span class="chip">18+ · matched betting tool</span>
</div></nav>

<header class="hero"><div class="wrap">
  <span class="tagchip">Live · __COUNT__ lockable · scanned __SCANNED__ boosts across __BOOKS__ books · __TS__</span>
  <h1>Turn bookmaker price boosts<br>into <span class="g">locked-in profit</span></h1>
  <p>Bookies boost odds to lure you in. BoostLock shows you how to back the boost <i>and</i> cover
     the other side — so you keep a profit <b>whatever the result</b>. No tipping, no luck.</p>
  <div class="cta">
    <a class="btn primary" href="#feed">See today's boosts</a>
    <a class="btn ghost" href="#how">How it works (2 min)</a>
  </div>
  <div class="heronote">Not every boost is profitable — the calculator tells you which ones lock. 18+ only.</div>
</div></header>

<section id="how"><div class="wrap">
  <div class="eyebrow">How it works</div>
  <div class="h2">Four steps. No betting knowledge needed.</div>
  <p class="lead">The idea: a "boost" is the bookie offering better-than-normal odds on a pick.
     If you back the boost and at the same time bet on the <b>opposite</b> result on a betting
     <b>exchange</b> (we use <b>Matchbook</b>), the two bets cancel out — and the boost leaves you
     in profit no matter what happens. That's "matched betting", and it's legal and tax-free in the UK.</p>
  <div class="steps">
    <div class="step"><div class="n">1</div><h3>Open two accounts</h3>
      <p>A <b>bookmaker</b> (e.g. bet365, William Hill — wherever the boost is) and a betting
         <b>exchange</b>, <b>Matchbook</b>. Deposit a starting bank (£50–£200 is plenty) into each.</p></div>
    <div class="step"><div class="n">2</div><h3>Pick a boost from the live list</h3>
      <p>Scroll to <a href="#feed" style="color:var(--accent)">today's boosts</a>. Choose a
         <b>single-outcome</b> one — a team to win, over/under goals, a player to score. Avoid combos
         and obscure props (you usually can't cover those — see Risks).</p></div>
    <div class="step"><div class="n">3</div><h3>Let the calculator do the maths</h3>
      <p>Click the boost — it drops into the <a href="#calc" style="color:var(--accent)">calculator</a>.
         Type the <b>lay odds</b> you see for that same pick on Matchbook. It tells you the exact two
         stakes and whether it <b>locks a profit</b>.</p></div>
    <div class="step"><div class="n">4</div><h3>Place both bets</h3>
      <p><b>Back</b> the boost at the bookie for the first stake. <b>Lay</b> it on Matchbook for the
         second. Done — you keep the locked profit whichever way the match goes. Repeat on the next one.</p></div>
  </div>
  <div class="warn"><b>Plain English:</b> "Back" = a normal bet that something happens. "Lay" (on the
     exchange) = a bet that it <b>won't</b> happen. "Liability" = the money the exchange holds in case
     your lay loses. The calculator works all of this out — you just copy the two numbers.</div>
</div></section>

<section><div class="wrap">
  <div class="eyebrow">Three ways to lock a boost</div>
  <div class="h2">Pick whichever the calculator says works</div>
  <div class="modes">
    <div class="mode l"><span class="tag">LAY · risk-free</span><h3>Lay on Matchbook</h3>
      <p>Back the boost, lay the same pick on the exchange. The cleanest lock — best for match result,
         over/under and goalscorer boosts that Matchbook prices.</p></div>
    <div class="mode c"><span class="tag">COVER · risk-free</span><h3>Cover at another book</h3>
      <p>No exchange market? Back the <b>opposite</b> result at a second bookmaker instead. Locks profit
         when the two prices combine under 100%.</p></div>
    <div class="mode v"><span class="tag">VALUE · +EV</span><h3>Bet it straight (value)</h3>
      <p>When neither locks, the boost can still be <b>+EV</b> if it beats the true price. Profitable over
         time — but <b>not</b> risk-free. Stake small.</p></div>
  </div>
</div></section>

<section id="feed"><div class="wrap">
  <div class="eyebrow">Live feed · lockable only</div>
  <div class="h2">Boosts you can actually lock today</div>
  <p class="lead">We scanned <b>__SCANNED__</b> boosts across <b>__BOOKS__</b> books and
     <b>hid __HIDDEN__</b> props/combos that have no exchange market to lay or cover. What's left below
     <i>can</i> be locked. Click a row to price it, and use the <b>"What to lay"</b> column to find the
     market on the exchange.</p>
  <table class="feed"><thead><tr><th class="l">Bookmaker</th><th class="l">Selection</th>
    <th>Boost</th><th class="l">What to lay on the exchange</th></tr></thead><tbody id="rows"></tbody></table>
  <div class="warn" id="emptynote" style="display:none">No lockable boosts in this scan — every boost
     today was a prop or combo. That's common; check back when there are mainstream match/goals boosts.</div>
</div></section>

<section id="calc"><div class="wrap">
  <div class="eyebrow">Calculator</div>
  <div class="h2" id="calcTitle">Price a boost</div>
  <p class="lead">Click a boost above, or type the numbers in. Everything in £.</p>
  <div class="calc">
    <div class="tabs">
      <div class="tab active" data-m="lay">Lay (Matchbook)</div>
      <div class="tab" data-m="cover">Cover (other book)</div>
      <div class="tab" data-m="value">Value</div>
    </div>
    <div class="grid">
      <div class="f"><label>Boost odds (at the bookie)</label><input id="back" type="number" step="0.01" value="2.50"></div>
      <div class="f"><label>Your stake (£)</label><input id="stake" type="number" value="25"></div>
      <span id="layf" style="display:contents">
        <div class="f"><label>Lay odds (Matchbook)</label><input id="lay" type="number" step="0.01" value="2.32"></div>
        <div class="f"><label>Exchange &amp; commission</label><select id="exch">
          <option value="0.015" selected>Matchbook — taker 1.5%</option>
          <option value="0.0075">Matchbook — maker 0.75%</option>
          <option value="0.02">Smarkets — 2%</option>
          <option value="0.01">Smarkets Pro — 1%</option>
          <option value="0.02">Betdaq — 2%</option>
          <option value="0.06">Betfair — 6%</option>
          <option value="0.02">Betfair — high-volume 2%</option>
          <option value="0">New-account offer — 0%</option>
        </select></div>
      </span>
      <span id="covf" class="hidden" style="display:none">
        <div class="f" style="flex:2"><label>Opposite-result odds at other book(s), space-separated</label>
          <input id="legs" value="3.5 4.0"></div></span>
      <span id="valf" class="hidden" style="display:none">
        <div class="f"><label>Fair odds (exchange price)</label><input id="fair" type="number" step="0.01" value="2.05"></div></span>
    </div>
    <div class="out" id="out"></div>
  </div>
</div></section>

<section><div class="wrap">
  <div class="eyebrow">Worked example</div>
  <div class="h2">A real lock, start to finish</div>
  <div class="ex">
    <div class="row"><span class="muted">Boost (bet365)</span><span><b>France to win</b> — was 2.10, boosted to <b>2.50</b></span></div>
    <div class="row"><span class="muted">Step 1 — back</span><span>Stake <b>£25</b> on France @ 2.50 at bet365</span></div>
    <div class="row"><span class="muted">Step 2 — lay</span><span>Lay <b>£27.11</b> on France @ 2.32 on Matchbook (1.5% comm; it holds <b>£35.79</b> liability)</span></div>
    <div class="row"><span class="muted">If France win</span><span class="pos">+£1.71</span></div>
    <div class="row"><span class="muted">If France draw or lose</span><span class="pos">+£1.71</span></div>
    <div class="row"><span class="muted">Result</span><span><b class="pos">£1.71 locked</b> — guaranteed, whatever happens</span></div>
  </div>
  <p class="lead" style="margin-top:14px">Do a few of those a day and it adds up. The calculator above produced these exact
     numbers — change the odds to match what you actually see.</p>
</div></section>

<section id="risks"><div class="wrap">
  <div class="eyebrow">Risks &amp; FAQ</div>
  <div class="h2">Read this before you stake a penny</div>
  <details open><summary>Is this really risk-free?</summary>
    <p>The <b>lay</b> and <b>cover</b> methods are — when the calculator shows a lock, you profit whatever
       happens, because the two bets cancel out. The <b>value</b> method is not: it's a +EV bet you'll
       sometimes lose. Never use the value method with money you can't afford to lose.</p></details>
  <details><summary>Why do most boosts say "no lock"?</summary>
    <p>Bookies mostly boost <b>combos</b> and <b>player props</b> (shots, cards, fouls) — exactly the bets
       you can't lay on an exchange or cover at another book, because no opposite market exists. That's
       deliberate. Look for <b>single-outcome</b> boosts (match result, over/under goals, a player to
       score), which Matchbook prices and you can lock.</p></details>
  <details><summary>Will I get my accounts banned?</summary>
    <p>Possibly limited ("gubbed"), over time — bookies don't like consistent winners. It's rarely a true
       ban, just smaller maximum stakes. Spread your activity, don't only ever bet boosts, and treat it as
       a steady side-income, not a salary.</p></details>
  <details><summary>What's the catch with the maths?</summary>
    <p>Exchange odds move and liquidity can be thin — if you can't get your full lay matched, you're not
       fully covered. Always lay <b>before</b> the price drifts, and check there's enough money available
       on Matchbook for your liability.</p></details>
  <div class="warn" style="margin-top:20px"><b>This is a tool, not advice.</b> BoostLock shows you the maths;
     it does not place bets and is not financial or betting advice. Gambling involves risk. Only stake what
     you can afford to lose.</div>
</div></section>

<footer><div class="wrap">
  <div class="rg"><span class="age">18+</span>
    <span>Bet responsibly. If gambling is a problem for you, visit
      <a href="https://www.begambleaware.org" style="color:var(--accent)">BeGambleAware.org</a>
      or call the National Gambling Helpline on 0808 8020 133.</span></div>
  <div>BoostLock is an educational matched-betting calculator. It does not take bets, hold funds, or
     guarantee profit. Odds shown are indicative and may be out of date — always confirm live prices
     before betting. Not affiliated with any bookmaker or exchange.</div>
</div></footer>

<script>
const BOOSTS = __BOOSTS_JSON__;
const $ = i => document.getElementById(i);
const gbp = x => (x<0?'-£':'£') + Math.abs(x).toFixed(2);
let mode = 'lay';

function renderRows(){
  if(!BOOSTS.length){ $('emptynote').style.display='block'; $('rows').innerHTML=''; return; }
  $('rows').innerHTML = BOOSTS.slice().reverse().map((b,i)=>`<tr data-i="${BOOSTS.length-1-i}">
    <td class="l"><span class="bk">${b.bookie}</span></td>
    <td class="l">${b.sel}</td>
    <td><span class="od">${b.odds}</span></td>
    <td class="l">Lay <b>${b.lay||b.sel}</b><br><span class="muted">${b.market} market</span></td></tr>`).join('');
  document.querySelectorAll('#rows tr[data-i]').forEach(tr=>tr.onclick=()=>{
    const b=BOOSTS[tr.dataset.i]; $('back').value=b.odds;
    $('calcTitle').textContent=`Lay "${b.lay||b.sel}" in the ${b.market} market — ${b.bookie} boost @ ${b.odds}`;
    document.getElementById('calc').scrollIntoView({behavior:'smooth',block:'start'}); calc();
  });
}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); t.classList.add('active');
  mode=t.dataset.m;
  $('layf').style.display = mode==='lay'?'contents':'none';
  $('covf').style.display = mode==='cover'?'contents':'none';
  $('valf').style.display = mode==='value'?'contents':'none';
  calc();
});
function calc(){
  const B=parseFloat($('back').value), S=parseFloat($('stake').value), o=$('out');
  if(!(B>1&&S>0)){o.innerHTML='<span class="muted">Enter the boost odds and your stake…</span>';return;}
  if(mode==='lay'){
    const L=parseFloat($('lay').value), c=parseFloat($('exch').value);
    if(!(L>1)){o.innerHTML='<span class="muted">Enter the Matchbook lay odds…</span>';return;}
    const ls=(B*S)/(L-c), liab=ls*(L-1), win=S*(B-1)-liab, lose=ls*(1-c)-S, lk=Math.min(win,lose);
    o.innerHTML = lk>=0
      ? `<div class="v pos">RISK-FREE LOCK · ${gbp(lk)}</div><div class="sub">Guaranteed, whatever the result.</div>
         <ol><li>BACK <b>${gbp(S)}</b> on the boost @ <b>${B}</b> at the bookie</li>
         <li>LAY <b>${gbp(ls)}</b> @ <b>${L}</b> on Matchbook (it holds <b>${gbp(liab)}</b> liability)</li>
         <li>Profit either way: <b class="pos">${gbp(lk)}</b></li></ol>`
      : `<div class="v neg">No lock · ${gbp(lk)}</div><div class="sub">The boost (${B}) is too small to beat the lay odds (${L}). Skip it, or check the Cover/Value tabs.</div>`;
  } else if(mode==='cover'){
    const odds=$('legs').value.split(/\s+/).map(Number).filter(x=>x>1);
    if(!odds.length){o.innerHTML='<span class="muted">Enter the opposite-result odds…</span>';return;}
    const R=S*B, ls=odds.map(x=>R/x), tot=S+ls.reduce((a,b)=>a+b,0), pf=R-tot, bs=1/B+odds.reduce((a,x)=>a+1/x,0);
    o.innerHTML = bs<1
      ? `<div class="v pos">CROSS-BOOK LOCK · ${gbp(pf)}</div><div class="sub">${(100*pf/tot).toFixed(1)}% return · combined book ${(bs*100).toFixed(1)}%</div>
         <ol><li>BACK <b>${gbp(S)}</b> on the boost @ <b>${B}</b></li>
         ${ls.map((s,i)=>`<li>BACK <b>${gbp(s)}</b> on the opposite @ <b>${odds[i]}</b> at another book</li>`).join('')}
         <li>Profit either way: <b class="pos">${gbp(pf)}</b></li></ol>`
      : `<div class="v neg">No lock</div><div class="sub">Combined book is ${(bs*100).toFixed(1)}% (needs under 100%). The other book's price isn't generous enough.</div>`;
  } else {
    const F=parseFloat($('fair').value); if(!(F>1)){o.innerHTML='<span class="muted">Enter the fair (exchange) odds…</span>';return;}
    const edge=(B/F-1)*100;
    o.innerHTML = edge>=2
      ? `<div class="v pos">+${edge.toFixed(1)}% value</div><div class="sub">The boost (${B}) genuinely beats the true price (${F}). A <b>value bet — not risk-free</b>. Stake small.</div>`
      : `<div class="v neg">${edge>=0?'+':''}${edge.toFixed(1)}% — skip</div><div class="sub">The boost doesn't beat the true price (${F}) by enough to be worth it.</div>`;
  }
}
['back','stake','lay','exch','legs','fair'].forEach(i=>$(i).addEventListener('input',calc));
renderRows(); calc();
</script>
</body>
</html>
"""
