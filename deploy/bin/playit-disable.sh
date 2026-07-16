#!/bin/bash
# Stop Playit agent (keep credentials)
set -euo pipefail

PIDFILE="/run/playit/claim-exchange.pid"
if [[ -f "$PIDFILE" ]]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]]; then
    kill "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE" /run/playit/claim-exchange.code
fi

if systemctl list-unit-files playit.service >/dev/null 2>&1; then
  systemctl stop playit || true
  systemctl disable playit || true
fi
echo "OK"
