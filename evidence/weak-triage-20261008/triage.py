#!/usr/bin/env python3
"""Rank weak_single_test modules (AGEN-1154 triage) into top100 retest seeds.

Inputs (read-only):
  ../coverage-gaps-20261007/coverage_raw.json, summary.json  (scan @ f07029cf)
  scan tree of deeptutor/ at f07029cf (git archive extraction path, --tree)

Reproduces aggregate.py semantics (intree test coverage + import fan-in),
asserts consistency with summary.json, then ranks the 242 weak modules:

  score   = fanin*10 + min(loc,500)//50 + bonus*15
  bonus   = 2  user-facing route / startup / runtime core
               (deeptutor/api/routers/*, api.run_server,
                services.config.readiness, runtime.*)
          = 1  pipeline / delivery plane (partners, llm, rag, embedding,
               parsing, voice, imagegen, tools, workspace, memory, search,
               subagent, multi_user, learning, co_writer, book,
               capabilities, video_learning, api.*)
          = 0  otherwise
  risk    = 高: fanin>=5 or bonus==2
            中: fanin 2-4 or loc>=300 or bonus==1
            低: otherwise
  order   = (-score, -loc, -fanin, module)

DONE cards: manual review of project issue board on 2026-10-08 (see triage.md
dedup section); mapping embedded below.
"""
import ast
import json
import os
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "coverage-gaps-20261007", "coverage_raw.json")
SUMMARY = os.path.join(HERE, "..", "coverage-gaps-20261007", "summary.json")
SCAN_COMMIT = "f07029cfcf2c8dfccdb671cdfc343db8334f5741"
REPO = "/Users/Shared/DeepTutor"

TIER2_PREFIXES = ("deeptutor/api/routers/",)
TIER2_MODULES = {"deeptutor.api.run_server", "deeptutor.services.config.readiness"}
TIER2_TOP = ("runtime",)
TIER1_PREFIXES = (
    "deeptutor/partners/", "deeptutor/services/llm/", "deeptutor/services/rag/",
    "deeptutor/services/embedding/", "deeptutor/services/parsing/",
    "deeptutor/services/voice/", "deeptutor/services/imagegen/",
    "deeptutor/tools/", "deeptutor/services/workspace/",
    "deeptutor/services/memory/", "deeptutor/services/search/",
    "deeptutor/services/subagent/", "deeptutor/multi_user/",
    "deeptutor/learning/", "deeptutor/co_writer/", "deeptutor/book/",
    "deeptutor/capabilities/", "deeptutor/video_learning/", "deeptutor/api/",
)
TIER1_TOP = ("partners", "multi_user", "learning", "co_writer", "book",
             "capabilities", "video_learning", "tools")

DONE = {
    "agents.loop.context_budget": ("AGEN-1053",),
    "api.contracts.turn_protocol": ("AGEN-1147",),
    "api.routers.file_preview": ("AGEN-764",),
    "api.routers.mcp_settings": ("AGEN-832",),
    "api.routers.partner_groups": ("AGEN-763",),
    "api.routers.question_notebook": ("AGEN-838",),
    "api.routers.space_cli_apps": ("AGEN-833",),
    "api.routers.space_mcp": ("AGEN-780",),
    "api.run_server": ("AGEN-1060",),
    "book.agents.page_planner": ("AGEN-966",),
    "capabilities.mastery.choices": ("AGEN-1151",),
    "capabilities.obsidian.vault": ("AGEN-807",),
    "co_writer.edit_agent": ("AGEN-751",),
    "learning.topic_generation": ("AGEN-1139",),
    "learning.topic_materials": ("AGEN-1140",),
    "learning.assessment": ("AGEN-1050",),
    "learning.grading": ("AGEN-1035",),
    "learning.objective_relations": ("AGEN-1133",),
    "learning.pending": ("AGEN-793",),
    "learning.topic_naming": ("AGEN-1135",),
    "multi_user.book_access": ("AGEN-828",),
    "partners.channels.lark_http": ("AGEN-736",),
    "partners.channels.matrix": ("AGEN-743",),
    "partners.channels.msteams": ("AGEN-741", "AGEN-947"),
    "partners.channels.napcat": ("AGEN-742", "AGEN-947"),
    "partners.channels.wecom": ("AGEN-1051",),
    "runtime.background_leader": ("AGEN-863",),
    "services.chat_hints": ("AGEN-993",),
    "services.config.readiness": ("AGEN-787",),
    "services.doctor": ("AGEN-914",),
    "services.embedding.adapters.dashscope_native": ("AGEN-913",),
    "services.embedding.adapters.gemini": ("AGEN-913",),
    "services.generation_http": ("AGEN-1010",),
    "services.llm.error_mapping": ("AGEN-1036",),
    "services.llm.local_provider": ("AGEN-847",),
    "services.memory.consolidator.line_doc": ("AGEN-1141",),
    "services.memory.consolidator.modes.audit": ("AGEN-782",),
    "services.office_preview": ("AGEN-790",),
    "services.parsing.engines._install": ("AGEN-915",),
    "services.partners.weixin_onboarding": ("AGEN-808",),
    "services.rag.eval.dataset": ("AGEN-912",),
    "services.rag.eval.matching": ("AGEN-912",),
    "services.rag.pipelines.lightrag.sidecar": ("AGEN-811",),
    "services.rag.provider_binding": ("AGEN-824",),
    "services.reading_hints": ("AGEN-745",),
    "services.search.consolidation": ("AGEN-1052",),
    "services.search.source_filter": ("AGEN-974",),
    "services.skill.taxonomy": ("AGEN-813",),
    "services.subagent.claude_code": ("AGEN-1142",),
    "services.subagent.deepseek_harness": ("AGEN-1143",),
    "services.subagent.opencode_server": ("AGEN-845",),
    "services.voice.adapters.openai_compat": ("AGEN-1056",),
    "services.voice.adapters.volcengine": ("AGEN-916",),
    "services.workspace.dependencies": ("AGEN-1144",),
    "services.workspace.kb_move": ("AGEN-976",),
    "services.workspace.session_transfer": ("AGEN-831",),
    "tools.mastery_nav": ("AGEN-973",),
    "tools.media_gen_tool": ("AGEN-1086",),
    "tools.partner_memory": ("AGEN-1145",),
    "tools.question_bank": ("AGEN-972",),
    "tools.reason": ("AGEN-849",),
    "tools.vision.ggb_validator": ("AGEN-977",),
    "video_learning.invidious_account": ("AGEN-806",),
}


def scan_tree(tmp_root):
    dest = os.path.join(tmp_root, "scan-tree")
    if not os.path.isdir(dest):
        os.makedirs(dest)
        r = subprocess.run(["git", "-C", REPO, "archive", SCAN_COMMIT, "deeptutor"],
                           capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", dest], input=r.stdout, check=True)
    return os.path.join(dest, "deeptutor")


def module_key(rel_py):
    parts = rel_py[:-3].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def parsed(path):
    try:
        return ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return None


def import_names(tree):
    """intree-test style: absolute imports only (relative ignored)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {node.module + "." + a.name for a in node.names}
    return names


def main():
    tmp_root = sys.argv[1]
    raw = json.load(open(RAW))
    summary = json.load(open(SUMMARY))
    pkg_root = scan_tree(tmp_root)

    mods = [m for m in raw["modules"]
            if not os.path.basename(m["path"]).startswith("test_")]
    intree = [m for m in raw["modules"]
              if os.path.basename(m["path"]).startswith("test_")]

    # intree test -> imported deeptutor names (same as aggregate.py)
    intree_imports = {}
    for t in intree:
        tree = parsed(os.path.join(pkg_root, "..", t["path"]))
        names = import_names(tree) if tree else set()
        intree_imports[t["module"]] = {n for n in names
                                       if n == "deeptutor" or n.startswith("deeptutor.")}

    # fan-in: literal port of aggregate.py (importer spelling kept as-is so a
    # module both `import`-ed and `from`-import-ed by the same file counts
    # twice, exactly as in the summary we reproduce)
    fanin = defaultdict(set)
    for dirpath, dirnames, filenames in os.walk(pkg_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, pkg_root)[:-3].split(os.sep)
            is_init = rel[-1] == "__init__"
            if is_init:
                rel = rel[:-1]
            src = ".".join(rel)
            pkg_parts = rel if is_init else rel[:-1]
            tree = parsed(p)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.startswith("deeptutor.") and a.name != src:
                            fanin[a.name].add(src)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                        mod = ".".join(["deeptutor"] + base + ([node.module] if node.module else []))
                    else:
                        mod = node.module or ""
                    if mod.startswith("deeptutor.") and mod != "deeptutor." + src:
                        fanin[mod].add("deeptutor." + src)
                        for a in node.names:
                            full = mod + "." + a.name
                            if full != "deeptutor." + src:
                                fanin[full].add("deeptutor." + src)

    by_key = {m["module"]: m for m in mods}
    intree_cover = defaultdict(set)
    for tmod, names in intree_imports.items():
        for n in names:
            bare = n[len("deeptutor."):] if n.startswith("deeptutor.") else n
            if bare in by_key:
                intree_cover[bare].add(tmod)

    def f(m):
        return len(fanin.get("deeptutor." + m["module"], ()))

    # reproduce aggregate decisions
    zero, weak = [], []
    for m in mods:
        m["intree_tests"] = sorted(intree_cover.get(m["module"], ()))
        if m["is_init"]:
            continue
        if m["n_cover"] == 0 and not m["intree_tests"]:
            zero.append(m)
        elif m["n_cover"] + len(m["intree_tests"]) == 1:
            weak.append(m)

    zero.sort(key=lambda m: (-m["loc"], -f(m)))
    weak.sort(key=lambda m: -m["loc"])

    t = summary["totals"]
    assert len(weak) == t["weak_single_test"] == 242, (len(weak), t)
    assert len(zero) == t["zero_noninit"], (len(zero), t)
    assert [m["module"] for m in weak[:100]] == [w["module"] for w in summary["weak_top100"]]
    for w, s in zip(weak[:100], summary["weak_top100"]):
        assert (m_loc_fanin := (w["loc"], f(w))) == (s["loc"], s["fanin"]), (w["module"], m_loc_fanin, s)
    assert [(x[0], x[1]) for x in summary["fanin_top50"][:50]] == \
           sorted(((k, len(v)) for k, v in fanin.items()), key=lambda x: -x[1])[:50]
    assert [(z["module"], z["loc"]) for z in zero[:200]] == \
           [(z["module"], z["loc"]) for z in summary["zero_top200"]]

    # drift vs current origin/main (HEAD 6cf793bd v1.6.14)
    drift = set(subprocess.run(
        ["git", "-C", REPO, "diff", "--name-only", SCAN_COMMIT, "origin/main", "--", "deeptutor"],
        capture_output=True, text=True, check=True).stdout.split())

    rows = []
    for m in weak:
        path = m["path"]
        bonus = 2 if (path.startswith(TIER2_PREFIXES) or m["module"] in TIER2_MODULES
                      or m["module"].split(".")[0] in TIER2_TOP) else 0
        if not bonus and (path.startswith(TIER1_PREFIXES)
                          or m["module"].split(".")[0] in TIER1_TOP):
            bonus = 1
        score = f(m) * 10 + min(m["loc"], 500) // 50 + bonus * 15
        if f(m) >= 5 or bonus == 2:
            risk = "高"
        elif f(m) >= 2 or m["loc"] >= 300 or bonus == 1:
            risk = "中"
        else:
            risk = "低"

        src = os.path.join(pkg_root, path[len("deeptutor/"):])
        doc, defs = "", []
        try:
            tree = ast.parse(open(src, encoding="utf-8", errors="replace").read())
            d = ast.get_docstring(tree)
            if d:
                doc = d.strip().splitlines()[0].strip()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not node.name.startswith("_"):
                        defs.append(node.name)
        except (SyntaxError, OSError):
            pass
        defs = defs[:4]

        if path.startswith("deeptutor/api/routers/"):
            tail = "＋失败/4xx 分支"
        elif m["module"] in TIER2_MODULES or m["module"].split(".")[0] in TIER2_TOP:
            tail = "＋启动/装配失败路径"
        elif path.startswith(("deeptutor/partners/", "deeptutor/services/llm/",
                              "deeptutor/services/embedding/", "deeptutor/services/voice/",
                              "deeptutor/services/imagegen/")):
            tail = "＋超时/限流/畸形响应分支"
        else:
            tail = "＋异常/降级分支"
        if defs:
            focus = "覆盖 " + "/".join(defs) + " 契约与边界" + tail
        else:
            focus = "模块级冒烟：import 副作用与导出契约" + tail
        if doc:
            words = doc[:44].split(" ")
            words = words[:-1] if len(doc) > 44 and len(words) > 1 else words
            doc = " ".join(words).rstrip("，。;；,")
            focus = f"「{doc}」" + focus

        keys = DONE.get(m["module"])
        rows.append({
            "module": m["module"], "path": path, "loc": m["loc"], "fanin": f(m),
            "bonus": bonus, "score": score, "risk": risk, "focus": focus,
            "done": keys, "drift": path in drift,
        })

    rows.sort(key=lambda r: (-r["score"], -r["loc"], -r["fanin"], r["module"]))

    def esc(s):
        return s.replace("|", "/").replace("\n", " ")

    done_rows = [r for r in rows if r["done"]]
    key2mods = {}
    for r in done_rows:
        for k in r["done"]:
            key2mods.setdefault(k, []).append(r["module"])
    drift100 = sum(1 for r in rows[:100] if r["drift"])

    L = []
    L.append("# weak_single_test top100 补测种子 triage（20261008）")
    L.append("")
    L.append("## 输入与边界")
    L.append("- 扫描证据：`evidence/coverage-gaps-20261007/{coverage_raw,summary}.json`（myfork `scan/coverage-gaps-20261007`，root_commit `f07029cf` = v1.6.13），只读")
    L.append("- weak 定义（复现 aggregate.py）：非 `__init__`、非 `test_*` 模块，`tests/` 触达数 + in-tree（`deeptutor/**/tests/test_*`）触达数 == 1，共 242 个")
    L.append("- 本卡只做 triage：不改任何产品代码/测试；`⚠` = 该文件在 `f07029cf..origin/main`（6cf793bd，v1.6.14）间有改动，拆卡前需在 origin/main 复核职责")
    L.append("")
    L.append("## 排序口径（可复算）")
    L.append("- 复算：`python3 triage.py <临时目录>`，脚本内断言 fanin/weak_top100/zero_top200 与 summary.json 完全一致后才输出")
    L.append("- `score = fanin×10 + min(LOC,500)÷50（整除） + bonus×15`；并列按 LOC↓、fanin↓、模块名字典序")
    L.append("- `fanin` = 包内静态 import 反向依赖模块数（与 summary.json 同一口径，含其 importer 拼写特性）")
    L.append("- `bonus`：2=用户面路由/启动/runtime 核心（`api/routers/*`、`api.run_server`、`services.config.readiness`、`runtime.*`）；1=管线/交付面（partners、llm、rag、embedding、parsing、voice、imagegen、tools、workspace、memory、search、subagent、multi_user、learning、co_writer、book、capabilities、video_learning、api.*）；0=其他")
    L.append("- `风险`：高=fanin≥5 或 bonus=2；中=fanin 2-4 或 LOC≥300 或 bonus=1；低=其余")
    L.append("")
    L.append("## 去重口径")
    L.append("- DONE 映射：2026-10-08 人工核对项目卡（`test:` 前缀卡标题/描述与模块 path、dotted 名、目录片段、词干逐一匹配并复核描述目标文件），weak242 内已建卡 %d 个（top100 内 %d 个）" % (len(done_rows), sum(1 for r in rows[:100] if r["done"])))
    L.append("- 建卡但已不属 weak242 的 3 个模块：`capabilities.mastery.choices`(AGEN-1151)、`learning.topic_generation`(AGEN-1139)、`learning.topic_materials`(AGEN-1140)——已被 in-tree 测试触达（触发数=2）")
    L.append("- AGEN-1064/967 的目标是 `services/parsing/engines/formats.py`（顶层分派，zero 表）；各引擎子目录 `formats.py`（markitdown/docling/…）不在其范围，本表仍列为待拆")
    L.append("")
    L.append("## top100")
    L.append("| # | 模块 | path | LOC | fanin | score | 风险 | 建议测试焦点 | 状态 |")
    L.append("|---|------|------|----:|------:|------:|------|--------------|------|")
    for i, r in enumerate(rows[:100], 1):
        status = ("DONE(" + "+".join(r["done"]) + ")") if r["done"] else "TODO" + ("⚠" if r["drift"] else "")
        L.append("| %d | `%s` | `%s` | %d | %d | %d | %s | %s | %s |" % (
            i, r["module"], r["path"], r["loc"], r["fanin"], r["score"],
            r["risk"], esc(r["focus"]), status))
    L.append("")
    L.append("## 已建卡索引（weak242 内全部 DONE）")
    for k in sorted(key2mods):
        L.append("- %s: %s" % (k, ", ".join("`%s`" % m for m in key2mods[k])))
    L.append("")
    L.append("## 附注")
    L.append("- 焦点文本 = 模块 docstring 首行 + 顶层公开 def/class（≤4 个）自动生成，按 bonus 类别追加失败分支轴；拆卡时按需细化")
    L.append("- top100 中 ⚠ 漂移 %d 个；计数：高 %d / 中 %d / 低 %d" % (
        drift100,
        sum(1 for r in rows[:100] if r["risk"] == "高"),
        sum(1 for r in rows[:100] if r["risk"] == "中"),
        sum(1 for r in rows[:100] if r["risk"] == "低")))
    out = os.path.join(HERE, "triage.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote", out, len(L), "lines")

    json.dump({"rows": rows, "n_weak": len(weak)},
              open(os.path.join(tmp_root, "rows.json"), "w"), ensure_ascii=False, indent=1)
    print("weak:", len(weak), "top100 first:", rows[0]["module"], rows[0]["score"],
          "| last:", rows[99]["module"], rows[99]["score"],
          "| done in weak:", len(done_rows),
          "| drift in top100:", drift100)


if __name__ == "__main__":
    main()
