# Deploying the job tracker on your Oracle VM

Runs the monitor + dashboard + public URL as auto-restarting services, sharing
one `jobtracker.db`. Same machine as your ticket bot.

## One-time setup on the VM

```bash
# 1. get the code onto the VM (scp, git, or rsync the whole repo), then:
cd ~/reselling                       # wherever you put the repo

# 2. create a venv and install deps
python3 -m venv .venv
.venv/bin/pip install -r jobtracker/requirements.txt

# 3. bring your config + secrets across
#    - jobtracker/config.yaml   (your 40 firms + filter)
#    - .env                     (NTFY_TOPIC, SMTP_*, ANTHROPIC_API_KEY)

# 4. set a dashboard password (REQUIRED before exposing it online)
echo "DASHBOARD_PASSWORD=pick-a-strong-password" >> .env

# 5. install + start everything
bash jobtracker/deploy/install.sh
```

That's it. The installer creates and starts three services and installs
`cloudflared` if needed (handles arm64 — Oracle's free tier — automatically).

## Get your dashboard URL

The free Cloudflare quick-tunnel prints a `https://….trycloudflare.com` link:

```bash
sudo journalctl -u jobtracker-tunnel | grep -o 'https://.*trycloudflare.com' | tail -1
```

Open it on any device, enter your password, done.

## Day-to-day

```bash
# see status / logs
systemctl status jobtracker-monitor jobtracker-dashboard jobtracker-tunnel
sudo journalctl -u jobtracker-monitor -f          # follow monitor activity

# after editing config.yaml or pulling new code
sudo systemctl restart jobtracker-monitor jobtracker-dashboard

# stop everything
sudo systemctl stop jobtracker-monitor jobtracker-dashboard jobtracker-tunnel
```

All three auto-start on reboot and auto-restart on crash.

## Optional: a permanent URL (named tunnel)

The quick-tunnel URL changes every restart. For a fixed URL you need a free
Cloudflare account + a domain on it:

```bash
cloudflared tunnel login
cloudflared tunnel create jobtracker
cloudflared tunnel route dns jobtracker jobs.yourdomain.com
```

Then point the `jobtracker-tunnel` service at the named tunnel instead of the
`--url` quick tunnel (edit `/etc/systemd/system/jobtracker-tunnel.service`,
`ExecStart=cloudflared tunnel run jobtracker`, then
`sudo systemctl daemon-reload && sudo systemctl restart jobtracker-tunnel`).
Now `jobs.yourdomain.com` always works. You can also add Cloudflare Access in
front for an email-login layer on top of the password.
