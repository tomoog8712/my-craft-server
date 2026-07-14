#!/bin/bash
# Bump VERSION and finalize CHANGELOG [Unreleased] section.
# Usage: bump-version.sh <patch|minor|major>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$ROOT/VERSION"
CHANGELOG="$ROOT/CHANGELOG.md"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <patch|minor|major>" >&2
  exit 1
fi

BUMP="$1"
CURRENT="$(tr -d '[:space:]' < "$VERSION_FILE")"

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
case "$BUMP" in
  patch) PATCH=$((PATCH + 1)) ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  *)
    echo "Unknown bump type: $BUMP" >&2
    exit 1
    ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
DATE="$(date +%Y-%m-%d)"

TMP="$(mktemp)"
awk -v new_ver="$NEW_VERSION" -v date="$DATE" '
  /^## \[Unreleased\]/ {
    print "## [" new_ver "] - " date
    in_unreleased=1
    next
  }
  in_unreleased && /^---$/ {
    in_unreleased=0
    print
    print ""
    print "## [Unreleased]"
    print ""
    print "### Added"
    print ""
    print "### Changed"
    print ""
    print "### Fixed"
    print ""
    print "### Removed"
    print ""
    print "---"
    next
  }
  in_unreleased && /^### (Added|Changed|Deprecated|Removed|Fixed|Security)$/ {
    heading=$0
    getline
    if ($0 ~ /^- /) {
      print heading
      print $0
      while ((getline) > 0 && $0 ~ /^- /) print
      if ($0 !~ /^- / && length($0) > 0) print $0
    }
    next
  }
  in_unreleased && /^### / { next }
  in_unreleased && /^- / { next }
  { print }
' "$CHANGELOG" > "$TMP"

# Update footer links
python3 - "$TMP" "$NEW_VERSION" "$CURRENT" <<'PY'
import re, sys
path, new_ver, old_ver = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
repo = "https://github.com/tomoog8712/my-craft-server"
text = re.sub(r"\[Unreleased\]: [^\n]+", f"[Unreleased]: {repo}/compare/v{new_ver}...HEAD", text)
if f"[{old_ver}]:" not in text:
    text = text.rstrip() + f"\n[{new_ver}]: {repo}/releases/tag/v{new_ver}\n"
else:
    text = re.sub(rf"\[{re.escape(old_ver)}\]: [^\n]+", f"[{new_ver}]: {repo}/releases/tag/v{new_ver}", text)
open(path, "w", encoding="utf-8").write(text)
PY

mv "$TMP" "$CHANGELOG"
echo "$NEW_VERSION" > "$VERSION_FILE"

echo "Bumped version: $CURRENT -> $NEW_VERSION"
echo "Updated CHANGELOG.md and VERSION"
