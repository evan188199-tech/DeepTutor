import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1])
EXCLUDE_PARTS = {"node_modules", ".git", "dist", "build", ".next", "__pycache__"}
EXCLUDE_PREFIXES = ("test_",)
EXCLUDE_DIR_NAMES = {"tests"}

findings = []


def rel(p: pathlib.Path) -> str:
    return str(p.relative_to(ROOT))


def is_test(path: pathlib.Path) -> bool:
    parts = path.relative_to(ROOT).parts
    return "tests" in parts or path.name.startswith("test_")


for path in ROOT.rglob("*.py"):
    if any(part in EXCLUDE_PARTS for part in path.parts):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        findings.append(
            {
                "file": rel(path),
                "line": exc.lineno or 0,
                "kind": "syntax_error",
                "detail": str(exc.msg),
                "test": is_test(path),
            }
        )
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        only_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
        only_continue = len(body) == 1 and isinstance(body[0], ast.Continue)
        bare = node.type is None
        broad = (
            node.type is not None
            and isinstance(node.type, ast.Name)
            and node.type.id == "Exception"
        )
        kinds = []
        if bare:
            kinds.append("bare_except")
        if only_pass:
            kinds.append("swallow_pass")
        if only_continue:
            kinds.append("swallow_continue")
        if broad:
            kinds.append("broad_exception")
        if kinds:
            findings.append(
                {
                    "file": rel(path),
                    "line": node.lineno,
                    "kinds": kinds,
                    "test": is_test(path),
                    "snippet": ast.unparse(node)[:120],
                }
            )

print(json.dumps(findings, ensure_ascii=False, indent=1))
print(f"# handlers={len(findings)}", file=sys.stderr)
