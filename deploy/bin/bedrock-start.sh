#!/bin/bash
# My Craft Server - Bedrock wrapper with console FIFO
set -euo pipefail
cd /opt/minecraft
FIFO="/opt/minecraft/console.fifo"
rm -f "$FIFO"
mkfifo "$FIFO"
chmod 660 "$FIFO"
chown minecraft:minecraft "$FIFO"
# Open read-write so the read end does not block waiting for a writer.
exec 3<>"$FIFO"
exec /opt/minecraft/bedrock_server <&3
