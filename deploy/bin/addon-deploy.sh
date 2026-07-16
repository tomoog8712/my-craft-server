#!/bin/bash
# Deploy an add-on pack directory into the Minecraft server pack pool.
set -euo pipefail

SRC="${1:-}"
KIND="${2:-}"
NAME="${3:-}"

if [ -z "$SRC" ] || [ -z "$KIND" ] || [ -z "$NAME" ]; then
  echo "usage: addon-deploy.sh <src_dir> <behavior|resource> <folder_name>" >&2
  exit 1
fi

if [ ! -d "$SRC" ]; then
  echo "source missing: $SRC" >&2
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
mkdir -p "$(dirname "$DEST")"
cp -a "$SRC/." "$DEST/"
chown -R minecraft:minecraft "$DEST"
chmod -R u=rwX,g=rX,o= "$DEST"
echo "OK"
