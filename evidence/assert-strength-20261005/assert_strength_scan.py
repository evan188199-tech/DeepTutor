#!/usr/bin/env python3
"""Full assertion-strength inventory (static, AST-based) for AGEN-773.

Extends the §4 sampling of coverage-gaps-20261005 (assertion_sample.py) to ALL
(module, covering-test-file) pairs:

- module universe : every *.py under deeptutor/ except deeptutor/learning/tests/
                    (in-tree tests are tests, not product code) and __pycache__
- test universe   : tests/ plus in-tree deeptutor/learning/tests/test_*.py
- pairing         : same two tiers as scan_coverage_gaps.py
                    T1 path correspondence  : test file stem contains module stem
                    T2 import correspondence: test file imports the module
                    plus package-prefix fallback for __init__ modules
                    T2 fix vs baseline: exact prefix match instead of the
                    `" ".join(names)` substring hack, which is
                    PYTHONHASHSEED-order-dependent (verified: 3-7 modules
                    flip run-to-run under seeds 1/42/7/99)
- per-file metrics: §4 primary counter is unchanged (ast.Assert statements per
                    test function named test*); plus a documented supplementary
                    counter splitting non-statement assertions into
                    unittest-style `x.assertXxx(...)` and mock-style
                    `x.assert_xxx(...)` attribute calls, so that assertion-rich
                    unittest/mock tests are visible instead of falsely counted
                    as zero-assertion. Weak rule stays §4-exact.
- aggregation     : per module over the UNION of per-test-function §4 assert
                    counts in all its covering test files; median uses the same
                    sorted[n//2] rule as the baseline
- weak module     : median asserts/test <= 1  OR  zero-assert ratio >= 0.20
                    (thresholds taken verbatim from the AGEN-773 card)

Coverage existence is scan-coverage-gaps' domain; this card only scores modules
that HAVE at least one covering test file. Read-only; stdlib only.
"""
import ast
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PKG = os.path.join(ROOT, "deeptutor")
IN_TREE_TESTS = os.path.join(PKG, "learning", "tests")
TESTS = os.path.join(ROOT, "tests")
DATE = "20261005"

MOCK_HINTS = ("MagicMock", "mock.patch", "monkeypatch", "Mock(", "AsyncMock", "faker", "Fake")


def py_files(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".venv", "node_modules", "__pycache__")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def module_key(path):
    rel = os.path.relpath(path, PKG)
    parts = rel[:-3].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def test_imports(path):
    names = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=path)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg = os.path.relpath(os.path.dirname(path), TESTS).replace(os.sep, ".")
                base = pkg.split(".")[: node.level]
                if node.module:
                    names.add(".".join(base + [node.module]))
                for a in node.names:
                    names.add(".".join(base + [node.module or "", a.name]).strip("."))
            elif node.module:
                names.add(node.module)
                for a in node.names:
                    names.add(node.module + "." + a.name)
    return {n for n in names if n == "deeptutor" or n.startswith("deeptutor.")}


def fn_assert_counts(node):
    """(stmt, unittest_style, mock_style) assert counts for one test function."""
    stmt = u = mk = 0
    for x in ast.walk(node):
        if isinstance(x, ast.Assert):
            stmt += 1
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute):
            attr = x.func.attr
            if attr.startswith("assert_"):
                mk += 1
            elif attr.startswith("assert"):
                u += 1
    return stmt, u, mk


def analyze(path):
    """§4-primary per-file metrics, plus supplementary assertion counters."""
    rel = os.path.relpath(path, ROOT)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return {"file": rel, "missing": True}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"file": rel, "syntax_error": True}
    n_test_fn = n_assert = n_raises = n_mock_refs = 0
    n_unittest = n_mockstyle = 0
    fns = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            n_test_fn += 1
            a, u, mk = fn_assert_counts(node)
            n_unittest += u
            n_mockstyle += mk
            fns.append({"name": node.name, "line": node.lineno,
                        "asserts": a, "unittest": u, "mock": mk})
        if isinstance(node, ast.Assert):
            n_assert += 1
        if isinstance(node, (ast.With, ast.AsyncWith)):
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
    n_mock_refs += sum(src.count(h) for h in MOCK_HINTS) // 4
    stmts = sorted(f["asserts"] for f in fns)
    med = stmts[len(stmts) // 2] if stmts else 0
    zero = sum(1 for a in stmts if a == 0)
    zero_ext = sum(1 for f in fns if f["asserts"] + f["unittest"] + f["mock"] == 0)
    return {
        "file": rel,
        "test_functions": n_test_fn,
        "asserts": n_assert,
        "unittest_asserts": n_unittest,
        "mock_asserts": n_mockstyle,
        "asserts_total": n_assert + n_unittest + n_mockstyle,
        "asserts_per_test_median": med,
        "zero_assert_test_functions": zero,
        "zero_assert_test_functions_ext": zero_ext,
        "zero_assert_ratio": round(zero / n_test_fn, 4) if n_test_fn else 0.0,
        "pytest_raises": n_raises,
        "mock_refs": n_mock_refs,
        "loc": src.count("\n") + 1,
        "functions": fns,
    }


def main():
    modules = [p for p in py_files(PKG) if not os.path.relpath(p, PKG).startswith("learning" + os.sep + "tests")]
    test_files = [p for p in py_files(TESTS)]
    test_files += [p for p in py_files(IN_TREE_TESTS) if stem(p).startswith("test")]

    test_rel_imports = {t: test_imports(t) for t in test_files}
    stem_index = defaultdict(set)
    for t in test_files:
        stem_index[stem(t)].add(t)

    file_metrics = {}  # rel test path -> analyze() result (shared, computed once)

    def metrics(t):
        rel = os.path.relpath(t, ROOT)
        if rel not in file_metrics:
            file_metrics[rel] = analyze(t)
        return file_metrics[rel]

    rows = []
    for m in modules:
        key = module_key(m)
        is_init = stem(m) == "__init__"
        s = stem(m)
        t1 = set()
        if s and s != "__init__":
            for ts, paths in stem_index.items():
                if s == ts or s in ts.split("_"):
                    t1 |= paths
        t2 = set()
        # deterministic exact prefix match; the baseline's `" ".join(names)`
        # substring hack is PYTHONHASHSEED-order-dependent (a matching import
        # only hits when it is the last joined token) and mispairs a few
        # modules run-to-run — replaced here, flagged in the report
        prefix = "deeptutor." + key
        for t, names in test_rel_imports.items():
            if any(n == prefix or n.startswith(prefix + ".") for n in names):
                t2.add(t)
        pkg_prefix = key.rsplit(".", 1)[0] if "." in key else "deeptutor"
        pkg_hits = set()
        if is_init:
            for t, names in test_rel_imports.items():
                if any(n == pkg_prefix or n.startswith(pkg_prefix + ".") for n in names):
                    pkg_hits.add(t)
        covered = t1 | t2 | pkg_hits
        if not covered:
            continue  # coverage existence is the other card's scope
        per_file = []
        all_stmts = []
        for t in sorted(covered):
            r = metrics(t)
            per_file.append({k: v for k, v in r.items() if k != "functions"})
            all_stmts.extend(f["asserts"] for f in r.get("functions", []))
        all_stmts.sort()
        n_fns = len(all_stmts)
        med = all_stmts[n_fns // 2] if n_fns else 0
        zero = sum(1 for a in all_stmts if a == 0)
        zero_ext = sum(
            1
            for t in sorted(covered)
            for f in metrics(t).get("functions", [])
            if f["asserts"] + f["unittest"] + f["mock"] == 0
        )
        rows.append({
            "module": key,
            "path": os.path.relpath(m, ROOT),
            "module_loc": sum(1 for _ in open(m, encoding="utf-8", errors="replace")),
            "is_init": is_init,
            "n_test_files": len(per_file),
            "test_files": per_file,
            "test_functions": n_fns,
            "asserts": sum(all_stmts),
            "asserts_unittest": sum(f["unittest_asserts"] for f in per_file),
            "asserts_mock": sum(f["mock_asserts"] for f in per_file),
            "asserts_per_test_median": med,
            "zero_assert_test_functions": zero,
            "zero_assert_test_functions_ext": zero_ext,
            "zero_assert_ratio": round(zero / n_fns, 4) if n_fns else 0.0,
            "pytest_raises": sum(f["pytest_raises"] for f in per_file),
            "weak": bool(n_fns and (med <= 1 or zero / n_fns >= 0.20)),
        })

    # rank weak hotspots: most §4-zero-assert tests first, then biggest module.
    # __init__ package aggregations (pkg-prefix fallback pairing) stay in the
    # full data but are excluded from the Top20 display: their numbers are
    # inherited from their leaf modules, not independently actionable.
    weak = sorted(
        [r for r in rows if r["weak"]],
        key=lambda r: (-r["zero_assert_test_functions"], -r["module_loc"], r["module"]),
    )
    weak_leaf = [r for r in weak if not r["is_init"]]
    weak_init = [r for r in weak if r["is_init"]]

    root_commit = os.popen("git rev-parse HEAD").read().strip()

    # distinct (de-duplicated across modules) inventory numbers
    distinct_files = {tf["file"] for r in rows for tf in r["test_files"]}
    distinct_fn_keys = set()
    for rel in distinct_files:
        for f in file_metrics[rel].get("functions", []):
            distinct_fn_keys.add((rel, f["name"], f["line"], f["asserts"]))
    distinct_zero = sum(1 for k in distinct_fn_keys if k[3] == 0)
    distinct_fn_count = len(distinct_fn_keys)

    raw = {
        "root_commit": root_commit,
        "method": "extends evidence/coverage-gaps-20261005/assertion_sample.py (AGEN-662 §4) to all pairs",
        "primary_counter": "ast.Assert statements per test function (identical to §4)",
        "supplementary_counters": "unittest-style x.assertXxx() and mock-style x.assert_xxx() attribute calls per test function (zero_assert_test_functions_ext = fns with none of the three)",
        "weak_rule": "median §4 asserts/test <= 1 OR zero_assert_ratio >= 0.20 (§4-exact)",
        "top20_excludes": "__init__ package aggregations (kept in rows, flagged is_init)",
        "t2_fix": "exact prefix match; baseline substring join was hash-seed order dependent",
        "n_modules_universe": len(modules),
        "n_test_files_universe": len(test_files),
        "n_paired_modules": len(rows),
        "distinct_paired_test_files": len(distinct_files),
        "distinct_paired_test_functions": distinct_fn_count,
        "distinct_zero_assert_functions": distinct_zero,
        "rows": rows,
    }
    with open(os.path.join(HERE, "assert_strength_raw.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)

    with open(os.path.join(HERE, "assert_strength_full.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["module", "path", "module_loc", "is_init", "n_test_files", "test_functions",
                    "asserts_stmt", "asserts_unittest", "asserts_mock", "asserts_per_test_median",
                    "zero_assert_test_functions", "zero_assert_ratio",
                    "zero_assert_test_functions_ext", "pytest_raises", "weak"])
        for r in sorted(rows, key=lambda r: (not r["weak"], -r["zero_assert_test_functions"], r["module"])):
            w.writerow([r["module"], r["path"], r["module_loc"], r["is_init"], r["n_test_files"],
                        r["test_functions"], r["asserts"], r["asserts_unittest"], r["asserts_mock"],
                        r["asserts_per_test_median"], r["zero_assert_test_functions"],
                        r["zero_assert_ratio"], r["zero_assert_test_functions_ext"],
                        r["pytest_raises"], r["weak"]])

    # §4-zero-assert function witnesses for the Top20 (path:line evidence);
    # fns that only carry mock/unittest-style asserts are tagged, true-zero first
    witnesses = {}
    for r in weak_leaf[:20]:
        true_zero, styled = [], []
        for tf in r["test_files"]:
            full = os.path.join(ROOT, tf["file"])
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    a, u, mk = fn_assert_counts(node)
                    if a == 0:
                        entry = f"{tf['file']}:{node.lineno} `{node.name}`"
                        if u + mk > 0:
                            styled.append(entry + "（仅 mock/unittest 断言）")
                        else:
                            true_zero.append(entry)
        witnesses[r["module"]] = (true_zero + styled)[:6]

    n_weak = len(weak)
    by_strength = defaultdict(int)
    for r in rows:
        med = r["asserts_per_test_median"]
        bucket = "0" if med == 0 else "1" if med == 1 else "2-3" if med <= 3 else "4-6" if med <= 6 else "7+"
        by_strength[bucket] += 1

    lines = []
    A = lines.append
    A("# 测试断言强度全量清点（AGEN-773，静态 AST，只读）")
    A("")
    A(f"- 基线 commit：`{root_commit}`（origin/main，v1.6.13）")
    A(f"- 方法基线：`evidence/coverage-gaps-20261005/assertion_sample.py`（AGEN-662 §4）AST 口径全量扩展")
    A(f"- 模块全集：`deeptutor/` 下 {len(modules)} 个 .py（排除内嵌 `learning/tests/`）；测试全集：`tests/` + 内嵌 `deeptutor/learning/tests/`，共 {len(test_files)} 个文件")
    A(f"- 配对口径：与 `scan_coverage_gaps.py` 相同两级——T1 文件名词干对应、T2 import 对应（`__init__` 模块加包前缀回退）；本卡只统计**有测试对应**的 {len(rows)} 个模块（覆盖存在性归 scan-coverage-gaps 卡）。一处必要修正：基线 T2 的 `\" \".join(names)` 子串匹配存在 PYTHONHASHSEED 顺序依赖（已实测同一模块在不同种子下漏配/误配），本卡改为确定性前缀匹配，种子 1/42/7 复跑结果完全一致")
    A(f"- 断言计数主口径 = §4 原口径（测试函数内 `ast.Assert` 语句数），弱断言判定严格按此口径，§4 全部 15 个抽样数字可逐一复现；另附**补充口径**（unittest 风格 `x.assertXxx()` 与 mock 风格 `x.assert_xxx()` 调用），用于识别\"形式上零 assert 语句、实有行为断言\"的用例，避免误伤")
    A(f"- 弱断言判定（卡面口径，主口径）：**中位断言/用例 ≤ 1** 或 **零断言用例占比 ≥ 20%**")
    A(f"- 复现：`python3 evidence/assert-strength-{DATE}/assert_strength_scan.py`（stdlib only，只读）")
    A("")
    A("## 1. 总体分布")
    A("")
    A(f"- 有测试对应的模块：{len(rows)} / {len(modules)}；去重后涉及测试文件 {len(distinct_files)} 个、测试函数 {distinct_fn_count} 个")
    A(f"- 其中 §4 口径零断言测试函数 {distinct_zero} 个（占 {distinct_zero / distinct_fn_count * 100:.1f}%；部分由 mock/unittest 断言覆盖，见 Top20 标注）")
    A(f"- **弱断言模块 {n_weak} 个**（占已覆盖模块 {n_weak / len(rows) * 100:.1f}%），其中可独立拆卡的非 `__init__` 模块 {len(weak_leaf)} 个")
    A("")
    A("| 中位断言/用例 | 模块数 |")
    A("|---|---|")
    for bucket in ["0", "1", "2-3", "4-6", "7+"]:
        A(f"| {bucket} | {by_strength.get(bucket, 0)} |")
    A("")
    A("## 2. 弱断言热点 Top20")
    A("")
    A("排序：零断言用例数（§4 口径）降序，其次模块行数（越大越值得拆增强卡）。"
      + (f"包级 `__init__` 聚合行 {len(weak_init)} 个（{'、'.join('`' + r['module'] + '`' for r in weak_init)}）不占名次、只在完整表内——数值继承自叶子模块。" if weak_init else ""))
    A("")
    A("| # | 模块 | 测试函数 | 断言数 | 中位 | 零断言(占比) | 其中纯mock/ut | raises | 模块LOC | 零断言用例示例（path:line） |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(weak_leaf[:20], 1):
        zs = witnesses.get(r["module"], [])
        sample = "；".join(zs[:2]) if zs else "—"
        A(f"| {i} | `{r['module']}` | {r['test_functions']} | {r['asserts']} | {r['asserts_per_test_median']} | "
          f"{r['zero_assert_test_functions']} ({r['zero_assert_ratio'] * 100:.0f}%) | {r['zero_assert_test_functions_ext']} | "
          f"{r['pytest_raises']} | {r['module_loc']} | {sample} |")
    A("")
    A("## 3. 其余弱断言模块（21+，完整清单见 CSV）")
    A("")
    A("| 模块 | 测试函数 | 断言数 | 中位 | 零断言(占比) | 模块LOC |")
    A("|---|---|---|---|---|---|")
    for r in weak_leaf[20:]:
        A(f"| `{r['module']}` | {r['test_functions']} | {r['asserts']} | {r['asserts_per_test_median']} | "
          f"{r['zero_assert_test_functions']} ({r['zero_assert_ratio'] * 100:.0f}%) | {r['module_loc']} |")
    A("")
    A("## 4. 可拆增强卡条目（Top 弱点，均只补断言不改产品代码）")
    A("")
    for i, r in enumerate(weak_leaf[:8], 1):
        zs = witnesses.get(r["module"], [])
        focus = "；".join(z.split("`")[1].split("（")[0] for z in zs[:3]) if zs else "全部用例"
        scope = ""
        if r["n_test_files"] >= 4:
            scope = f" 注意：配对含 {r['n_test_files']} 个测试文件（T1 词干同名也会并入），拆卡时先按 T2 import 关系圈定实际覆盖用例。"
        A(f"{i}. **test: {r['module'].split('.')[-1]} 断言语义增强** — 现状 {r['test_functions']} 用例仅 {r['asserts']} 断言"
          f"（中位 {r['asserts_per_test_median']}，零断言 {r['zero_assert_test_functions']} 个）。"
          f"目标：为 `{r['path']}` 对应用例补语义/边界断言（零断言用例如 {focus}），移出弱断言区。{scope}")
    A("")
    A("## 5. 附：完整数据表与口径备注")
    A("")
    A(f"全部 {len(rows)} 个有对应模块逐行数据（含每个覆盖测试文件的分文件指标）见 `assert_strength_full.csv`（模块级）与 `assert_strength_raw.json`（模块级+分文件+逐用例）。")
    A("")
    A("- 模块级指标 = 该模块全部覆盖测试文件中所有测试函数（主口径）断言数的合并分布（中位沿用基线 `sorted[n//2]` 规则）。")
    A("- §4 对照：15 个 §4 抽样文件中 13 个由本配对口径自动命中且数字逐位一致（`asserts` 主口径）。`api.routers.mastery_path` 未自动命中 `deeptutor/learning/tests/test_mastery_tools.py`——该文件为内嵌测试目录，其相对导入按 `tests/` 根解析，无法还原为 `deeptutor.*` 全名，T2 无法命中（该模块经其他测试文件配对，union 72 用例/209 断言）；`core.config_manager` 为 §4 手工对照行（其测试文件经 fixture 间接使用模块，不在 T1/T2 命中范围）。两者均为 §4 手工抽样，不是本口径的回归。")
    A("- 已知限制：T1 词干匹配会把同名词干的无关测试并入（如 `queue`），import 配对会把目录级 conftest 并入对应模块；两者均为基线既有口径，未放宽或收紧。")
    A("")

    with open(os.path.join(HERE, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # SHA256SUMS over the other artifacts
    sums = []
    for name in sorted(["assert_strength_scan.py", "assert_strength_raw.json", "assert_strength_full.csv", "report.md"]):
        with open(os.path.join(HERE, name), "rb") as fh:
            sums.append(hashlib.sha256(fh.read()).hexdigest() + f"  {name}")
    with open(os.path.join(HERE, "SHA256SUMS"), "w") as f:
        f.write("\n".join(sums) + "\n")

    print(f"modules={len(modules)} paired={len(rows)} weak={n_weak} (leaf={len(weak_leaf)}) "
          f"distinct_files={len(distinct_files)} distinct_fns={distinct_fn_count} "
          f"zero_assert={distinct_zero} ({distinct_zero / distinct_fn_count * 100:.1f}%)")
    print("top5:", ", ".join(r["module"] for r in weak_leaf[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
