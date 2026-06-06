# Put OfferPilot online (no more localhost)

Goal: a permanent web link to your tool, usable from any device, no PowerShell.
This is a **one-time setup**. It's all done in your **web browser** — no commands.

You'll create two free accounts (GitHub + Streamlit) and connect them. Budget
~30 minutes the first time. After that, it just runs.

I've already prepared every file the host needs (`requirements.txt`, `packages.txt`,
`.gitignore`, secrets handling). You only do the clicking below.

---

## STEP 1 — Put the code on GitHub (using GitHub Desktop — easiest)

Claude has already packaged your code into a local repository (secrets excluded).
You just publish it with a free, click-only app.

1. Go to **https://desktop.github.com** → **Download for Windows** → run the
   installer (just click through it).
2. Open **GitHub Desktop**. It says "Sign in to GitHub.com" → click it → your browser
   opens → **Sign up** for a free GitHub account (or sign in) → click **Authorize**.
   You'll come back to GitHub Desktop, now signed in.
3. In GitHub Desktop's top menu: **File → Add local repository**.
4. Click **Choose…**, navigate to **`C:\Users\henry\reselling`**, select it, click
   **Add repository**. (It recognises the package Claude made — no errors expected.)
5. A blue button **"Publish repository"** appears (top right). Click it.
6. In the box that pops up:
   - **Name:** change it to `offerpilot`
   - **Keep "Keep this code private" TICKED** ✅
   - Click **Publish repository**.
7. Wait a few seconds. Your code is now on GitHub. ✅

---

## STEP 2 — Deploy on Streamlit Community Cloud (free)

1. Go to **https://share.streamlit.io** → **Sign in** → choose **Continue with GitHub**
   (use the account from Step 1). Approve the access it asks for.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `your-username/offerpilot`
   - **Branch:** `main`
   - **Main file path:** `jobtracker/dashboard.py`
4. Click **Advanced settings** → in the **Secrets** box, paste this (fill in your real
   values):
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-your-key"
   ADMIN_EMAIL = "shek_henry@outlook.com"
   ADMIN_PASSWORD = "your-admin-password"
   ```
5. Click **Deploy**. Wait 5–10 minutes the first time (it's installing LibreOffice
   for PDFs — be patient).
6. You'll get a permanent link like **`https://offerpilot.streamlit.app`**.
   Open it → log in with your admin email/password → tailor CVs. **No localhost ever again.**

---

## STEP 3 — Point your website's buttons at the live app

1. Open `website/index.html` (the `APP_URL` line near the bottom, in the `<script>`).
2. Change:
   ```js
   const APP_URL = "http://localhost:8501";
   ```
   to your Streamlit link:
   ```js
   const APP_URL = "https://offerpilot.streamlit.app";
   ```
3. Re-upload `website/index.html` to Netlify (drag the `website` folder onto
   app.netlify.com/drop again, or it auto-updates if you connected the repo).

Now your Netlify website's **“Start free”** opens your live tool. Done — fully online.

---

## Good to know (honest notes)

- **PDF export** needs LibreOffice, which Streamlit's free tier installs from
  `packages.txt`. It can be slow; if PDFs ever fail, the app still gives you the
  **Word (.docx)** download, and you can “Save as PDF” from Word/Google Docs.
- **The app sleeps** after a while with no visitors on the free tier — the first
  visit after a nap takes ~30s to wake. Normal for free hosting.
- **Your data:** the free tier’s disk resets on redeploy, so the *application
  tracker* and other users’ signups can reset. Your **admin login always works**
  (it’s recreated from your secrets each time). When you go commercial, we move the
  database to a permanent one (Supabase/Postgres) — a small, contained change.
- **The job-drop monitor** isn’t part of the hosted app (it’s a background loop) —
  run that one locally if you want phone alerts, or we set it up on your Oracle VM.

Stuck on any step? Send me a screenshot of where you are and I’ll tell you the exact next click.
