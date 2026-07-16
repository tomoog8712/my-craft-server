#!/bin/bash
set -euo pipefail
/usr/bin/tailscale down 2>/dev/null || true
echo "OK"
