#!/bin/bash
# Reproducible scan: naive datetime & UTC-mixing inventory (static, read-only)
# Usage: gen_findings.sh <worktree-root>   (rg confined to that root)
set -euo pipefail
REPO="$1"
OUT="$(cd "$(dirname "$0")" && pwd)"; REPO_RESOLVED="$REPO"
F="$OUT/findings_full.tsv"
: > "$F"
add() { # category, risk, pattern-file
  local cat="$1" risk="$2" pf="$3"
  (cd "$REPO" && rg -n --no-heading -g "*.py" -f "$pf" deeptutor || true) \
    | while IFS= read -r row; do printf '%s\t%s\t%s\n' "$cat" "$risk" "$row" >> "$F"; done
}
P1="$OUT/.p1"; P2="$OUT/.p2"; P3="$OUT/.p3"; P4="$OUT/.p4"
printf 'datetime\\.now\\(\\)' > "$P1"
printf 'datetime\\.utcnow\\(\\)' > "$P2"
printf 'datetime\\(\\s*[0-9]{4}[^)]*\\)' > "$P3"
printf 'fromtimestamp\\([^,)]*\\)' > "$P4"
add A-naive-construction HIGH "$P1"
add A-naive-construction HIGH "$P2"
add A-naive-construction REVIEW "$P3"
add A-naive-construction REVIEW "$P4"
printf 'replace\\(tzinfo=None\\)\\.isoformat' > "$P1"; add B-utc-mixing HIGH "$P1"
printf 'fromisoformat\\([^)]*\\.replace' > "$P2"; add B-utc-mixing REVIEW "$P2"
printf '%s' '(isoformat\(\)|strftime\("%Y[^"]*"\))' > "$P1"; add C-serialization-loses-tz MEDIUM "$P1"
printf 'datetime\\.now\\(\\)\\s*-|fromisoformat\\([^)]*\\)\\s*[<>]' > "$P1"; add D-cross-tz-comparison HIGH "$P1"
grep -v '/tests/' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
sort -u -o "$F" "$F"
echo "total: $(wc -l < "$F")"
awk -F'\t' '{print $1}' "$F" | sort | uniq -c
