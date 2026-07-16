#!/bin/bash
# Safely install permissions.json, allowlist.json, or whitelist.json
set -euo pipefail

KIND="${1:-}"
SRC="${2:-}"
MINECRAFT_DIR="/opt/minecraft"

if [ -z "$KIND" ] || [ -z "$SRC" ]; then
  echo "usage: bedrock-json-write.sh <permissions|allowlist|whitelist> <json_file>" >&2
  exit 1
fi

if [ ! -f "$SRC" ]; then
  echo "source file missing: $SRC" >&2
  exit 1
fi

case "$KIND" in
  permissions) TARGET="$MINECRAFT_DIR/permissions.json" ;;
  allowlist) TARGET="$MINECRAFT_DIR/allowlist.json" ;;
  whitelist) TARGET="$MINECRAFT_DIR/whitelist.json" ;;
  *)
    echo "invalid kind: $KIND" >&2
    exit 1
    ;;
esac

TMP="${TARGET}.tmp.$$"
install -m 664 -o minecraft -g minecraft "$SRC" "$TMP"
mv -f "$TMP" "$TARGET"
echo "OK"
