#!/bin/sh
# Re-run the isolation scan and verify the committed data files reproduce
# byte-for-byte (deterministic output). Run from the worktree root:
#   sh evidence/scan-test-isolation-20261006/scripts/verify_rerun.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
DATA="$HERE/../data"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

python3 "$HERE/scan_isolation.py" "$REPO" "$TMP" >/dev/null

fail=0
for f in findings.json coverage.json; do
    if cmp -s "$DATA/$f" "$TMP/$f"; then
        echo "MATCH  $f"
    else
        echo "DIFF   $f"
        fail=1
    fi
done
exit $fail
