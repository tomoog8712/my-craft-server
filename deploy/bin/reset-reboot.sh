#!/bin/bash
# Schedule system reboot after reset center factory reset
set -euo pipefail
/usr/sbin/shutdown -r +0.5 "My Craft Server factory reset"
echo "OK"
