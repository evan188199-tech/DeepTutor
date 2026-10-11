#!/usr/bin/env bash
# AGEN-1583 复扫命令 — 在仓库根目录执行（web/node_modules 可用，或先 cd web && npm ci）。
# 基线 commit：origin/main @ 6cf793bd8 (release v1.6.14)
set -euo pipefail
cd "$(dirname "$0")/../../.."   # -> repo root
cd web

echo "== 1) repo 自带审计：缺失 key + 硬编码启发式 =="
node scripts/i18n_audit.mjs --show-missing --show-all

echo
echo "== 2) repo 自带 en<->zh parity =="
node scripts/i18n_parity.mjs

echo
echo "== 3) 本卡扫描器：三清单 JSON（含孤儿 raw-guard 与 fr 目录缺口）=="
node ../evidence/scan-web-locale-keys/evidence-scan.mjs --json-out /tmp/scan-web-locale-keys-out

echo
echo "== 4) 动态 t() 同文件字面量 map 核查 =="
node ../evidence/scan-web-locale-keys/dynamic-literals.mjs /tmp/scan-web-locale-keys-out/dynamic-literals.json
