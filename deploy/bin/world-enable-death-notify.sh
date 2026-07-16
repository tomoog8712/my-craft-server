#!/bin/bash
# Attach MHServer death-notify behavior pack to a world folder.
set -euo pipefail

WORLD_DIR="${1:-}"
PACK_ID="c8f4a2b1-3d5e-4f6a-9b0c-1d2e3f4a5b6c"
PACK_FILE="world_behavior_packs.json"

if [ -z "$WORLD_DIR" ] || [ ! -d "$WORLD_DIR" ]; then
  echo "world directory missing: $WORLD_DIR" >&2
  exit 1
fi

TARGET="$WORLD_DIR/$PACK_FILE"
TMP="$(mktemp)"

python3 - "$TARGET" "$PACK_ID" "$TMP" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
pack_id = sys.argv[2]
out = Path(sys.argv[3])
version = [1, 0, 0]
entry = {"pack_id": pack_id, "version": version}

packs = []
if target.is_file():
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, list):
            packs = data
    except Exception:
        packs = []

if not any(p.get("pack_id") == pack_id for p in packs):
    packs.append(entry)

out.write_text(json.dumps(packs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

install -m 664 -o minecraft -g minecraft "$TMP" "$TARGET"
rm -f "$TMP"
