#!/bin/bash
# Enable and start Playit agent after authentication
set -euo pipefail

if ! command -v playit >/dev/null 2>&1; then
  echo "NOT_INSTALLED"
  exit 2
fi

if [[ ! -f /opt/appliance/data/playit.toml ]]; then
  # During claim, daemon may run before secret file exists.
  /opt/appliance/bin/playit-start-agent.sh
  echo "OK"
  exit 0
fi

systemctl daemon-reload
systemctl enable playit
systemctl restart playit
echo "OK"
