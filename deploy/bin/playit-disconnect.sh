#!/bin/bash
# Disconnect Playit agent and remove local credentials for a fresh setup
set -euo pipefail

CREDENTIALS_CLEARED="/opt/appliance/data/playit-credentials-cleared"
PLAYIT_SECRET="/opt/appliance/data/playit.toml"
install -d -m 0755 /opt/appliance/data

for PIDFILE in /opt/appliance/data/playit-claim-exchange.pid /run/playit/claim-exchange.pid; do
  if [[ -f "$PIDFILE" ]]; then
    OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$OLD_PID" ]]; then
      kill "$OLD_PID" 2>/dev/null || true
    fi
  fi
done

pkill -f "claim exchange" 2>/dev/null || true
rm -f /opt/appliance/data/playit-claim-exchange.pid /opt/appliance/data/playit-claim-exchange.code
rm -f /run/playit/claim-exchange.pid /run/playit/claim-exchange.code
rm -f "$PLAYIT_SECRET" 2>/dev/null || true
rm -f /etc/playit/playit.toml 2>/dev/null || true

if systemctl list-unit-files playit.service >/dev/null 2>&1; then
  systemctl stop playit || true
  systemctl disable playit || true
fi

touch "$CREDENTIALS_CLEARED"
chmod 0644 "$CREDENTIALS_CLEARED"

for LOGFILE in /opt/appliance/data/playit-claim-exchange.log /var/log/playit/claim-exchange.log; do
  if [[ -f "$LOGFILE" ]]; then
    : > "$LOGFILE" 2>/dev/null || true
  fi
done

echo "OK"
