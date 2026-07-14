#!/bin/bash
# Run after: gh auth login --hostname github.com --git-protocol ssh --web
set -euo pipefail

REPO_NAME="${1:-my-craft-server}"
WEB_DIR="/opt/appliance/web"

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh not authenticated. Run:"
  echo "  gh auth login --hostname github.com --git-protocol ssh --web"
  exit 1
fi

# Register SSH key with GitHub (idempotent)
if ! gh ssh-key list 2>/dev/null | grep -q "mcs-appliance"; then
  gh ssh-key add "$HOME/.ssh/id_ed25519_github.pub" -t "mcs-appliance-$(hostname)"
fi

cd "$WEB_DIR"

if gh repo view "tomoog8712/${REPO_NAME}" >/dev/null 2>&1; then
  echo "Repository already exists: tomoog8712/${REPO_NAME}"
else
  gh repo create "$REPO_NAME" --private --source=. --remote=origin --description "My Craft Server - Bedrock appliance web UI"
fi

git remote -v
git push -u origin main
echo "Done: https://github.com/tomoog8712/${REPO_NAME}"
