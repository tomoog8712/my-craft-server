#!/bin/bash
# Write updated config.json - root only via sudo
set -euo pipefail
SRC="${1:-}"
DEST="/etc/appliance/config.json"
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "missing source file" >&2
  exit 1
fi
TMP="${DEST}.tmp.$$"
cp "$SRC" "$TMP"
mv -f "$TMP" "$DEST"
chmod 640 "$DEST"
chown root:appliance "$DEST"
