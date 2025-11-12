#!/usr/bin/env bash
set -euo pipefail

# Unzip all zip files in a directory and delete the zip files after extraction
# Usage: ./unzipify.sh /path/to/folder

ROOT="${1:-}"
if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "Usage: $0 /path/to/folder" >&2
  exit 1
fi

TOTAL=$(find "$ROOT" -maxdepth 1 -type f -iname '*.zip' | wc -l | tr -d ' ')
if [[ "$TOTAL" -eq 0 ]]; then
  echo "No zip files found in: $ROOT"
  exit 0
fi

echo "Found $TOTAL zip file(s) in: $ROOT"
echo

i=0
while IFS= read -r -d '' zipfile; do
    i=$((i+1))
    echo "[$i/$TOTAL] Extracting: $(basename "$zipfile")"
    
    # Extract zip file to the same directory
    if unzip -q -o "$zipfile" -d "$ROOT"; then
        # Only delete if extraction was successful
        rm -f -- "$zipfile"
        echo "  ✅ Extracted and removed zip file"
    else
        echo "  ❌ Failed to extract, keeping zip file" >&2
        exit 1
    fi
done < <(find "$ROOT" -maxdepth 1 -type f -iname '*.zip' -print0)

echo
echo "All done."

