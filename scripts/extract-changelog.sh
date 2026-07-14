#!/bin/bash
# Extract changelog section for a version (stdout).
# Usage: extract-changelog.sh 1.0.0
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHANGELOG="$ROOT/CHANGELOG.md"
VERSION="${1:-}"

if [[ -z "$VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
fi

VERSION="${VERSION#v}"

awk -v ver="$VERSION" '
  $0 ~ "^## \\[" ver "\\]" { found=1; next }
  found && /^## \[/ { exit }
  found { print }
' "$CHANGELOG"
