#!/bin/bash
# Save Playit secret key and enable service
set -euo pipefail

SECRET="${1:-}"
CREDENTIALS_CLEARED="/opt/appliance/data/playit-credentials-cleared"
PLAYIT_SECRET="/opt/appliance/data/playit.toml"

if [[ -z "$SECRET" ]]; then
  echo "MISSING_SECRET"
  exit 1
fi

install -d -m 0755 /opt/appliance/data
cat > "$PLAYIT_SECRET" <<EOF
secret_key = "${SECRET}"
EOF
chown playit:playit "$PLAYIT_SECRET" 2>/dev/null || true
chmod 0640 "$PLAYIT_SECRET" 2>/dev/null || true
rm -f /etc/playit/playit.toml 2>/dev/null || true

rm -f "$CREDENTIALS_CLEARED" 2>/dev/null || true

systemctl daemon-reload
systemctl enable playit >/dev/null 2>&1 || true
systemctl reset-failed playit 2>/dev/null || true
systemctl restart playit
echo "OK"
