#!/bin/bash
# Append an entry to CHANGELOG.md [Unreleased] section.
# Usage: changelog-add.sh <category> "description"
# Categories: added|changed|deprecated|removed|fixed|security
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHANGELOG="$ROOT/CHANGELOG.md"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <added|changed|deprecated|removed|fixed|security> \"description\"" >&2
  exit 1
fi

CATEGORY="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
shift
MSG="$*"

case "$CATEGORY" in
  added)      HEADING="Added" ;;
  changed)    HEADING="Changed" ;;
  deprecated) HEADING="Deprecated" ;;
  removed)    HEADING="Removed" ;;
  fixed)      HEADING="Fixed" ;;
  security)   HEADING="Security" ;;
  *)
    echo "Unknown category: $CATEGORY" >&2
    exit 1
    ;;
esac

if [[ ! -f "$CHANGELOG" ]]; then
  echo "CHANGELOG.md not found: $CHANGELOG" >&2
  exit 1
fi

TMP="$(mktemp)"
awk -v heading="$HEADING" -v line="- $MSG" '
  /^## \[Unreleased\]/ { in_unreleased=1 }
  in_unreleased && $0 == "### " heading {
    print
    print line
    inserted=1
    next
  }
  { print }
  END {
    if (!inserted) {
      print "Failed: could not find ### " heading " under [Unreleased]" > "/dev/stderr"
      exit 1
    }
  }
' "$CHANGELOG" > "$TMP"

mv "$TMP" "$CHANGELOG"
echo "Added to CHANGELOG [$HEADING]: $MSG"
