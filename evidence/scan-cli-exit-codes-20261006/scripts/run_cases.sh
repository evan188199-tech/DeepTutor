#!/usr/bin/env bash
# Dynamic exit-code / stream-division verification for deeptutor_cli.
# Read-only commands only; sandboxed CWD + DEEPTUTOR_HOME; no server, no network.
set -u
WT="/Users/Shared/DeepTutor/dt-agen897-exitcodes-wt"
PY="/Users/Shared/DeepTutor/.venv/bin/python"
export DEEPTUTOR_HOME="$PWD/home"
export PYTHONPATH="$WT"
export NO_COLOR=1
OUT="$PWD/results"
mkdir -p "$OUT"

run_case() {
  local name="$1"; shift
  "$PY" -m deeptutor_cli "$@" >"$OUT/$name.out" 2>"$OUT/$name.err"
  local code=$?
  echo "$code" >"$OUT/$name.code"
  printf '%s\t%s\tout=%dB\terr=%dB\n' "$name" "$code" "$(wc -c <"$OUT/$name.out" | tr -d ' ')" "$(wc -c <"$OUT/$name.err" | tr -d ' ')"
}

run_case help --help
run_case noargs
run_case bogus_cmd bogus-cmd
run_case kb_bare kb
run_case kb_bogus_sub kb bogus-sub
run_case kb_list_json kb list --format json
run_case memory_show_bogus memory show bogus
run_case plugin_info_bogus plugin info bogus
run_case provider_login_bogus provider login bogus
run_case doctor_fmt_bogus doctor --format bogus
run_case chat_bad_config_json chat --config-json "{bad"
run_case run_bad_config_json run chat hi --config-json "{bad"
run_case session_show_bogus session show bogus-session-id
run_case doctor_json doctor --format json
