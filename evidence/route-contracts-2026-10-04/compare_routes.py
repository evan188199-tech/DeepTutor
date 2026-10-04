#!/usr/bin/env python3
"""Compare frontend call heads against backend effective routes.

Inputs: backend_routes.tsv (mount, rprefix, method, path, loc, effective),
        frontend_calls.tsv (head, loc, zone).
Outputs comparison.tsv: head, zone, frontend_loc, status, backend_examples,
                        fmethod, note

status: OK | DRIFT(404) | OK(next-handler-forward) | INFO(policy/test) |
        METHOD? (heuristic method mismatch on exact-concrete match)
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
EV = ROOT / "evidence" / "route-contracts-2026-10-04"

SEG_PARAM = re.compile(r"^\{[^}]+\}$")
QUERY = re.compile(r"[?#].*$")
METHOD_RE = re.compile(r"""method\s*:\s*["']([A-Z]+)["']""")


def load_backend():
    routes = []  # (method, effective, loc)
    for line in (EV / "backend_routes.tsv").read_text().splitlines():
        mount, rpre, meth, p, loc, eff = line.split("\t")
        if eff.startswith("UNRESOLVED"):
            continue
        routes.append((meth, eff, loc))
    return routes


def segs(p):
    return [s for s in p.split("/") if s != ""]


def align(head_segs, route_segs):
    """How many leading segments align; head matches route when
    len(head_segs)==len(route_segs) and all align, or head is a static prefix
    (route extends with further segments)."""
    n = 0
    for h, r in zip(head_segs, route_segs):
        if SEG_PARAM.match(r) or h == r:
            n += 1
        else:
            break
    return n


def load_frontend():
    calls = []
    for line in (EV / "frontend_calls.tsv").read_text().splitlines():
        parts = line.split("\t")
        head, loc, zone = parts[0], parts[1], parts[2]
        parametric = len(parts) > 3 and parts[3] == "PARAM"
        calls.append((head, loc, zone, parametric))
    return calls


def method_at(webroot, loc):
    """Forward-search within the SAME fetch call: from the literal line, scan
    up to 8 lines ahead; stop at a new call boundary (apiUrl(/apiFetch(/fetch()
    on a line that precedes any method:). Returns method or ''."""
    rel, _, line = loc.rpartition(":")
    f = webroot / rel
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    ln = int(line) - 1
    for i in range(ln, min(len(lines), ln + 9)):
        seg = lines[i]
        m = METHOD_RE.search(seg)
        if m:
            return m.group(1)
        # a new call boundary after the literal line means method never appeared
        if i > ln and re.search(r"apiUrl\(|apiFetch\(|\bfetch\(", seg):
            return ""
    return ""


def main():
    routes = load_backend()
    calls = load_frontend()
    webroot = ROOT / "web"

    # group backend by effective path pattern
    by_pattern = defaultdict(list)
    for meth, eff, loc in routes:
        by_pattern[eff].append((meth, loc))

    out = []
    for head, loc, zone, parametric in calls:
        h = QUERY.sub("", head).rstrip("/")
        head_segs = segs(h)
        # policy/test/fixture/next-handler literals are not real call sites
        if zone in ("tests",) or loc.startswith(("proxy.ts", "lib/proxy-policy.ts")) or "/route.ts" in loc:
            status = "INFO(policy/test/handler)"
            out.append((head, zone, loc, status, "", "", ""))
            continue
        best = []  # (align_count, eff)
        for eff in by_pattern:
            n = align(head_segs, segs(eff))
            if n == len(head_segs):
                best.append((len(segs(eff)), eff))
        if not best:
            # drift
            out.append((head, zone, loc, "DRIFT(404)", "", method_at(webroot, loc), "no backend route aligns"))
            continue
        best.sort(reverse=True)
        # exact concrete match & method heuristic — only for non-parametric literals
        note = ""
        fmethod = "" if parametric else method_at(webroot, loc)
        exact = [eff for _, eff in best if segs(eff) == head_segs and not any(SEG_PARAM.match(s) for s in segs(eff))]
        if exact and fmethod:
            methods = {m for eff in exact for m, _ in by_pattern[eff]}
            if fmethod not in methods:
                note = f"heuristic-method {fmethod} not in {sorted(methods)}"
        examples = "; ".join(
            f"{m} {eff} ({loc2})" for eff in [e for _, e in best[:2]] for m, loc2 in by_pattern[eff][:2]
        )
        status = "OK"
        out.append((head, zone, loc, status, examples, fmethod, note))

    with open(EV / "comparison.tsv", "w") as f:
        for row in out:
            f.write("\t".join(row) + "\n")
    drifts = [r for r in out if r[3].startswith("DRIFT")]
    method_flags = [r for r in out if r[6]]
    print(f"total={len(out)} drift={len(drifts)} method_flags={len(method_flags)}")
    for r in drifts:
        print("DRIFT:", r[0], "@", r[2])
    for r in method_flags:
        print("METHOD?:", r[0], "@", r[2], "->", r[6])


if __name__ == "__main__":
    main()
