#!/bin/zsh
# Reproduce the spawn-site count behind evidence/subprocess-timeouts-20261005/report.md.
# Run from the repository root (deeptutor@f07029cfc or later, read-only).
set -euo pipefail

echo "== grep 口径：全部 spawn 点（48 行命中，其中 1 行为 docstring）"
rg -n "subprocess\.(run|Popen|check_output|check_call|call|getoutput|getstatusoutput)\(|create_subprocess_(exec|shell)\(" deeptutor --type py

echo
echo "== AST 口径：真实调用点 + timeout/capture 标注"
python3 evidence/subprocess-timeouts-20261005/audit_subprocess_ast.py deeptutor

echo
echo "== 宽口径文件清单（含仅注释/配置引用的文件，用于排除说明核对）"
rg -l "subprocess|Popen|check_output|create_subprocess_exec|create_subprocess_shell" deeptutor --type py | sort
