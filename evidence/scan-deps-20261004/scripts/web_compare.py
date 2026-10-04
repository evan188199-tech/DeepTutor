#!/usr/bin/env python3
"""Compare web/package.json + package-lock.json against collected web imports.

Outputs raw/web_analysis.json with:
  declared deps, imported pkgs, undeclared imports, unused declarations,
  lockfile version-range mismatches.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
RAW = ROOT / "evidence/scan-deps-20261004/raw"
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "constants", "crypto",
    "dgram", "dns", "domain", "events", "fs", "http", "http2", "https", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline", "repl",
    "stream", "string_decoder", "timers", "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib",
}

# js bundles that ship types/impl under different npm names
IMPORT_TO_NPM = {}


def parse_ver(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", v.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def cmp_ver(a, b):
    return (a > b) - (a < b)


def satisfies(version, range_):
    v = parse_ver(version)
    if v is None:
        return True  # unusual version strings: skip
    range_ = range_.strip()
    if range_ in ("*", "", "latest", "x"):
        return True
    for alt in range_.split("||"):
        if _satisfies_alt(v, alt.strip()):
            return True
    return False


def _satisfies_alt(v, alt):
    if not alt:
        return True
    parts = alt.split()
    if not parts:
        return True
    ok = True
    # hyphen range "1.2.3 - 2.0.0"
    if " - " in alt:
        lo, hi = [p.strip() for p in alt.split(" - ", 1)]
        lv, hv = parse_ver(lo), parse_ver(hi)
        if lv and cmp_ver(v, lv) < 0:
            return False
        if hv and cmp_ver(v, hv) > 0:
            return False
        return True
    for p in parts:
        m = re.match(r"^(\^|~|>=|<=|>|<|=)?\s*v?(\d+|x|\*)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?(?:[-+].*)?$", p)
        if not m:
            continue  # unknown syntax: ignore comparator
        op, maj, mi, pa = m.group(1) or "=", m.group(2), m.group(3), m.group(4)
        if not maj.isdigit():
            continue  # wildcard major: always true
        if mi is None or mi == "x" or pa is None or pa == "x":
            # x-range like "1" or "1.2"
            if op in ("=", "^", "~", ">="):
                upper = (int(maj) + 1, 0, 0) if (mi in (None, "x")) else (int(maj), int(mi) + 1, 0)
                if cmp_ver(v, (int(maj), 0, 0)) < 0 or (op != ">=" and cmp_ver(v, upper) >= 0):
                    ok = ok and (op == ">=")
                continue
        base = (int(maj), int(mi) if mi and mi.isdigit() else 0, int(pa) if pa and pa.isdigit() else 0)
        if op == "=" or op == "":
            if cmp_ver(v, base) != 0:
                ok = False
        elif op == ">=":
            if cmp_ver(v, base) < 0:
                ok = False
        elif op == ">":
            if cmp_ver(v, base) <= 0:
                ok = False
        elif op == "<=":
            if cmp_ver(v, base) > 0:
                ok = False
        elif op == "<":
            if cmp_ver(v, base) >= 0:
                ok = False
        elif op == "^":
            if cmp_ver(v, base) < 0:
                ok = False
            if base[0] > 0:
                upper = (base[0] + 1, 0, 0)
            elif base[1] > 0:
                upper = (0, base[1] + 1, 0)
            else:
                upper = (0, 0, base[2] + 1)
            if cmp_ver(v, upper) >= 0:
                ok = False
        elif op == "~":
            if cmp_ver(v, base) < 0:
                ok = False
            upper = (base[0], base[1] + 1, 0)
            if cmp_ver(v, upper) >= 0:
                ok = False
    return ok


def main():
    pkg = json.load(open(ROOT / "web/package.json"))
    deps = pkg.get("dependencies", {})
    devdeps = pkg.get("devDependencies", {})
    lock = json.load(open(ROOT / "web/package-lock.json"))

    # lockfile v2/v3
    lock_versions = {}
    for key, info in lock.get("packages", {}).items():
        if not key.startswith("node_modules/"):
            continue
        name = key[len("node_modules/"):]
        if name.startswith("@"):
            if name.count("/") != 1:
                continue  # nested copy under a scope
        elif "/" in name:
            continue  # nested copies: skip, top-level wins
        if name not in lock_versions:
            lock_versions[name] = info.get("version", "?")

    data = json.load(open(RAW / "web_imports.json"))
    imported = {}
    for f in data["files"]:
        for i in f["imports"]:
            rec = imported.setdefault(i["pkg"], {"files": [], "dynamic": 0, "require": 0, "static": 0})
            rec["files"].append(f["path"])
            rec["dynamic"] += len(i["dynamic"])
            rec["require"] += len(i["require"])
            rec["static"] += len(i["static"])

    declared = {**deps, **devdeps}

    # 1. undeclared imports
    undeclared = []
    for p in sorted(imported):
        if p in NODE_BUILTINS or p in declared:
            continue
        if p in ("eslint-config-next",):
            continue
        undeclared.append({
            "pkg": p,
            "files": sorted(set(imported[p]["files"]))[:8],
            "static": imported[p]["static"], "dynamic": imported[p]["dynamic"], "require": imported[p]["require"],
        })

    # 2. declared but unused
    unused = []
    for name in sorted(declared):
        if name in imported:
            continue
        # config-referenced tooling check (raw text mention anywhere under web/)
        import subprocess
        try:
            r = subprocess.run(["grep", "-rIl", "--exclude-dir=node_modules", "--exclude-dir=.next",
                                "--exclude=package-lock.json", name, str(ROOT / "web")],
                               capture_output=True, text=True, timeout=60)
            refs = [x.replace(str(ROOT / "web") + "/", "") for x in r.stdout.splitlines()]
        except Exception:
            refs = []
        unused.append({"pkg": name, "kind": "dependencies" if name in deps else "devDependencies",
                       "spec": declared[name], "text_refs": refs[:8]})

    # 3. dynamic/require-guarded imports of undeclared pkgs
    guarded_undeclared = [u for u in undeclared if u["static"] == 0]

    # 4. lockfile drift: resolved version outside declared range
    drift = []
    for name, spec in sorted(declared.items()):
        lv = lock_versions.get(name)
        if lv is None:
            drift.append({"pkg": name, "spec": spec, "lock_version": "MISSING from lockfile", "ok": False})
        elif not satisfies(lv, spec):
            drift.append({"pkg": name, "spec": spec, "lock_version": lv, "ok": False})
    # overrides check
    overrides = pkg.get("overrides", {})
    override_notes = []
    for name, rule in overrides.items():
        if isinstance(rule, dict):
            for sub, subrule in rule.items():
                resolved = lock_versions.get(sub)
                override_notes.append({"parent": name, "pkg": sub, "override": subrule, "lock_version": resolved})

    result = {
        "imported_count": len(imported),
        "declared_count": len(declared),
        "category1_undeclared": undeclared,
        "category2_unused": unused,
        "category3_guarded_dynamic_undeclared": guarded_undeclared,
        "category4_lockfile_drift": drift,
        "category4_overrides": override_notes,
        "lockfile_version": lock.get("lockfileVersion"),
    }
    out = RAW / "web_analysis.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"wrote {out}")
    print("undeclared:", len(undeclared), "unused:", len(unused), "drift:", len(drift))


if __name__ == "__main__":
    main()
