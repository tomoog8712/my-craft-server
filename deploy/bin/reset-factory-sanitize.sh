#!/bin/bash
# Additional privileged cleanup for clone shipment reset.
set -euo pipefail

APPLIANCE_DIR="/etc/appliance"
DATA_DIR="/opt/appliance/data"

# Clear provisioning state that may bind the clone to the source unit.
rm -f "${APPLIANCE_DIR}/.provisioned" || true
rm -f "${APPLIANCE_DIR}/config.json" || true
rm -f "${APPLIANCE_DIR}/uuid" || true

# Remove stale Cloudflare credentials/state files if they exist.
rm -f "${APPLIANCE_DIR}/cloudflare.token" || true
rm -rf /etc/cloudflared || true
rm -f /etc/systemd/system/cloudflared.service /etc/systemd/system/multi-user.target.wants/cloudflared.service || true

# Ensure Playit temporary exchange artifacts are not carried over.
rm -f "${DATA_DIR}/playit-claim-exchange.code" "${DATA_DIR}/playit-claim-exchange.pid" || true
if [[ -f "${DATA_DIR}/playit-claim-exchange.log" ]]; then
  : > "${DATA_DIR}/playit-claim-exchange.log" || true
fi
rm -f /run/playit/claim-exchange.code /run/playit/claim-exchange.pid || true

# Force machine-id regeneration on next boot to avoid cloned identity collisions.
truncate -s 0 /etc/machine-id || true
rm -f /var/lib/dbus/machine-id || true
ln -s /etc/machine-id /var/lib/dbus/machine-id || true

systemctl daemon-reload || true

echo "OK"
