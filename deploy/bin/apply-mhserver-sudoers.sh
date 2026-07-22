#!/usr/bin/env bash
# Apply mhserver passwordless sudo rules (required for add-on deploy, players, etc.)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/mhserver-bedrock"
DEST="/etc/sudoers.d/mhserver-bedrock"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "root 権限が必要です: sudo bash $0" >&2
  exit 1
fi

install -m 0440 "$SRC" "$DEST"
visudo -c -f "$DEST"
echo "OK: $DEST を更新しました"
