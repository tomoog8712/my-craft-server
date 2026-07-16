#!/bin/bash
# Send a command to the Bedrock server console FIFO
set -euo pipefail
CMD="${1:-}"
FIFO="/opt/minecraft/console.fifo"
if [ -z "$CMD" ]; then
  echo "missing command" >&2
  exit 1
fi
if [ ! -p "$FIFO" ]; then
  echo "NOT_READY" >&2
  exit 2
fi
# Open FIFO for write; timeout prevents blocking the web UI if bedrock is not reading.
if ! timeout 3 sh -c 'exec 3>"$1"; printf "%s\n" "$2" >&3' sh "$FIFO" "$CMD"; then
  echo "TIMEOUT" >&2
  exit 3
fi
echo "OK"
