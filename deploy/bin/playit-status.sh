#!/bin/bash
# Playit status helper (JSON via stdout)
set -euo pipefail

MODE="${1:-status}"
CREDENTIALS_CLEARED="/opt/appliance/data/playit-credentials-cleared"
PLAYIT_SECRET="/opt/appliance/data/playit.toml"

read_secret() {
  if [[ -f "$CREDENTIALS_CLEARED" ]]; then
    return 1
  fi
  if [[ ! -f "$PLAYIT_SECRET" ]]; then
    return 1
  fi
  grep -E '^secret_key\s*=' "$PLAYIT_SECRET" | head -1 | sed -E 's/^secret_key\s*=\s*"([^"]+)".*/\1/'
}

case "$MODE" in
  installed)
    if command -v playit >/dev/null 2>&1; then
      echo "YES"
    else
      echo "NO"
    fi
    ;;
  secret)
    SECRET="$(read_secret || true)"
    if [[ -n "$SECRET" ]]; then
      echo "$SECRET"
      exit 0
    fi
    echo "NONE"
    ;;
  status)
    ACTIVE="false"
    if systemctl is-active --quiet playit 2>/dev/null; then
      ACTIVE="true"
    fi
    INSTALLED="false"
    if command -v playit >/dev/null 2>&1; then
      INSTALLED="true"
    fi
    SECRET="false"
    if SECRET_VAL="$(read_secret || true)" && [[ -n "$SECRET_VAL" ]]; then
      SECRET="true"
    fi
    printf '{"installed":%s,"active":%s,"authenticated":%s}\n' "$INSTALLED" "$ACTIVE" "$SECRET"
    ;;
  *)
    echo "UNKNOWN"
    exit 1
    ;;
esac
