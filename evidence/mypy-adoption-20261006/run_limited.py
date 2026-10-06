#!/usr/bin/env python3
"""AGEN-856 helper: run a command with a hard timeout, portable (no GNU timeout).

Usage: python3 run_limited.py <seconds> <logfile> <cmd> [args...]
Read-only wrt the repo: only writes the given logfile.
"""
import subprocess
import sys

seconds = int(sys.argv[1])
logfile = sys.argv[2]
cmd = sys.argv[3:]
try:
    with open(logfile, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=seconds)
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"\nTIMEOUT after {seconds}s\n")
    print(f"TIMEOUT after {seconds}s: {' '.join(cmd)}", file=sys.stderr)
    sys.exit(124)
