#!/bin/bash
# Create a Minecraft Bedrock tunnel via Playit API
set -euo pipefail

LOCAL_IP="${1:-127.0.0.1}"
LOCAL_PORT="${2:-19132}"

PLAYIT_SECRET="/opt/appliance/data/playit.toml"

if [[ ! -f "$PLAYIT_SECRET" ]]; then
  echo "NOT_AUTHENTICATED"
  exit 2
fi

SECRET="$(grep -E '^secret_key\s*=' "$PLAYIT_SECRET" | head -1 | sed -E 's/^secret_key\s*=\s*"([^"]+)".*/\1/')"
if [[ -z "$SECRET" ]]; then
  echo "NOT_AUTHENTICATED"
  exit 2
fi

api_post() {
  local path="$1"
  local payload="$2"
  curl -fsS -m 20 -X POST "https://api.playit.gg${path}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Authorization: agent-key ${SECRET}" \
    -d "$payload"
}

RUNDATA="$(api_post "/agents/rundata" '{}' || true)"
AGENT_ID="$(python3 - <<'PY' "$RUNDATA"
import json, sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
if not raw:
    sys.exit(0)
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(0)
payload = data.get("data") or {}
print(payload.get("agent_id") or payload.get("id") or "")
PY
)"

if [[ -z "$AGENT_ID" ]]; then
  AGENT_ID="$(journalctl -u playit -n 40 --no-pager -o cat 2>/dev/null | grep -oE 'agent_id=[0-9a-f-]{36}' | tail -1 | cut -d= -f2 || true)"
fi

if [[ -z "$AGENT_ID" ]]; then
  echo "AGENT_NOT_READY"
  exit 3
fi

PAYLOAD="$(python3 - <<PY
import json
print(json.dumps({
    "name": "Minecraft Bedrock",
    "tunnel_type": "minecraft-bedrock",
    "port_type": "udp",
    "port_count": 1,
    "origin": {
        "type": "agent",
        "data": {
            "agent_id": "${AGENT_ID}",
            "local_ip": "${LOCAL_IP}",
            "local_port": ${LOCAL_PORT},
        },
    },
    "enabled": True,
}))
PY
)"

RETRY_DELAYS=(2 3 5 5 10 10 10)
attempt=0
last_err=""

while true; do
  if RESP="$(api_post "/tunnels/create" "$PAYLOAD" 2>&1)"; then
    echo "OK"
    exit 0
  else
    last_err="$RESP"
  fi

  if echo "$last_err" | grep -q "AgentVersionTooOld"; then
    if [[ $attempt -lt ${#RETRY_DELAYS[@]} ]]; then
      sleep "${RETRY_DELAYS[$attempt]}"
      attempt=$((attempt + 1))
      continue
    fi
    echo "AGENT_NOT_READY"
    exit 3
  fi

  if echo "$last_err" | grep -qiE 'already exists|duplicate|TunnelName'; then
    echo "ALREADY"
    exit 0
  fi

  echo "$last_err" | head -c 240
  exit 1
done
