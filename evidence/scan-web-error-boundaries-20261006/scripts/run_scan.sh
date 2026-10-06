#!/usr/bin/env bash
# Deterministic runner for the web error-presentation scan.
# Usage: bash run_scan.sh <repo-root> [out-dir]
# Writes the three JSON datasets into out-dir. Output is byte-stable:
# no timestamps, sorted walks, sorted JSON keys.
set -euo pipefail
REPO="${1:?usage: run_scan.sh <repo-root> [out-dir]}"
OUT="${2:-$(cd "$(dirname "$0")/.." && pwd)/datasets}"
mkdir -p "$OUT"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPTS/scan_error_boundaries.py" "$REPO" > "$OUT/boundaries.json"
python3 "$SCRIPTS/scan_failure_surfacing.py" "$REPO" > "$OUT/surfacing.json"
python3 "$SCRIPTS/scan_recovery_actions.py" "$REPO" > "$OUT/recovery.json"
