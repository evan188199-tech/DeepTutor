#!/usr/bin/env python3
"""Reproducible category scanner for time/timing/order-sensitive tests.

Pure standard library. Run from the repository root:

    python3 evidence/flaky-tests-20261006/scan_categories.py

Scans the backend test surface (``tests/`` plus in-package test trees
``deeptutor/learning/tests/`` and ``deeptutor/services/config/test_runner.py``)
and prints per-category match counts and ``path:line`` hits. The curated
risk assessment for each hit lives in report.md; this script only fixes the
detection methodology so numbers can be re-derived on any checkout.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_PATHS = [
    ROOT / "tests",
    ROOT / "deeptutor" / "learning" / "tests",
    ROOT / "deeptutor" / "services" / "config" / "test_runner.py",
]

CATEGORIES: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "A_blocking_sleep": [
        ("time.sleep(", re.compile(r"\btime\.sleep\(")),
    ],
    "B_async_pacing_nonzero": [
        ("asyncio.sleep(x>0)", re.compile(r"\basyncio\.sleep\(\s*(?!0+\s*\))(\d+(?:\.\d+)?)")),
    ],
    "C_wall_clock": [
        ("time.time(", re.compile(r"\btime\.time\(")),
        ("time.monotonic(", re.compile(r"\btime\.monotonic\(")),
        ("perf_counter", re.compile(r"\bperf_counter\b")),
    ],
    "D_datetime_now": [
        ("datetime.now(", re.compile(r"\bdatetime\.now\(")),
        ("utcnow(", re.compile(r"\.utcnow\(\)")),
        ("date.today(", re.compile(r"\bdate\.today\(")),
        ("datetime.today(", re.compile(r"\bdatetime\.today\(")),
        ("fromtimestamp(", re.compile(r"\bfromtimestamp\(")),
    ],
    "E_alarm_timer": [
        ("signal.alarm", re.compile(r"\bsignal\.alarm\b")),
        ("setitimer/SIGALRM", re.compile(r"\bsetitimer\b|\bSIGALRM\b")),
        ("threading.Timer", re.compile(r"\bthreading\.Timer\b")),
    ],
    "F_tz_surface": [
        ("TZ env", re.compile(r"\benviron\[.TZ.\]|\bTZ\s*=")),
        ("tzset", re.compile(r"\btzset\b")),
        ("astimezone(", re.compile(r"\bastimezone\(")),
        ("localtime/mktime", re.compile(r"\blocaltime\(|\bmktime\(")),
    ],
    "G_order_assert": [
        ("list(x) == [ (no sorted)", re.compile(r"\blist\([a-zA-Z_][\w.]*\)\s*==\s*\[")),
        (".keys() == [", re.compile(r"\.keys\(\)\s*==\s*\[")),
        ("set( near join/iterate", re.compile(r"\bjoin\([^)]*\bset\(")),
    ],
    "H_random_unseeded": [
        ("random.<fn> (line lacks Random()/seed)", re.compile(r"\brandom\.(sample|shuffle|choice|randint|random)\b")),
    ],
}

_SEEDED = re.compile(r"random\.Random\(|seed\(|patch\(.random\.random.|getrandbits")


def iter_test_files() -> list[Path]:
    files: list[Path] = []
    for path in SCAN_PATHS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
    return files


def main() -> int:
    hits: dict[str, list[str]] = defaultdict(list)
    scanned = 0
    for path in iter_test_files():
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(lines, 1):
            for category, patterns in CATEGORIES.items():
                for _label, pattern in patterns:
                    if pattern.search(line):
                        if category == "H_random_unseeded" and _SEEDED.search(line):
                            continue
                        hits[category].append(f"{rel}:{lineno}: {line.strip()[:110]}")
                        break

    print(f"# scanned test files: {scanned}")
    for category in CATEGORIES:
        entries = hits.get(category, [])
        print(f"\n## {category} ({len(entries)} hits)")
        for entry in entries:
            print(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
