#!/usr/bin/env bash
# AGEN-856 mypy adoption inventory — read-only reproduction script.
# Runs from the repo worktree root. Never modifies product code or config:
# - mypy cache goes to the evidence raw dir (not the repo tree)
# - the config used is evidence/mypy-adoption-20261006/mypy-inventory.ini
#   (a copy of the pyproject [tool.mypy] baseline WITHOUT the module overrides,
#    used only to measure latent error volume per directory)
# - every mypy run is time-limited to 900s via run_limited.py (portable, no GNU timeout)
# - mypy is pinned to 1.13.0 = .pre-commit-config.yaml rev v1.13.0
#
# Runs:
#   A baseline        : inventory config (relaxed, no overrides, no stubs)
#   B firststep       : A + --check-untyped-defs --no-implicit-optional --warn-return-any --warn-no-return
#   C annotations     : A + --disallow-untyped-defs --disallow-incomplete-defs
#   D baseline+nso    : A + --no-strict-optional (mirrors gate arg)
#   E truegate-nostubs: repo pyproject config + hook args, NO stub deps
#   F hookenv         : repo pyproject config + hook args + stub deps (== real pre-commit env)
#   G hookenv+so      : F minus --no-strict-optional (cost of restoring strict optional)
#
# Usage: bash evidence/mypy-adoption-20261006/run_inventory.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EV="$ROOT/evidence/mypy-adoption-20261006"
RAW="$EV/raw"
CFG="$EV/mypy-inventory.ini"
LIMIT="$EV/run_limited.py"
MYPY="uvx --from mypy==1.13.0 mypy"
MYPY_STUBS="uvx --from mypy==1.13.0 --with types-PyYAML --with types-requests --with types-croniter mypy"
cd "$ROOT"

echo "== [1/9] file inventory (stdlib only) =="
python3 "$EV/inventory_files.py" > "$RAW/files_inventory.json"

echo "== [2/9] run A: adoption baseline (relaxed, no overrides, no stubs) =="
python3 "$LIMIT" 900 "$RAW/mypy_runA_baseline.txt" \
  $MYPY --config-file "$CFG" --cache-dir "$RAW/.mypy_cache_A" \
  deeptutor deeptutor_cli || true

echo "== [3/9] run B: baseline + first-step strict flags =="
python3 "$LIMIT" 900 "$RAW/mypy_runB_firststep.txt" \
  $MYPY --config-file "$CFG" --cache-dir "$RAW/.mypy_cache_B" \
  --check-untyped-defs --no-implicit-optional --warn-return-any --warn-no-return \
  deeptutor deeptutor_cli || true

echo "== [4/9] run C: baseline + annotation-coverage flags =="
python3 "$LIMIT" 900 "$RAW/mypy_runC_annotations.txt" \
  $MYPY --config-file "$CFG" --cache-dir "$RAW/.mypy_cache_C" \
  --disallow-untyped-defs --disallow-incomplete-defs \
  deeptutor deeptutor_cli || true

echo "== [5/9] run D: baseline + --no-strict-optional =="
python3 "$LIMIT" 900 "$RAW/mypy_runD_gate.txt" \
  $MYPY --config-file "$CFG" --cache-dir "$RAW/.mypy_cache_D" \
  --no-strict-optional --no-error-summary \
  deeptutor deeptutor_cli || true

echo "== [6/9] run E: repo pyproject config + hook args, no stub deps =="
python3 "$LIMIT" 900 "$RAW/mypy_runE_truegate.txt" \
  $MYPY --cache-dir "$RAW/.mypy_cache_E" \
  --no-strict-optional --no-error-summary \
  deeptutor deeptutor_cli || true

echo "== [7/9] run F: hook environment (pyproject + hook args + stub deps) =="
python3 "$LIMIT" 900 "$RAW/mypy_runF_hookenv.txt" \
  $MYPY_STUBS --cache-dir "$RAW/.mypy_cache_F" \
  --no-strict-optional --no-error-summary --ignore-missing-imports \
  deeptutor deeptutor_cli || true

echo "== [8/9] run G: hook env, --no-strict-optional removed =="
python3 "$LIMIT" 900 "$RAW/mypy_runG_nostrictsoff.txt" \
  $MYPY_STUBS --cache-dir "$RAW/.mypy_cache_G" \
  --no-error-summary --ignore-missing-imports \
  deeptutor deeptutor_cli || true

echo "== [9/9] aggregating (stdlib only) =="
python3 "$EV/aggregate.py"
echo "done: see $RAW and $EV/stats.json"
