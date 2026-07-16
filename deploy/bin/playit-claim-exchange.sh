#!/bin/bash
# Run playit claim exchange in background (registers agent for browser claim)
set -euo pipefail

CODE="${1:-}"
PIDFILE="/opt/appliance/data/playit-claim-exchange.pid"
CODEFILE="/opt/appliance/data/playit-claim-exchange.code"
LOGFILE="/opt/appliance/data/playit-claim-exchange.log"

if [[ -z "$CODE" ]]; then
  echo "MISSING_CODE"
  exit 1
fi

install -d -m 0755 /opt/appliance/data
if install -d -m 0750 -o playit -g playit /var/log/playit 2>/dev/null; then
  LOGFILE="/var/log/playit/claim-exchange.log"
fi
touch "$LOGFILE" 2>/dev/null || true
chown playit:playit "$LOGFILE" 2>/dev/null || true
chmod 0640 "$LOGFILE" 2>/dev/null || true

if [[ -f "$CODEFILE" ]] && [[ "$(cat "$CODEFILE")" == "$CODE" ]]; then
  if pgrep -f "claim exchange ${CODE}" >/dev/null 2>&1; then
    pgrep -f "claim exchange ${CODE}" | head -1 > "$PIDFILE"
    echo "ALREADY"
    exit 0
  fi
fi

/opt/appliance/bin/playit-start-agent.sh >/dev/null

if [[ -f "$PIDFILE" ]]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
  fi
fi
pkill -f "claim exchange ${CODE}" 2>/dev/null || true
sleep 0.3

echo "$CODE" > "$CODEFILE"
chmod 0644 "$CODEFILE"

runuser -u playit -- /usr/bin/playit claim exchange "$CODE" --wait 0 >>"$LOGFILE" 2>&1 &
sleep 0.5
CLAIM_PID="$(pgrep -f "claim exchange ${CODE}" | head -1 || true)"
if [[ -z "$CLAIM_PID" ]]; then
  echo "CLAIM_START_FAILED"
  exit 1
fi
echo "$CLAIM_PID" > "$PIDFILE"
chmod 0644 "$PIDFILE"

if grep -q "Program approved. Finishing setup" "$LOGFILE" 2>/dev/null; then
  SECRET="$(grep -E '^[0-9a-f]{64}$' "$LOGFILE" | tail -1 || true)"
  if [[ -n "$SECRET" ]]; then
    /opt/appliance/bin/playit-save-secret.sh "$SECRET" >/dev/null || true
  fi
fi

echo "OK"
