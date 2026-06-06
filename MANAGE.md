# Managing your live bot

The bot runs 24/7 on your Oracle Cloud server. You don't need your PC on.

- **Server IP:** 145.241.192.135
- **Login user:** ubuntu
- **SSH key:** `C:\Users\henry\Downloads\ssh-key-2026-06-04 (1).key`
- **App folder on server:** `/home/ubuntu/ticket-monitor`
- **Alerts:** ntfy topic `ticketdrop-53cce25e001115b4` + email

## Log into the server (from PowerShell)

```powershell
ssh -i "C:\Users\henry\Downloads\ssh-key-2026-06-04 (1).key" ubuntu@145.241.192.135
```

## Useful commands (run once logged in)

```bash
# Is it running?
sudo systemctl status ticket-monitor

# Watch live logs (Ctrl+C to stop watching — does NOT stop the bot)
journalctl -u ticket-monitor -f

# Restart / stop / start
sudo systemctl restart ticket-monitor
sudo systemctl stop ticket-monitor
sudo systemctl start ticket-monitor
```

## Add or change which events it watches

```bash
nano /home/ubuntu/ticket-monitor/config.yaml   # edit the targets, Ctrl+O, Enter, Ctrl+X
sudo systemctl restart ticket-monitor           # apply the change
```

To copy a freshly edited local config up from your PC instead:

```powershell
scp -i "C:\Users\henry\Downloads\ssh-key-2026-06-04 (1).key" `
  config.yaml ubuntu@145.241.192.135:/home/ubuntu/ticket-monitor/config.yaml
ssh -i "C:\Users\henry\Downloads\ssh-key-2026-06-04 (1).key" `
  ubuntu@145.241.192.135 "sudo systemctl restart ticket-monitor"
```

## If alerts stop / something breaks

1. `journalctl -u ticket-monitor -n 50` — look for errors.
2. If Fatsoma changed their page layout, the parser selectors in
   `src/parsers/fatsoma.py` may need updating (see the comments in that file).
