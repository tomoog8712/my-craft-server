#!/bin/bash
# Install world_behavior_packs.json or world_resource_packs.json for a world.
set -euo pipefail

WORLD_DIR="${1:-}"
KIND="${2:-}"
JSON_FILE="${3:-}"

if [ -z "$WORLD_DIR" ] || [ -z "$KIND" ] || [ -z "$JSON_FILE" ]; then
  echo "usage: addon-world-json.sh <world_dir> <behavior|resource> <json_file>" >&2
  exit 1
fi

if [ ! -d "$WORLD_DIR" ]; then
  echo "world directory missing: $WORLD_DIR" >&2
  exit 1
fi

if [ ! -f "$JSON_FILE" ]; then
  echo "json file missing: $JSON_FILE" >&2
  exit 1
fi

case "$KIND" in
  behavior) TARGET="$WORLD_DIR/world_behavior_packs.json" ;;
  resource) TARGET="$WORLD_DIR/world_resource_packs.json" ;;
  *)
    echo "invalid kind: $KIND" >&2
    exit 1
    ;;
esac

install -m 664 -o minecraft -g minecraft "$JSON_FILE" "$TARGET"
echo "OK"
