#!/usr/bin/env python3
"""Read-only evidence integrity recompute for myfork scan/* branches.

For each sampled branch:
  1. List files under evidence/ from the git tree (no checkout).
  2. Parse each evidence/**/SHA256SUMS manifest.
  3. Recompute sha256 of every listed file from `git cat-file blob` bytes.
  4. Compare manifest vs tree (missing / extra, manifest itself excluded).
Emit JSON results.
"""
import hashlib
import json
import subprocess
import sys

REPO = "/Users/Shared/DeepTutor"

BRANCHES = [
    "myfork/scan/a11y-basics-20261005",
    "myfork/scan/coverage-gaps-20261005",
    "myfork/scan/cli-exit-codes-20261006",
    "myfork/scan/win-compat-20261004",
    "myfork/scan/mypy-adoption-20261006",
    "myfork/scan/web-error-boundaries-20261006",
    "myfork/scan/signal-handlers-20261007",
    "myfork/scan/settings-draft-apply-20261003",
]


def git_bytes(rev_path: str) -> bytes:
    out = subprocess.run(
        ["git", "-C", REPO, "cat-file", "blob", rev_path],
        capture_output=True,
        check=True,
    )
    return out.stdout


def git_text(rev_path: str) -> str:
    return git_bytes(rev_path).decode("utf-8", errors="replace")


def git_list_tree(branch: str, path: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", REPO, "ls-tree", "-r", "--name-only", branch, "--", path],
        capture_output=True,
        check=True,
        text=True,
    )
    return [l for l in out.stdout.splitlines() if l.strip()]


def main() -> None:
    results = []
    for branch in BRANCHES:
        files = git_list_tree(branch, "evidence/")
        manifests = [f for f in files if f.endswith("/SHA256SUMS")]
        brec = {"branch": branch, "evidence_file_count": len(files), "manifests": []}
        for mfst in manifests:
            mdir = mfst.rsplit("/", 1)[0]
            rec = {"manifest": mfst, "dir": mdir, "entries": [], "recomputed": 0,
                   "match": 0, "mismatch": [], "unreadable": [],
                   "in_tree_not_in_manifest": [], "in_manifest_not_in_tree": []}
            dir_files = sorted(f for f in files if f.startswith(mdir + "/"))
            try:
                text = git_text(f"{branch}:{mfst}")
            except subprocess.CalledProcessError as e:
                rec["unreadable"].append(f"manifest: {e}")
                brec["manifests"].append(rec)
                continue
            listed = []
            for lineno, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    rec["mismatch"].append(
                        {"path": f"{mfst}:line{lineno}", "expected": line, "actual": "UNPARSEABLE"})
                    continue
                expected, rel = parts
                rel = rel.lstrip("*").strip()
                while rel.startswith("./"):
                    rel = rel[2:]
                full = f"{mdir}/{rel}"
                listed.append(full)
                if full not in files:
                    rec["in_manifest_not_in_tree"].append(full)
                    rec["mismatch"].append(
                        {"path": full, "expected": expected, "actual": "MISSING_FROM_TREE"})
                    continue
                try:
                    blob = git_bytes(f"{branch}:{full}")
                    actual = hashlib.sha256(blob).hexdigest()
                except subprocess.CalledProcessError as e:
                    rec["unreadable"].append(f"{full}: {e}")
                    rec["mismatch"].append(
                        {"path": full, "expected": expected, "actual": "UNREADABLE"})
                    continue
                rec["recomputed"] += 1
                if actual == expected:
                    rec["match"] += 1
                else:
                    rec["mismatch"].append({"path": full, "expected": expected, "actual": actual})
            extra = [f for f in dir_files
                     if f not in listed and not f.endswith("/SHA256SUMS")]
            rec["in_tree_not_in_manifest"] = extra
            brec["manifests"].append(rec)
        results.append(brec)

    total_recomputed = sum(m["recomputed"] for b in results for m in b["manifests"])
    total_mismatch = sum(len(m["mismatch"]) for b in results for m in b["manifests"])
    summary = {"branches": len(results), "recomputed_files": total_recomputed,
               "mismatch_entries": total_mismatch}
    json.dump({"summary": summary, "results": results}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
