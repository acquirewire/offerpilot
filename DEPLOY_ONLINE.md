# Put OfferPilot online (no more localhost)

Goal: a permanent web link to your tool, usable from any device, no PowerShell.
This is a **one-time setup**. It's all done in your **web browser** — no commands.

You'll create two free accounts (GitHub + Streamlit) and connect them. Budget
~30 minutes the first time. After that, it just runs.

I've already prepared every file the host needs (`requirements.txt`, `packages.txt`,
`.gitignore`, secrets handling). You only do the clicking below.

---

## STEP 1 — Make a GitHub account & put the code there

GitHub is where your code lives so the host can read it.

1. Go to **https://github.com** → **Sign up** → make a free account.
2. Click the **+** (top-right) → **New repository**.
3. Name it `offerpilot`, keep it **Private**, click **Create repository**.
4. On the new repo page, click **“uploading an existing file”** (a link in the
   middle of the page).
5. Open your folder `C:\Users\henry\reselling` in File Explorer. Drag these into the
   browser upload box — **only these**:
   - the **`jobtracker`** folder
   - the **`website`** folder
   - the files **`requirements.txt`**, **`packages.txt`**, **`.gitignore`**, **`.streamlit`** (folder)
   ⚠️ **Do NOT upload** `.venv`, `.env`, or any `.db` files (they're your private data /
   too big — the `.gitignore` is set to skip them, but don't drag them in).
6. Click **Commit changes**. Your code is now on GitHub.

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
