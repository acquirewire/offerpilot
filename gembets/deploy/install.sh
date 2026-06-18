#!/usr/bin/env bash
# One-command deploy for gembets on a Linux VM (Oracle Cloud Ubuntu, arm64 or x86).
# Installs a systemd service that runs the monitor 24/7 and auto-restarts on crash
# or reboot — so you never need a terminal open.
#
# Run ON THE VM, from the repo root:   bash gembets/deploy/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO/.venv"
PYTHON="$VENV/bin/python"
RUN_USER="$(whoami)"

echo "repo:   $REPO"
echo "user:   $RUN_USER"

# --- venv + dependencies (httpx, PyYAML) ------------------------------------
if [[ ! -x "$PYTHON" ]]; then
  echo "creating venv at $VENV"
  python3 -m venv "$VENV"
fi
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r "$REPO/gembets/requirements.txt"

# --- sanity checks ----------------------------------------------------------
if [[ ! -f "$REPO/gembets/config.yaml" ]]; then
  echo "ERROR: $REPO/gembets/config.yaml missing — copy gembets/config.example.yaml and edit it."
  exit 1
fi
if [[ ! -f "$REPO/.env" ]] || ! grep -q '^ODDS_API_KEY=..*' "$REPO/.env" 2>/dev/null; then
  echo "WARNING: ODDS_API_KEY not found in $REPO/.env — the monitor needs it for live odds."
fi
"$PYTHON" -c "import gembets.monitor" || { echo "ERROR: gembets failed to import"; exit 1; }

# --- write + start the service ----------------------------------------------
sudo tee /etc/systemd/system/gembets.service >/dev/null <<EOF
[Unit]
Description=gembets football value-bet monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO
EnvironmentFile=-$REPO/.env
ExecStart=$PYTHON -m gembets monitor --config $REPO/gembets/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gembets >/dev/null
sudo systemctl restart gembets

echo
echo "=== installed & started ==="
systemctl --no-pager --lines=0 status gembets || true
echo
echo "Watch it run:   journalctl -u gembets -f"
echo "Stop / start:   sudo systemctl stop gembets   |   sudo systemctl start gembets"
echo "After a code update:  git pull && sudo systemctl restart gembets"
echo "CLV + P&L:      $PYTHON -m gembets report --config $REPO/gembets/config.yaml"
