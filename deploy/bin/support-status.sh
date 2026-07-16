#!/bin/bash
set -euo pipefail
/usr/bin/tailscale status --json 2>/dev/null || echo '{"BackendState":"Stopped"}'
