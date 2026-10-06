#!/usr/bin/env python3
"""Assertion-strength sampler (static, AST-based) for AGEN-662.

For a fixed sample of (module, covering-test-file) pairs, computes per-file:
  test functions, assert statements, pytest.raises uses, mock/patch references.
No test execution here; single-file pytest runs are recorded separately.
Stdlib only.
"""
import ast
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SAMPLE = [
    # (module, covering test file relative to repo root, role)
    ("services.config.readiness", "tests/services/config/test_readiness.py", "weak"),
    ("api.routers.co_writer", "tests/api/test_co_writer.py", "weak"),
    ("co_writer.docx_converter", "tests/api/test_co_writer.py", "weak"),
    ("partners.channels.napcat", "tests/services/partners/test_napcat_channel.py", "weak"),
    ("services.llm.provider_core.codebuddy_provider", "tests/services/llm/test_codebuddy_provider.py", "weak"),
    ("services.session.turns.lifecycle", "tests/services/test_hermes_remote_backend_lifecycle.py", "weak"),
    ("services.voice.adapters.openai_compat", "tests/services/test_voice.py", "weak"),
    ("multi_user.device_credentials", "tests/multi_user/test_guardians.py", "weak"),
    ("services.memory.consolidator.line_doc", "tests/services/memory/test_line_doc.py", "weak"),
    ("services.search.source_filter", "tests/services/search/test_web_search_runtime.py", "weak"),
    ("api.routers.mastery_path", "deeptutor/learning/tests/test_mastery_tools.py", "intree-weak"),
    ("partners.channels.msteams", "tests/services/partners/test_msteams_channel.py", "weak"),
    # controls (recently authored test cards, expected stronger)
    ("events.event_bus (control)", "tests/runtime/test_orchestrator.py", "control"),
    ("core.config_manager (control)", "tests/core/test_config_manager.py", "control"),
    ("services.session.sqlite_store (control)", "tests/services/session/test_sqlite_store.py", "control"),
]

MOCK_HINTS = ("MagicMock", "mock.patch", "monkeypatch", "Mock(", "AsyncMock", "faker", "Fake")


def analyze(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return {"file": path, "missing": True}
    src = open(full, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"file": path, "syntax_error": True}
    n_test_fn = n_assert = n_raises = 0
    n_mock_refs = 0
    fn_asserts = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            n_test_fn += 1
            a = sum(1 for x in ast.walk(node) if isinstance(x, ast.Assert))
            fn_asserts.append(a)
        if isinstance(node, ast.Assert):
            n_assert += 1
        if isinstance(node, getattr(ast, "With", ())) or isinstance(node, getattr(ast, "AsyncWith", ())):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    fn = item.context_expr.func
                    name = getattr(fn, "attr", None) or getattr(fn, "id", "")
                    if name == "raises":
                        n_raises += 1
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", "")
            if name in ("patch", "Mock", "MagicMock", "AsyncMock", "mock"):
                n_mock_refs += 1
    n_mock_refs += sum(src.count(h) for h in MOCK_HINTS) // 4  # de-noised textual hint
    fn_asserts_sorted = sorted(fn_asserts)
    med = fn_asserts_sorted[len(fn_asserts_sorted) // 2] if fn_asserts_sorted else 0
    zero_assert_fns = sum(1 for a in fn_asserts_sorted if a == 0)
    return {
        "file": path,
        "test_functions": n_test_fn,
        "asserts": n_assert,
        "asserts_per_test_median": med,
        "zero_assert_test_functions": zero_assert_fns,
        "pytest_raises": n_raises,
        "mock_refs": n_mock_refs,
        "loc": src.count("\n") + 1,
    }


def main():
    rows = [analyze(p) for _, p, role in SAMPLE]
    out = {"sample": [{"module": m, "role": r, **analyze(p)} for m, p, r in SAMPLE]}
    with open(os.path.join(HERE, "assertion_sample.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for r in out["sample"]:
        if r.get("missing"):
            print(f"MISSING {r['file']}")
            continue
        print(f"{r['module']:45s} fns={r['test_functions']:3d} asserts={r['asserts']:3d} "
              f"med/test={r['asserts_per_test_median']} zero-assert-fns={r['zero_assert_test_functions']:3d} "
              f"raises={r['pytest_raises']:3d} mocks~{r['mock_refs']:3d}")


if __name__ == "__main__":
    main()
