#!/bin/bash
# Start Playit agent daemon (works before authentication)
set -euo pipefail

if ! command -v playit >/dev/null 2>&1; then
  echo "NOT_INSTALLED"
  exit 2
fi

if systemctl is-active --quiet playit 2>/dev/null && [[ -S /run/playit/playitd.sock ]]; then
  echo "OK"
  exit 0
fi

# Remove broken symlink if package already provides the unit
if [[ -L /etc/systemd/system/playit.service ]]; then
  target="$(readlink -f /etc/systemd/system/playit.service 2>/dev/null || true)"
  if [[ "$target" == "$(readlink -f /usr/lib/systemd/system/playit.service 2>/dev/null || true)" ]]; then
    rm -f /etc/systemd/system/playit.service
  fi
fi

systemctl daemon-reload
systemctl enable playit
systemctl start playit

for _ in $(seq 1 20); do
  if [[ -S /run/playit/playitd.sock ]]; then
    echo "OK"
    exit 0
  fi
  sleep 0.5
done

if systemctl is-active --quiet playit; then
  echo "OK"
  exit 0
fi

echo "START_FAILED"
exit 1
