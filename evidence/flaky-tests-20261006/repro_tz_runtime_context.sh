#!/bin/sh
# Reproduces the timezone-sensitive failures in tests/agents/chat/test_runtime_context.py
# on a checkout that still freezes an AWARE FIXED_NOW (origin/main at scan time).
#
# Mechanics: the product renders the runtime-context date via
# `datetime.now().astimezone()` (deeptutor/agents/loop/prompt_blocks.py).
# The test freezes `datetime` with FIXED_NOW = 2026-08-17 12:00+08:00, so
# `.astimezone()` converts to the host zone. Hosts at UTC-9 or further west
# render 2026-08-16 and three date assertions fail.
#
# Pure standard-library tooling (sh + python -m pytest subprocess).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
TARGET="tests/agents/chat/test_runtime_context.py"
PYTHON=${PYTHON:-python3}

echo "repo: $REPO_ROOT"
echo "target: $TARGET"
status_overall=0
for tz in UTC America/New_York Pacific/Honolulu; do
  echo "--- TZ=$tz"
  TZ="$tz" "$PYTHON" -m pytest -q -p no:cacheprovider "$REPO_ROOT/$TARGET"
  rc=$?
  [ "$rc" -ne 0 ] && status_overall=1
done

echo "--- summary"
echo "exit codes above are per-TZ pytest results; overall=$status_overall"
echo "expected on affected revisions: UTC=pass, America/New_York=pass (frozen instant lands exactly on local midnight), Pacific/Honolulu=3 failures (date shifts to 2026-08-16)"
exit "$status_overall"
