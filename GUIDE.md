# OfferPilot — Your Step-by-Step Guide (click by click)

For using your job tool this recruiting cycle. Nothing assumed — every step spelled out.

---

## PART 0 — Open the right window (do this every time)

You type commands into a window called **PowerShell**. Open it *inside* your project
folder so commands just work:

1. Press the **Windows key + E** to open File Explorer.
2. In the bar at the top, delete what's there, type this, and press **Enter**:
   ```
   C:\Users\henry\reselling
   ```
3. Now click that **same top bar again**, delete it, type **`powershell`**, press **Enter**.
4. A dark blue/black window opens, already in the right folder. **This is PowerShell.**
   You'll paste commands here. (To paste: right-click, or Ctrl+V. Then press Enter to run.)

---

## PART 1 — One-time setup (do this ONCE, ~15 minutes)

Do these in order. After each, **wait until it finishes** (the cursor returns and you can
type again) before doing the next.

### Step 1.1 — Install the tools
Paste this, press Enter, wait (can take a few minutes):
```powershell
.venv\Scripts\python.exe -m pip install -r jobtracker\requirements.txt
```
**You'll see:** lots of text scrolling, ending with `Successfully installed …` or
`Requirement already satisfied`. Both are fine.

Then paste this, press Enter, wait:
```powershell
.venv\Scripts\python.exe -m playwright install chromium
```
**You'll see:** a download finishing, or "is already installed". Fine either way.

### Step 1.2 — Make yourself the owner (unlimited free access)
Paste this **first** line exactly, press Enter:
```powershell
Add-Content -Path .env -Value "ADMIN_EMAIL=shek_henry@outlook.com"
```
Now the second line — **change `MyPassword123` to a password you'll remember** (keep the
quotes, no spaces), then press Enter:
```powershell
Add-Content -Path .env -Value "ADMIN_PASSWORD=MyPassword123"
```
**You'll see:** nothing happens, the cursor just returns. That's correct — it quietly
saved both lines. ⚠️ Write your password down somewhere.

### Step 1.3 — Set up the database
Paste, press Enter:
```powershell
.venv\Scripts\python.exe -m jobtracker init-db
```
**You'll see:** `initialized jobtracker.db`. ✅ Setup is done forever.

---

## PART 2 — Tailor your CV for a job (you'll do this for every application)

### Step 2.1 — Start the app
Paste, press Enter:
```powershell
.venv\Scripts\python.exe -m streamlit run jobtracker\dashboard.py
```
**You'll see:** a few lines appear, then your **web browser opens automatically** to a
page with a paper-plane logo and **"OfferPilot"**.
> If the browser doesn't open on its own: look in PowerShell for a line like
> `Local URL: http://localhost:8501`. Copy that address into your browser.

⚠️ **Leave the PowerShell window open** the whole time you use the app. Closing it stops the app.

### Step 2.2 — Make your account (first time only)
1. On the OfferPilot page, click the **"Create account"** tab.
2. In **Email**, type the same admin email from Step 1.2: `shek_henry@outlook.com`
3. In **Password**, type the same password from Step 1.2.
4. Click the **"Create free account"** button.

You're now logged in. (Next time, you'll use the **"Log in"** tab instead with the same
details.) Because it's your admin email, you have **everything unlocked, free.**

### Step 2.3 — Go to the tailoring screen
At the top you'll see tabs: **📋 Pipeline · 🔔 Open Drops · ➕ Log Application · ✍️ Tailor CV · 🛠️ Admin**.

Click **✍️ Tailor CV**.

### Step 2.4 — Fill it in
1. Click **"Browse files"** (under "Master CV") and choose your Word CV:
   go to **OneDrive → Documents → `updated cv.docx`**, and open it.
   *(It must be the Word `.docx` file, NOT a PDF.)*
2. A list appears: **"Which bullets should Claude rewrite?"** Your achievement bullets are
   already ticked; your grades/skills are left unticked. Leave it as-is, or untick any you
   don't want changed. *(Tip: ticking fewer bullets = each one keeps more detail.)*
3. Click in the big **"Job description"** box and **paste the full job advert** (copy it from
   the company's job page, Ctrl+C, then Ctrl+V into the box).
4. In **"Your full name"**, type: `Henry Shek`
5. In **"Firm"**, type the company name, e.g.: `Citi`
6. Click the purple **"✨ Tailor my CV + write cover letter"** button.

### Step 2.5 — Wait
A spinning message says it's tailoring. **This takes about 2–3 minutes.** Don't close
anything — just wait.

### Step 2.6 — Get your documents
When it finishes you'll see:
- A green **"Done — …% fit"** line.
- **"⬇ Download CV (PDF)"** and **"⬇ Download cover letter (PDF)"** buttons — **click them
  to save your tailored documents.** They'll go to your Downloads folder, named like
  `Henry_Shek_Citi.pdf`.
- A **"📊 ATS & fit"** section showing which job requirements you cover (green) and miss (red).

**Optional buttons further down:**
- **💡 Get AI improvement tips** — advice on how to improve, like a recruiter.
- **⚡ Apply these improvements** — auto-rewrites your bullets to act on that advice (~1 min).
  *(If it makes the fit worse, an **"↩ Undo last improvement"** button appears — click it to go back.)*
- **✏️ Edit bullets & rebuild** — change any wording yourself, then **"🔁 Rebuild CV with my
  edits"** to regenerate instantly (no waiting).

### Step 2.7 — Do the next job, or close
- **For another job:** scroll back up, upload the same CV, paste the new job advert, change
  the firm name, click Tailor again.
- **To finish:** click the **PowerShell** window, hold **Ctrl** and press **C**. The app stops.

---

## PART 3 — (Optional) Get alerts when new jobs open

This watches ~40 firms and pings your phone when a 2027 role drops. Skip if you'd rather
find jobs yourself.

1. On your **phone**, install the free app called **ntfy** (App Store / Play Store).
2. Open it → **Subscribe to topic** → type your topic name (it's in your `.env` file as
   `NTFY_TOPIC`).
3. On your PC, in PowerShell (Part 0), paste and press Enter:
   ```powershell
   .venv\Scripts\python.exe -m jobtracker poll --config jobtracker\config.yaml
   ```
4. Leave it running. The first few minutes are silent. After that, when a matching job
   appears, **your phone buzzes**. Press **Ctrl+C** in PowerShell to stop it.

---

## PART 4 — Track where you've applied

Inside the same app (Part 2):
- **➕ Log Application** tab → fill the form → it records a firm + role you applied to.
- **📋 Pipeline** tab → see all your applications as cards. Each has a button to move it to
  the next stage (Applied → OA → HireVue → Superday → Offer).
- It warns you if you've applied to too many roles at one firm.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `streamlit.exe … blocked by Application Control` | You used the wrong command. Use the one in Step 2.1 (`python.exe -m streamlit …`). |
| You changed something but the app looks the same | Click PowerShell, press **Ctrl+C**, then run the Step 2.1 command again. A browser refresh isn't enough. |
| `ModuleNotFoundError: jobtracker` | You're in the wrong folder. Redo **Part 0** to open PowerShell in `C:\Users\henry\reselling`. |
| "Wrong email or password" | Use the exact email + password from Step 1.2. |
| Tailored CV went onto 2 pages | Redo it but untick a few of your weaker bullets in Step 2.4.2. |

---

## Cheat sheet (once you're comfortable)

```powershell
# 1. open PowerShell in the folder (Part 0), then:

# start the app (tailor CVs, track applications)
.venv\Scripts\python.exe -m streamlit run jobtracker\dashboard.py

# watch for new job openings (optional)
.venv\Scripts\python.exe -m jobtracker poll --config jobtracker\config.yaml
```

**For this cycle:** do Part 1 once, then Part 2 for every application. Good luck.
