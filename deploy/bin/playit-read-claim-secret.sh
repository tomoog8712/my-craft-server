#!/bin/bash
# Read approved claim secret from playit claim-exchange log
set -euo pipefail

CODE="${1:-}"

for LOGFILE in /var/log/playit/claim-exchange.log /opt/appliance/data/playit-claim-exchange.log; do
  if [[ ! -f "$LOGFILE" ]]; then
    continue
  fi
  SECRET="$(python3 - <<'PY' "$LOGFILE" "$CODE"
import re, sys
path, code = sys.argv[1], sys.argv[2]
try:
    text = open(path, encoding="utf-8", errors="replace").read()
except OSError:
    sys.exit(0)
if code:
    marker = f"claim/{code}"
    idx = text.rfind(marker)
    if idx < 0:
        sys.exit(0)
    text = text[idx:]
if "Program approved. Finishing setup" not in text:
    sys.exit(0)
matches = re.findall(r"(?m)^[0-9a-f]{64}$", text)
if matches:
    print(matches[-1])
PY
)"
  if [[ -n "$SECRET" ]]; then
    echo "$SECRET"
    exit 0
  fi
done

echo "NONE"
