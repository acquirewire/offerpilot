# Deploy gembets to the Oracle Cloud VM (runs 24/7, no PowerShell)

Goal: the monitor runs as a **systemd service** on your Oracle VM — it survives
crashes and reboots, and alerts your phone whether or not your PC is on. Same box
and `.env` as your Fatsoma/jobtracker bots.

## One-time setup

### 1. Get the code onto the VM
SSH in (from PowerShell on your PC):
```powershell
ssh ubuntu@<your-vm-ip>
```
Then on the VM, get the repo. If it's **already there** (you deploy jobtracker from
it), just update it:
```bash
cd ~/reselling && git pull
```
If it's **not there yet**, clone it:
```bash
git clone https://github.com/acquirewire/offerpilot.git ~/reselling
```
> Push your latest gembets work from your PC first: `git add gembets && git commit -m "gembets" && git push`. (Secrets in `.env` are gitignored — they transfer separately in step 2.)

### 2. Put your secrets on the VM (not in git)
The monitor reads `~/reselling/.env` (ODDS_API_KEY, ntfy, SMTP). If that file isn't
on the VM yet, copy it from your PC (run in PowerShell, **not** the VM):
```powershell
scp C:\Users\henry\reselling\.env ubuntu@<your-vm-ip>:~/reselling/.env
```
The Betfair creds (in `boostmatcher/.env`) are only needed if you later enable
Detectors E/B — copy that too if so:
```powershell
scp C:\Users\henry\reselling\boostmatcher\.env ubuntu@<your-vm-ip>:~/reselling/boostmatcher/.env
```
Also copy your tuned config if it isn't in git:
```powershell
scp C:\Users\henry\reselling\gembets\config.yaml ubuntu@<your-vm-ip>:~/reselling/gembets/config.yaml
```

### 3. Install + start the service (on the VM)
```bash
cd ~/reselling
bash gembets/deploy/install.sh
```
That creates a venv, installs `httpx`/`PyYAML`, writes the systemd unit, and starts
it. You should see `active (running)`.

## Day-to-day

| Task | Command (on the VM) |
|---|---|
| Watch it live | `journalctl -u gembets -f` |
| Stop / start | `sudo systemctl stop gembets` / `start` |
| Restart after a code change | `git pull && sudo systemctl restart gembets` |
| CLV + P&L report | `.venv/bin/python -m gembets report --config gembets/config.yaml` |
| Settle a bet | `.venv/bin/python -m gembets settle --key <key> --result win` |

You can close the SSH window — the service keeps running. Alerts go to your phone
via ntfy exactly as before.

## Notes
- **Dependencies are tiny** (httpx + PyYAML); the maths core is pure stdlib.
- **The ledger** (`gembets_ledger.db`) lives in the repo root on the VM — that's
  where CLV/P&L accumulate. Back it up if you care about the history.
- **Updating:** push from your PC, `git pull` + `restart` on the VM. The service
  picks up the new code on restart.
- **Standalone:** gembets imports `boostmatcher` only if the oddschecker scrape
  fallback runs — for the default API + Betfair setup it isn't needed, but since
  you clone the whole repo it's present anyway.
