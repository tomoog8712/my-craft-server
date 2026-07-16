#!/bin/bash
# Apply next shipment serial (privileged).
set -euo pipefail

SERIAL="${1:-}"
if [[ ! "$SERIAL" =~ ^(MCS|JRT)-[0-9]{6}$ ]]; then
    echo "ERROR: Invalid serial format: ${SERIAL}" >&2
    exit 1
fi

APPLIANCE_DIR="/etc/appliance"

chmod 644 "${APPLIANCE_DIR}/serial" 2>/dev/null || true
echo "${SERIAL}" > "${APPLIANCE_DIR}/serial"
chmod 444 "${APPLIANCE_DIR}/serial"

rm -f "${APPLIANCE_DIR}/.provisioned" "${APPLIANCE_DIR}/config.json" "${APPLIANCE_DIR}/uuid"

if command -v systemd-machine-id-setup &>/dev/null; then
    systemd-machine-id-setup
fi

hostnamectl set-hostname my-craft-server 2>/dev/null || true

if [[ -f /opt/appliance/bin/provision.sh ]]; then
    /opt/appliance/bin/provision.sh || true
fi

echo "OK: ${SERIAL}"
