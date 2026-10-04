#!/usr/bin/env python3
"""Compare collected imports against declared dependency manifests.

Outputs raw/analysis.json with per-category candidate findings:
  1. undeclared_imports  2. declared_unused  3. optional_no_fallback  4. version_drift
"""
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
RAW = ROOT / "evidence/scan-deps-20261004/raw"
STDLIB = set(sys.stdlib_module_names)

# ---- import-name -> distribution mapping (import side) ----
IMPORT_TO_DIST = {
    "yaml": "pyyaml", "pil": "pillow", "fitz": "pymupdf", "pymupdf": "pymupdf",
    "jose": "python-jose", "docx": "python-docx", "pptx": "python-pptx",
    "telegram": "python-telegram-bot", "socketio": "python-socketio",
    "multipart": "python-multipart", "python_socks": "python-socks",
    "websocket": "websocket-client", "nio": "matrix-nio",
    "slack_sdk": "slack-sdk", "slackify_markdown": "slackify-markdown",
    "dingtalk_stream": "dingtalk-stream", "botpy": "qq-botpy", "lark_oapi": "lark-oapi",
    "jwt": "pyjwt", "llama_index": "llama-index", "faiss": "faiss-cpu",
    "sentence_transformers": "sentence-transformers", "lightrag": "lightrag-hku",
    "json_repair": "json-repair", "oauth_cli_kit": "oauth-cli-kit",
    "youtube_transcript_api": "youtube-transcript-api",
    "codebuddy_agent_sdk": "codebuddy-agent-sdk", "wecom_aibot_sdk": "wecom-aibot-sdk",
    "pytest_asyncio": "pytest-asyncio", "pre_commit": "pre-commit", "import_linter": "import-linter",
    "crypto": "pycryptodome", "pil": "pillow", "_pytest": "pytest", "perplexity": "perplexityai",
}
# distributions that are pure CLI tooling or framework-runtime (no direct import expected)
TOOLING = {
    "safety", "bandit", "pre-commit", "import-linter",
    # transport/protocol libs consumed by other SDKs, not imported directly
    "python-socks", "socksio", "websocket-client", "msgpack",
    # framework runtime hooks used implicitly by FastAPI/uvicorn
    "python-multipart", "uvicorn",
    # external CLI invoked via subprocess
    "manim",
}
# namespace sub-packages shipped inside another declared dist (transitive of a declared one)
TRANSITIVE_OF = {
    "graphrag_llm": "graphrag", "graphrag_cache": "graphrag", "graphrag_storage": "graphrag",
    "starlette": "fastapi", "httpcore": "httpx", "anyio": "httpx",
    "lxml": "pdfplumber",  # candidate: verify usage context
    "pyarrow": "lightrag-hku",  # candidate: verify usage context
    "packaging": "setuptools",
}


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_req_line(line):
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s*\[([^\]]*)\])?\s*(.*)$", line)
    if not m:
        return None
    name, extras, spec = m.group(1), m.group(2), m.group(3).strip()
    marker = ""
    if ";" in spec:
        spec, marker = spec.split(";", 1)
        marker = marker.strip()
    return {"name": norm(name), "raw_name": name, "spec": spec.strip(), "marker": marker.replace('"', "'")}


def load_python_manifests():
    pp = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]
    core = {}
    for d in pp["dependencies"]:
        r = parse_req_line(d)
        if r:
            core[r["name"]] = r
    extras = {}
    for extra, deps in pp.get("optional-dependencies", {}).items():
        ex = {}
        for d in deps:
            r = parse_req_line(d)
            if r:
                ex[r["name"]] = r
        extras[extra] = ex
    requires_python = pp.get("requires-python", "")
    return core, extras, requires_python


def load_requirements_mirrors():
    mirrors = {}
    reqdir = ROOT / "requirements"
    for f in sorted(reqdir.glob("*.txt")):
        items = {}
        for line in f.read_text().splitlines():
            r = parse_req_line(line)
            if r:
                items[r["name"]] = r
        mirrors[f.name] = items
    return mirrors


def load_py_imports():
    data = json.load(open(RAW / "py_imports.json"))
    out = {}  # top-name -> list of occurrences
    for f in data["files"]:
        for i in f["imports"]:
            if i["relative"] or i["top"] in ("", "."):
                continue
            out.setdefault(i["top"], []).append({
                "path": f["path"], "line": i["line"], "module": i["module"],
                "lazy": i["lazy"], "guarded": i["guarded"], "weak_guard": i["weak_guard"],
                "type_checking": i["type_checking"],
            })
    dynamic = data["dynamic"]
    spec_checks = {}
    for f in data["files"]:
        for t in f.get("spec_checks", []):
            spec_checks.setdefault(t, []).append(f["path"])
    return out, dynamic, spec_checks


def main():
    core, extras, requires_python = load_python_manifests()
    mirrors = load_requirements_mirrors()
    py_imports, dynamic_imports, spec_checks = load_py_imports()

    all_declared = set(core) | {d for ex in extras.values() for d in ex} - {"deeptutor", "deeptutor-cli"}
    core_set = {n for n in core if n not in ("deeptutor", "deeptutor-cli")}
    runtime_dirs = ("deeptutor/", "deeptutor_cli/", "deeptutor_web/")

    # ---------- category 1: undeclared imports ----------
    undeclared = []
    for top, occ in sorted(py_imports.items()):
        if top in STDLIB or top in ("tests", "deeptutor", "deeptutor_cli", "deeptutor_web", "__future__"):
            continue
        dist = IMPORT_TO_DIST.get(top.lower(), norm(top))
        if dist in all_declared:
            continue
        if top in TRANSITIVE_OF:
            undeclared.append({"import": top, "dist_guess": dist, "transitive_of": TRANSITIVE_OF[top],
                               "declared": False, "occurrences": occ})
            continue
        undeclared.append({"import": top, "dist_guess": dist, "declared": False, "occurrences": occ})

    # ---------- category 2: declared but unused ----------
    observed_dists = {}
    for top in py_imports:
        d = IMPORT_TO_DIST.get(top.lower(), norm(top))
        observed_dists.setdefault(d, []).append(top)
    # dynamic import_module targets also count as observed
    for dyn in dynamic_imports:
        top = dyn["target"].split(".")[0]
        d = IMPORT_TO_DIST.get(top.lower(), norm(top))
        observed_dists.setdefault(d, []).append(f"dynamic:{dyn['target']}")
    # namespace-subpackage credit: dists whose import path lives under another namespace
    SUBPATH_TO_DIST = {
        "llama_index.retrievers.bm25": "llama-index-retrievers-bm25",
        "llama_index.retrievers.bm25s": "llama-index-retrievers-bm25",
        "llama_index.vector_stores.faiss": "llama-index-vector-stores-faiss",
    }
    for top, occ in py_imports.items():
        for o in occ:
            for sub, dist in SUBPATH_TO_DIST.items():
                if o["module"].split("::")[0].startswith(sub):
                    observed_dists.setdefault(dist, []).append(f"{o['path']}:{o['line']}")
    # raw-text fallback: some dists are referenced by name string in code/config
    def referenced_in_tree(dist, dirs):
        import subprocess
        try:
            r = subprocess.run(
                ["grep", "-rIl", "--exclude-dir=.git", "--exclude-dir=node_modules",
                 "--exclude-dir=.next", dist] + [str(ROOT / d) for d in dirs],
                capture_output=True, text=True, timeout=60)
            return [l.strip() for l in r.stdout.splitlines()]
        except Exception:
            return []

    unused = []
    for dist in sorted(all_declared):
        if dist in observed_dists:
            continue
        where = referenced_in_tree(dist, ["deeptutor", "deeptutor_cli", "scripts", "tests", "web", "Dockerfile", "Dockerfile.runner", "pyproject.toml"])
        tag = "not-imported"
        if dist in TOOLING:
            tag = "tooling-or-transport"
        unused.append({"dist": dist, "tag": tag, "text_refs": [p.replace(str(ROOT) + "/", "") for p in where[:10]]})

    # ---------- category 3: optional dependency without fallback ----------
    optional_dists = all_declared - core_set
    optional_imports = []
    for top, occ in sorted(py_imports.items()):
        dist = IMPORT_TO_DIST.get(top.lower(), norm(top))
        if dist not in optional_dists:
            continue
        for o in occ:
            optional_imports.append({"import": top, "dist": dist, **o})

    # undeclared & non-stdlib imports also raise runtime risk: report guard status for runtime dirs
    risk_points = []
    for u in undeclared:
        for o in u["occurrences"]:
            if o["path"].startswith(runtime_dirs):
                risk_points.append({"import": u["import"], **o})

    # ---------- category 4: version drift ----------
    drift = {"pyproject_vs_requirements": [], "dockerfile_pins": [], "intra_pyproject": []}

    # 4a. mirror files vs pyproject extras (each requirements file declares which extra it mirrors)
    mirror_map = {
        "cli.txt": "cli", "dev.txt": "dev", "math-animator.txt": "math-animator",
        "matrix-e2e.txt": "matrix-e2e", "matrix.txt": "matrix", "partners.txt": "partners",
        "rag-rerank.txt": "rag-rerank", "server.txt": "server", "video-learning.txt": "video-learning",
    }
    # effective sets: each mirror also includes transitively included requirements (-r lines)
    inc_map = {
        "cli.txt": [], "server.txt": ["cli.txt"], "partners.txt": ["server.txt"],
        "matrix.txt": ["partners.txt"], "matrix-e2e.txt": ["matrix.txt"],
        "dev.txt": ["server.txt"], "rag-rerank.txt": [], "math-animator.txt": [], "video-learning.txt": [],
    }

    def flatten(mirror_name, seen=None):
        seen = seen or set()
        items = dict(mirrors[mirror_name])
        for inc in inc_map[mirror_name]:
            if inc not in seen:
                seen.add(inc)
                items.update(flatten(inc, seen))
        return items

    def pyproject_effective(extra):
        """pyproject deps an extra pulls in (following self-references)."""
        eff = {}
        order = ["cli", "server", "partners", "matrix", "matrix-e2e", "dev"]
        def add(extra_name, seen):
            if extra_name in seen:
                return
            seen.add(extra_name)
            for n, r in extras.get(extra_name, {}).items():
                if n.startswith("deeptutor"):
                    m = re.match(r"deeptutor\[([a-z0-9-]+)\]", r["spec"].strip())
                    if m:
                        add(m.group(1), seen)
                    continue
                eff[n] = r
        # extras stack onto core deps (server includes core transitively via wheel but in source install `pip install -e ".[x]"` also installs core dependencies)
        for n, r in core.items():
            eff.setdefault(n, r)
        add(extra, set())
        return eff

    for fname, extra in mirror_map.items():
        # compare only the packages the mirror file itself lists (not -r includes)
        own = mirrors[fname]
        eff = pyproject_effective(extra)
        for n, r in own.items():
            if n not in eff:
                drift["pyproject_vs_requirements"].append({
                    "file": f"requirements/{fname}", "package": n, "mirror_spec": r["spec"],
                    "pyproject": "ABSENT (extra does not declare it)", "kind": "missing-in-pyproject-extra"})
                continue
            pr = eff[n]
            if r["spec"].strip() != pr["spec"].strip() or r["marker"] != pr["marker"].replace('"', "'"):
                drift["pyproject_vs_requirements"].append({
                    "file": f"requirements/{fname}", "package": n,
                    "mirror_spec": r["spec"] + ("; " + r["marker"] if r["marker"] else ""),
                    "pyproject": pr["spec"] + ("; " + pr["marker"] if pr["marker"] else ""),
                    "kind": "spec-mismatch"})

    # 4b. Dockerfile.runner unversioned installs vs pyproject caps
    runner = (ROOT / "Dockerfile.runner").read_text()
    pins = []
    lines = runner.splitlines()
    for idx, ln in enumerate(lines):
        if "pip install --no-cache-dir" in ln and ln.rstrip().endswith("\\"):
            j = idx + 1
            while j < len(lines):
                seg = lines[j].strip().rstrip("\\").strip()
                if not seg:
                    j += 1
                    continue
                if lines[j].rstrip().endswith("\\"):
                    pins.append(seg)
                    j += 1
                else:
                    pins.append(seg)
                    break
    pins = [p for p in pins if p and not p.startswith("#")]
    for p in pins:
        r = parse_req_line(p)
        if not r:
            continue
        if r["name"] in core:
            core_spec = core[r["name"]]["spec"]
            if not re.search(r"[><=]", core_spec) and not re.search(r"[><=]", r["spec"]):
                continue
            drift["dockerfile_pins"].append({
                "package": r["raw_name"], "runner_spec": r["spec"] or "(unversioned)",
                "pyproject_spec": core_spec, "kind": "unversioned-vs-capped"})
        else:
            drift["dockerfile_pins"].append({
                "package": r["raw_name"], "runner_spec": r["spec"] or "(unversioned)",
                "pyproject_spec": "NOT DECLARED", "kind": "not-declared"})

    # 4c. intra-pyproject: same dist declared with different specs in core vs extras
    seen_pairs = set()
    for extra, ex in extras.items():
        for n, r in ex.items():
            if n in core and core[n]["spec"].strip() != r["spec"].strip():
                key = (n, extra)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    drift["intra_pyproject"].append({
                        "package": n, "core_spec": core[n]["spec"], "extra": extra, "extra_spec": r["spec"]})

    result = {
        "requires_python": requires_python,
        "declared_core": sorted(core),
        "declared_extras": {k: sorted(v) for k, v in extras.items()},
        "category1_undeclared": undeclared,
        "category2_unused": unused,
        "category3_optional_imports": optional_imports,
        "category3_risk_points": risk_points,
        "category4_drift": drift,
        "dynamic_imports": dynamic_imports,
    }
    out = RAW / "analysis.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"wrote {out}")
    print("c1:", len(undeclared), "c2:", len(unused), "c3 imports:", len(optional_imports),
          "risk:", len(risk_points))


if __name__ == "__main__":
    main()
