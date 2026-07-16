#!/bin/bash
# Install Playit.gg agent on Ubuntu (official packages)
set -euo pipefail

if command -v playit >/dev/null 2>&1; then
  echo "ALREADY"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
curl -fsSL https://packages.playit.gg/install.sh | bash -s -- -y

if ! command -v playit >/dev/null 2>&1; then
  echo "INSTALL_FAILED"
  exit 1
fi

install -d -m 0755 /opt/appliance/data
install -d -m 0755 /opt/playit
mkdir -p /var/log/playit 2>/dev/null || true

systemctl daemon-reload
echo "OK"
