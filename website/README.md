# OfferPilot — marketing site

A single, self-contained landing page (`index.html`) to sell the product. No build
step, no dependencies — just one HTML file with inline CSS + JS.

## Preview it locally

```powershell
# from the repo root
.venv\Scripts\python.exe -m http.server 8530 --directory website
```
Then open http://localhost:8530

## Put it online (pick one — all free)

**Netlify (drag & drop, ~1 min, easiest)**
1. Go to https://app.netlify.com/drop
2. Drag the whole `website` folder onto the page.
3. You get a live `https://…netlify.app` URL instantly. Add a custom domain in Site settings.

**Vercel**
1. `npm i -g vercel` then run `vercel` inside the `website` folder, or import the repo at vercel.com.

**GitHub Pages**
1. Push the repo to GitHub.
2. Settings → Pages → deploy from branch, folder `/website` (or move `index.html` to repo root).

**Cloudflare Pages** — connect the repo, set the build output directory to `website`.

## Where the buttons go (important)

All "Start free / Sign in" buttons open your **app**. The destination is one line
near the top of the `<script>` in `index.html`:

```js
const APP_URL = "http://localhost:8501";   // your tool's address
```
- **Using it yourself now:** leave it as `localhost:8501`. Start the app first
  (`python.exe -m streamlit run jobtracker/dashboard.py`), then open the website and
  click Start free — it drops you into the tool.
- **Going live later:** change that one line to your hosted app URL
  (e.g. `https://app.offerpilot.com`) and re-deploy. Nothing else to change.

## Customising

Everything is in `index.html`:
- **Brand name / logo** — search for `OfferPilot` and the `✈` mark; change the text/emoji.
- **Colours** — the `:root` CSS variables at the top (`--b1/--b2/--b3` are the gradient).
- **Copy, pricing, FAQ** — plain HTML in the relevant `<section>`s.
- **"Start free" buttons** — currently `href="#"`. Point them at your app/sign-up URL
  (e.g. your Streamlit dashboard or a waitlist form).
- **Trust logos** — the firm names in the `.marquee` block.

> Footer note already states it's not affiliated with the firms shown — keep that if you
> display company names.
