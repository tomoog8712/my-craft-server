#!/bin/bash
# Create annotated git tag and push to trigger GitHub Release workflow.
# Usage: release.sh [version]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh not authenticated" >&2
  exit 1
fi

VERSION="${1:-$(tr -d '[:space:]' < VERSION)}"
TAG="v${VERSION#v}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: uncommitted changes. Commit before release." >&2
  git status --short
  exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "ERROR: tag $TAG already exists" >&2
  exit 1
fi

NOTES="$("$ROOT/scripts/extract-changelog.sh" "$VERSION")"
if [[ -z "$NOTES" ]]; then
  echo "WARNING: empty changelog section for $VERSION" >&2
fi

git tag -a "$TAG" -m "Release $TAG"
git push origin main
git push origin "$TAG"

echo "Pushed tag $TAG — GitHub Actions will create the Release."
echo "https://github.com/tomoog8712/my-craft-server/releases/tag/$TAG"
