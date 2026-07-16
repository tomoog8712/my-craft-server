#!/bin/bash
# Run a privileged command outside mhserver-web mount namespace.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: priv-exec.sh <command> [args...]" >&2
    exit 1
fi

exec /usr/bin/systemd-run --wait --pipe --collect "$@"
