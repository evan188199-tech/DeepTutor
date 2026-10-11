#!/usr/bin/env python3
"""Three-way reconciliation of the GLM reserve ledger: pools.json / backlog/*.jsonl / <pool>.consumed.

Read-only on the reserve directory. Mirrors multica_board_agent/reserve.py load semantics:
- load order: sorted(glob "<pool>.jsonl") + sorted(glob "<pool>.*.jsonl"); first occurrence of a key wins
- blank lines skipped silently; invalid lines reported (bad JSON, missing truthy key/title/description,
  duplicate key, unexpected fields -> TypeError)
- backlog/<pool>.consumed: one key per line, blank lines skipped
Usage: reconcile_three_way.py <reserve_dir> <out_dir>
"""
import hashlib
import json
import re
import sys
from dataclasses import dataclass, fields
from pathlib import Path

sys.path.insert(0, "/Users/xzh/services/ai-development/multica-board-agent/glm-reserve")
from multica_board_agent.reserve import load_pools  # noqa: E402
from multica_board_agent.upstream_claims import upstream_number, should_hold  # noqa: E402

CAND_FIELDS = {f.name for f in fields(__import__("multica_board_agent.reserve", fromlist=["Candidate"]).Candidate)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Line:
    file: str
    lineno: int
    status: str  # blank | ok | error
    reason: str = ""
    raw: dict | None = None
    key: str | None = None
    accepted: bool = False


def parse_backlog(backlog_dir: Path, pool_key: str):
    files = sorted(backlog_dir.glob(f"{pool_key}.jsonl")) + sorted(backlog_dir.glob(f"{pool_key}.*.jsonl"))
    lines: list[Line] = []
    seen: dict[str, tuple[str, int]] = {}
    for f in files:
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            rec = Line(f.name, n, "ok")
            if not ln.strip():
                rec.status = "blank"
                lines.append(rec)
                continue
            try:
                raw = json.loads(ln)
                if not isinstance(raw, dict):
                    raise TypeError("line is not a JSON object")
                extra = set(raw) - CAND_FIELDS
                if extra:
                    raise TypeError(f"unexpected field(s): {sorted(extra)}")
                if not (raw.get("key") and raw.get("title") and raw.get("description")):
                    raise ValueError("missing field key/title/description")
                key = str(raw["key"])
                if key in seen:
                    raise ValueError(f"duplicate key (first at {seen[key][0]}:{seen[key][1]})")
            except (ValueError, TypeError) as exc:
                rec.status = "error"
                rec.reason = str(exc)
                lines.append(rec)
                continue
            seen[key] = (f.name, n)
            rec.key = key
            rec.raw = raw
            rec.accepted = True
            lines.append(rec)
    return files, lines, seen


def parse_consumed(backlog_dir: Path, pool_key: str):
    f = backlog_dir / f"{pool_key}.consumed"
    if not f.exists():
        return None, []
    entries = []
    for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        entries.append((n, ln.strip(), bool(ln.strip())))
    return f, entries


def main(reserve: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pools = load_pools(reserve / "pools.json")
    pool_report = []
    for p in pools:
        pool_report.append({
            "key": p.key, "target": p.target, "agents": p.agents, "capacity": p.capacity,
            "harvest_executor": (p.harvest or {}).get("executor"),
            "queue_depth": p.queue_depth,
        })
    pool = pools[0]
    agents = set(pool.agents)

    backlog_dir = reserve / "backlog"
    files, lines, seen = parse_backlog(backlog_dir, pool.key)
    consumed_file, consumed_raw = parse_consumed(backlog_dir, pool.key)

    # --- file-level inventory: every file in backlog/ classified against the loader glob ---
    dir_files = sorted(x.name for x in backlog_dir.iterdir() if x.is_file())
    base_glob = {f.name for f in backlog_dir.glob(f"{pool.key}.jsonl")}
    star_glob = {f.name for f in backlog_dir.glob(f"{pool.key}.*.jsonl")}
    invisible = [n for n in dir_files if n not in base_glob and n not in star_glob
                 and n != f"{pool.key}.consumed"]

    # --- per-file conservation ---
    per_file = {}
    for fname in sorted({l.file for l in lines}):
        fl = [l for l in lines if l.file == fname]
        per_file[fname] = {
            "physical_lines": len(fl),
            "blank": sum(1 for l in fl if l.status == "blank"),
            "data_lines": sum(1 for l in fl if l.status != "blank"),
            "accepted_unique": sum(1 for l in fl if l.accepted),
            "duplicate_lines": sum(1 for l in fl if l.status == "error" and "duplicate key" in l.reason),
            "invalid_lines": sum(1 for l in fl if l.status == "error" and "duplicate key" not in l.reason),
        }

    data_lines = sum(v["data_lines"] for v in per_file.values())
    unique_keys = sum(1 for l in lines if l.accepted)
    dup_lines = sum(v["duplicate_lines"] for v in per_file.values())
    invalid_lines = sum(v["invalid_lines"] for v in per_file.values())
    conservation = (unique_keys + dup_lines + invalid_lines) == data_lines

    # --- key sets ---
    B = set(seen)  # unique accepted backlog keys
    C, consumed_dupes = set(), []
    seen_c: dict[str, int] = {}
    for n, k, nonblank in consumed_raw:
        if not nonblank:
            continue
        if k in seen_c:
            consumed_dupes.append((n, k, seen_c[k]))
        else:
            seen_c[k] = n
            C.add(k)

    shadowed_by_consumed = sorted(B & C)          # in backlog AND consumed -> never recreated
    dangling_consumed = sorted(C - B)             # consumed key with no live backlog entry
    live = sorted(B - C)

    # --- executor eligibility & after-dependency resolution ---
    bad_executor, after_issues = [], []
    for l in lines:
        if not l.accepted:
            continue
        if l.raw.get("executor") not in agents:
            bad_executor.append({"file": l.file, "line": l.lineno, "key": l.key,
                                 "executor": l.raw.get("executor")})
        aft = l.raw.get("after")
        if aft is None:
            continue
        if not isinstance(aft, list):
            after_issues.append({"file": l.file, "line": l.lineno, "key": l.key,
                                 "problem": f"after is {type(aft).__name__}, not list"})
            continue
        for dep in aft:
            if dep not in B and dep not in C:
                after_issues.append({"file": l.file, "line": l.lineno, "key": l.key,
                                     "problem": f"after dep '{dep}' not in backlog/consumed keys"})

    # --- pools.json internal cross-checks (parity axis, re-verified) ---
    pool_issues = []
    if pool.capacity:
        for name in pool.capacity:
            if name not in agents:
                pool_issues.append(f"capacity executor '{name}' not in agents")
    hx = (pool.harvest or {}).get("executor")
    if hx and hx not in agents:
        pool_issues.append(f"harvest.executor '{hx}' not in agents")
    for name, aid in pool.agents.items():
        if not aid:
            pool_issues.append(f"agent '{name}' has empty id")

    # --- error line listing ---
    error_lines = [{"file": l.file, "line": l.lineno, "reason": l.reason}
                   for l in lines if l.status == "error"]

    # --- duplicate backlog key occurrences (every shadowed occurrence, with first location) ---
    dup_detail = []
    for l in lines:
        if l.status == "error" and "duplicate key" in l.reason:
            first = seen.get(l.key, ("?", 0)) if l.key in seen else None
            dup_detail.append({"file": l.file, "line": l.lineno, "key": l.key,
                               "first_at": f"{first[0]}:{first[1]}" if first else None,
                               "reason": l.reason})

    # --- claims.json informational cross-ref (4th axis, .state cache) ---
    claims_path = reserve / ".state" / f"{pool.key}.claims.json"
    claims = {}
    claims_at = None
    if claims_path.exists():
        cj = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = cj.get("claims") or {}
        claims_at = cj.get("at")
    held_live, not_checked, claim_notes = [], [], []
    for l in lines:
        if not l.accepted:
            continue
        n = upstream_number(l.key)
        if n is None:
            continue
        reasons = claims.get(l.key)
        if reasons is None:
            not_checked.append(l.key)
        elif should_hold(l.raw.get("title"), reasons):
            held_live.append(l.key)
    for k in sorted((B & C) | (C - B)):
        if upstream_number(k) is not None:
            claim_notes.append({"key": k, "claims": claims.get(k, [])})

    # --- executor / priority distribution over live keys ---
    dist = {}
    for l in lines:
        if l.accepted and l.key in set(live):
            e = str(l.raw.get("executor"))
            dist[e] = dist.get(e, 0) + 1

    # --- input fingerprints ---
    input_files = [reserve / "pools.json"] + files + ([consumed_file] if consumed_file else [])
    inputs_sha = {str(p.relative_to(reserve)): sha256(p) for p in input_files if p and p.exists()}

    result = {
        "reserve_dir": str(reserve),
        "pool": pool_report,
        "backlog_dir_inventory": {"files": dir_files, "invisible_to_loader": invisible},
        "per_file": per_file,
        "totals": {
            "data_lines": data_lines, "unique_backlog_keys": unique_keys,
            "duplicate_lines": dup_lines, "invalid_lines": invalid_lines,
            "conservation_ok": conservation,
            "consumed_lines_nonblank": len([1 for _, k, nb in consumed_raw if nb]),
            "consumed_unique": len(C), "consumed_duplicates": len(consumed_dupes),
            "live_keys": len(live), "shadowed_by_consumed": len(shadowed_by_consumed),
            "dangling_consumed": len(dangling_consumed),
        },
        "sets": {
            "shadowed_by_consumed": shadowed_by_consumed,
            "dangling_consumed": dangling_consumed,
        },
        "consumed_duplicates": [{"line": n, "key": k, "first_line": fn} for n, k, fn in consumed_dupes],
        "duplicate_detail": dup_detail,
        "error_lines": error_lines,
        "bad_executor": bad_executor,
        "after_issues": after_issues,
        "pool_issues": pool_issues,
        "claims_info": {"at": claims_at, "up_keys_held_among_live": sorted(held_live),
                        "up_keys_not_checked": sorted(not_checked), "residual_notes": claim_notes},
        "live_executor_distribution": dist,
        "inputs_sha256": inputs_sha,
    }
    (out / "reconciliation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "inputs.sha256").write_text("".join(f"{v}  {k}\n" for k, v in inputs_sha.items()), encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False, indent=2))
    print("invisible:", result["backlog_dir_inventory"]["invisible_to_loader"])
    print("shadowed_by_consumed:", result["sets"]["shadowed_by_consumed"])
    print("dangling_consumed:", result["sets"]["dangling_consumed"])
    print("dup_detail:", json.dumps(dup_detail, ensure_ascii=False))
    print("error_lines:", json.dumps(error_lines, ensure_ascii=False))
    print("bad_executor:", json.dumps(bad_executor, ensure_ascii=False))
    print("after_issues:", json.dumps(after_issues, ensure_ascii=False))
    print("pool_issues:", pool_issues)
    print("consumed_dupes:", result["consumed_duplicates"])
    print("claims residual notes:", json.dumps(claim_notes, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
