#!/bin/bash
# Remove a deployed add-on pack from the Minecraft server pack pool.
set -euo pipefail

KIND="${1:-}"
NAME="${2:-}"

if [ -z "$KIND" ] || [ -z "$NAME" ]; then
  echo "usage: addon-remove.sh <behavior|resource> <folder_name>" >&2
  exit 1
fi

case "$KIND" in
  behavior) DEST="/opt/minecraft/behavior_packs/$NAME" ;;
  resource) DEST="/opt/minecraft/resource_packs/$NAME" ;;
  *)
    echo "invalid kind: $KIND" >&2
    exit 1
    ;;
esac

rm -rf "$DEST"
echo "OK"
