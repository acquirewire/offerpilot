#!/usr/bin/env bash
# One-command deploy for the job tracker on a Linux VM (e.g. your Oracle box).
#
# Installs three systemd services that auto-start on boot and auto-restart on
# crash:
#   jobtracker-monitor    the Drop Tracker poll loop
#   jobtracker-dashboard  the Streamlit UI on localhost:8501 (password-gated)
#   jobtracker-tunnel     a Cloudflare tunnel exposing the UI over https
#
# Run from the repo root:   bash jobtracker/deploy/install.sh
set -euo pipefail

# --- locate things -----------------------------------------------------------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="$REPO/.venv/bin/python"
RUN_USER="$(whoami)"
PORT="${JOBTRACKER_PORT:-8501}"

echo "repo:   $REPO"
echo "python: $PYTHON"
echo "user:   $RUN_USER"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: no venv at $PYTHON"
  echo "Create it first:  python3 -m venv .venv && .venv/bin/pip install -r jobtracker/requirements.txt"
  exit 1
fi
if [[ ! -f "$REPO/jobtracker/config.yaml" ]]; then
  echo "ERROR: jobtracker/config.yaml missing — copy config.example.yaml and edit it first."
  exit 1
fi

# --- install cloudflared if missing (arch-aware) -----------------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "installing cloudflared..."
  case "$(uname -m)" in
    x86_64)  CF_ARCH=amd64 ;;
    aarch64) CF_ARCH=arm64 ;;   # Oracle Ampere free tier is arm64
    *) echo "unknown arch $(uname -m); install cloudflared manually"; exit 1 ;;
  esac
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" -o /tmp/cloudflared
  chmod +x /tmp/cloudflared
  sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
fi
CLOUDFLARED="$(command -v cloudflared)"

# --- write the unit files ----------------------------------------------------
write_unit() {  # $1=name  $2=description  $3=ExecStart
  sudo tee "/etc/systemd/system/$1.service" >/dev/null <<EOF
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO
EnvironmentFile=-$REPO/.env
ExecStart=$3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

write_unit jobtracker-monitor "Job Drop Tracker monitor" \
  "$PYTHON -m jobtracker poll --config $REPO/jobtracker/config.yaml"

write_unit jobtracker-dashboard "Job Tracker dashboard (Streamlit)" \
  "$PYTHON -m streamlit run $REPO/jobtracker/dashboard.py --server.headless true --server.port $PORT --server.address 127.0.0.1"

write_unit jobtracker-tunnel "Cloudflare tunnel for the dashboard" \
  "$CLOUDFLARED tunnel --url http://localhost:$PORT"

# --- enable + (re)start ------------------------------------------------------
sudo systemctl daemon-reload
for svc in jobtracker-monitor jobtracker-dashboard jobtracker-tunnel; do
  sudo systemctl enable "$svc" >/dev/null
  sudo systemctl restart "$svc"
done

echo
echo "=== installed & started. status: ==="
systemctl --no-pager --lines=0 status jobtracker-monitor jobtracker-dashboard jobtracker-tunnel || true
echo
echo "Your dashboard URL (Cloudflare prints it in the tunnel log):"
echo "  sudo journalctl -u jobtracker-tunnel | grep -o 'https://.*trycloudflare.com' | tail -1"
echo
echo "NOTE: the free quick-tunnel URL changes each restart. For a permanent URL,"
echo "set up a named Cloudflare tunnel (see DEPLOY.md)."
