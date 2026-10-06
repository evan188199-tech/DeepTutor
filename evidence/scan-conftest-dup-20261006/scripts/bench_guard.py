"""Measure the per-test cost of the root conftest's secret-tree guard.

tests/conftest.py::_guard_real_owner_secrets snapshots four real trees with
Path.rglob before and after every test. This script measures that cost on a
synthetic tree and extrapolates to the suite size (7266 test functions as of
the scanned head).

Read-only for the repository: writes its synthetic tree under a temp dir.

    python evidence/scan-conftest-dup-20261006/scripts/bench_guard.py
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

SUITE_TESTS = 7266  # `def test_` occurrences under tests/ at scanned head


def snapshot(root: Path) -> frozenset[str]:
    if not root.is_dir():
        return frozenset()
    return frozenset(str(p) for p in root.rglob("*") if p.is_file())


def main() -> None:
    results = []
    for n_files in (0, 1000, 5000, 20000):
        tmp = Path(tempfile.mkdtemp(prefix="bench-guard-"))
        tree = tmp / "user-secrets"
        tree.mkdir()
        for i in range(n_files):
            d = tree / f"d{i // 100:03d}"
            d.mkdir(exist_ok=True)
            (d / f"f{i}.txt").write_text("x")
        t0 = time.perf_counter()
        before = snapshot(tree)
        after = snapshot(tree)
        added = after - before
        dt = time.perf_counter() - t0
        per_suite = dt * 2 * SUITE_TESTS
        results.append((n_files, dt, len(before), len(added), per_suite))
        print(
            f"tree={n_files:6d} files | snapshot x2 = {dt * 1000:8.1f} ms"
            f" | per full suite (x2 x {SUITE_TESTS}) = {per_suite / 60:6.1f} min"
        )
        shutil.rmtree(tmp)

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
        print(f"\nSummary lines written for reference: {len(results)} entries")
        fh.close()
        Path(fh.name).unlink()


if __name__ == "__main__":
    main()
