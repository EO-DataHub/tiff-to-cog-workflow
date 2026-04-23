#!/usr/bin/env bash
set -euo pipefail

# Minimal COG in-place converter
# Usage: ./cogify.sh /path/to/folder

ROOT="${1:-}"
if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "Usage: $0 /path/to/folder" >&2
  exit 1
fi

TOTAL=$(find "$ROOT" -type f \( -iname '*.tif' -o -iname '*.tiff' \) | wc -l | tr -d ' ')
echo "Found $TOTAL GeoTIFF file(s) under: $ROOT"
echo "Profile: deflate | Resampling: average | Replace: true"
echo

i=0
while IFS= read -r -d '' f; do
    i=$((i+1))
    echo "[$i/$TOTAL] Checking: $f"

    # Parse rio cogeo validate output to check if file is valid
    # Some versions return 0 even with errors, so check output text instead
    set +e
    VALID_OUTPUT=$(rio cogeo validate "$f" 2>&1)
    set -e
    
    # Check if output explicitly says "is NOT a valid" - if so, it's invalid
    if echo "$VALID_OUTPUT" | grep -q "is NOT a valid cloud optimized GeoTIFF"; then
      # File is invalid, will be converted below
      :
    # Check if output says "is a valid" (without NOT)
    elif echo "$VALID_OUTPUT" | grep -q "is a valid cloud optimized GeoTIFF"; then
      echo "  ✅ Already a valid COG"
      continue
    else
      # If output doesn't match expected patterns, assume invalid to be safe
      :
    fi

    echo "  ➜ Not a COG — converting in place…"
    dir=$(dirname "$f")
    base=$(basename "$f")
    # Create temp file alongside original (portable fallback if --suffix not supported)
    tmp=$( (mktemp --suffix=".tif" "$dir/.${base}.XXXXXX" 2>/dev/null) || mktemp "$dir/.${base}.XXXXXX" )
    
    # Clean up temp file on exit or error
    cleanup() {
      rm -f -- "$tmp"
    }
    trap cleanup EXIT ERR

    # Attempt conversion, but handle CRS errors gracefully
    set +e
    CONVERT_OUTPUT=$(rio cogeo create "$f" "$tmp" \
      --cog-profile deflate \
      --overview-resampling average \
      --quiet 2>&1)
    CONVERT_EXIT=$?
    set -e

    if [[ $CONVERT_EXIT -ne 0 ]]; then
      # Check if error was due to missing/invalid CRS
      if echo "$CONVERT_OUTPUT" | grep -qi "CRS is invalid\|CRSError.*invalid\|crs.*invalid.*none"; then
        echo "  ⚠️  Skipping: File has no CRS (required for COG conversion)"
        cleanup
        trap - EXIT ERR
        continue
      else
        # Other error - show output and fail
        echo "$CONVERT_OUTPUT" >&2
        echo "  ❌ Conversion failed (exit code: $CONVERT_EXIT)" >&2
        cleanup
        trap - EXIT ERR
        exit 1
      fi
    fi

    mv -f -- "$tmp" "$f"
    trap - EXIT ERR  # Clear trap after successful move
    echo "  ✅ Converted in place"
done < <(find "$ROOT" -type f \( -iname '*.tif' -o -iname '*.tiff' \) -print0)

echo
echo "All done."
