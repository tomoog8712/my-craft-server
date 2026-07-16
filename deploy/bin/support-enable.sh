#!/bin/bash
# Enable Tailscale remote support (root only via sudo)
set -euo pipefail
AUTHKEY="/etc/appliance/tailscale.authkey"
if [[ ! -s "$AUTHKEY" ]]; then
  echo "AUTHKEY_MISSING"
  exit 2
fi
/usr/bin/tailscale up --auth-key="file:${AUTHKEY}" --ssh --accept-routes=false --reset
echo "OK"
