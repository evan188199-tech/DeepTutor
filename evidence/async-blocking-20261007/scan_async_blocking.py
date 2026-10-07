#!/usr/bin/env python3
"""AGEN-998: 静态扫描 async 函数内的阻塞调用（事件循环饥饿风险清点）。

只读 AST 分析，不修改任何被扫描文件。

用法:
    python3 scan_async_blocking.py [根目录] [--out hits.json]
默认根目录 `deeptutor/`。JSON 明细写入 --out（默认与脚本同目录 data.json），
人读摘要输出到 stderr。

判定范围（阻塞轴，其他扫描卡的正交轴只做去重标注）:
  - sleep_sync          time.sleep
  - http_sync           requests / httpx 同步 API / urllib / http.client
  - subprocess_sync     subprocess.run 族 / os.system / Popen.wait/communicate
  - socket_sync         socket.create_connection 及阻塞 socket 方法
  - nested_event_loop   async 内 asyncio.run / loop.run_until_complete
  - thread/queue/event/future 原语阻塞   Thread.join / Queue.get / Event.wait / Future.result
  - file_sync           内建 open、os/shutil 文件操作、Path 读写
  - db_sync             sqlite3 同步驱动
  - cpu_loop / cpu_call 重 CPU 循环与重调用（启发式，标注需人工复核）

去重约定:
  - 锁轴（scan-lock-usage / AGEN-665）: lock.acquire 等锁原语不进主命中表，
    单独记入 lock_axis_overlap 供交叉引用。
  - 超时轴（scan-http-clients / AGEN-578）: http 命中仅判阻塞本质，不判超时配置。
  - 测试时序轴（scan-flaky-tests）: tests/ 路径命中加标注。
  - fire-and-forget 轴（scan-async-tasks / AGEN-453）: 正交，报告层说明。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- call naming

EXPR = "<expr>"


def call_full_name(node: ast.Call, imports: dict) -> str | None:
    """返回点分调用名；根为普通表达式时折叠为 <expr>。经 import 别名归一。"""
    parts: list[str] = []
    cur = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        head = cur.id
    elif isinstance(cur, ast.Call):
        inner = call_full_name(cur, imports)
        if inner is None:
            return None
        head = inner
    else:
        if not parts:
            return None
        head = EXPR
    parts.append(head)
    parts.reverse()
    raw = ".".join(parts)
    head, _, rest = raw.partition(".")
    if head in imports:
        resolved = imports[head] + (("." + rest) if rest else "")
    else:
        resolved = raw
    return resolved


def build_import_map(tree: ast.Module) -> dict:
    imports: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                local = (a.asname or a.name).split(".")[0]
                imports[local] = a.name if a.asname else local
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for a in node.names:
                if a.name == "*":
                    continue
                imports[a.asname or a.name] = f"{node.module}.{a.name}"
    return imports


# ---------------------------------------------------------------- specs

RESOLVED_SPECS = [
    # (regex, category, risk, confidence, fixed-label-or-None)
    (r"^time\.sleep$", "sleep_sync", "high", "certain", None),
    (r"^requests\.(get|post|put|patch|delete|head|options|request)$", "http_sync", "high", "certain", None),
    (r"^httpx\.(get|post|put|patch|delete|head|options|request|stream)$", "http_sync", "high", "certain", None),
    (r"^urllib\.request\.urlopen$", "http_sync", "high", "certain", None),
    (r"^http\.client\.(HTTPConnection|HTTPSConnection)$", "http_sync", "high", "certain", None),
    (r"^socket\.create_connection$", "socket_sync", "high", "certain", None),
    (r"^socket\.socket$", "socket_sync", "low", "certain", "socket 创建本身（connect/recv 才是真阻塞）"),
    (r"^subprocess\.(run|call|check_call|check_output)$", "subprocess_sync", "high", "certain", None),
    (r"^os\.(system|popen)$", "subprocess_sync", "high", "certain", None),
    (r"^subprocess\.Popen$", "subprocess_sync", "low", "certain",
     "Popen 创建含 fork/exec 开销；真正的阻塞在 .wait/.communicate"),
    (r"^asyncio\.run$", "nested_event_loop", "high", "certain", None),
    (r"\.run_until_complete$", "nested_event_loop", "high", "heuristic", None),
    (r"^queue\.Queue\.get$", "queue_blocking", "high", "certain", "queue.Queue.get 阻塞取"),
    (r"^threading\.Event\.wait$", "event_wait", "high", "certain", None),
    (r"^threading\.Thread\.join$", "thread_join", "high", "certain", None),
    (r"^(concurrent\.futures\.)?(Future|ThreadPoolExecutor|ProcessPoolExecutor)\.result$",
     "future_result", "high", "heuristic", None),
    (r"^input$", "input_blocking", "high", "certain", None),
    # file IO
    (r"^open$", "file_sync", "med", "certain", "内建 open()"),
    (r"^os\.(walk|listdir|scandir|mkdir|makedirs|remove|unlink|rename|replace|rmdir|truncate|chmod|chown|symlink|link)$",
     "file_sync", "med", "certain", None),
    (r"^os\.(stat|lstat|getsize)$", "file_sync", "low", "certain", None),
    (r"^os\.path\.(exists|isfile|isdir|getmtime|getsize|getctime|getatime)$", "file_sync", "low", "certain", None),
    (r"^shutil\.(copy|copy2|copyfile|copytree|rmtree|move|make_archive|unpack_archive)$", "file_sync", "med", "certain", None),
    (r"^shutil\.which$", "file_sync", "low", "certain", None),
    (r"^(pathlib\.)?Path\.(read_text|read_bytes|write_text|write_bytes|open)$", "file_sync", "med", "certain", None),
    (r"^(pathlib\.)?Path\.(unlink|mkdir|stat|iterdir|glob|touch)$", "file_sync", "low", "certain", None),
    (r"^(pathlib\.)?Path\.(rename|replace|rglob)$", "file_sync", "med", "certain", None),
    # db
    (r"^sqlite3\.connect$", "db_sync", "low", "certain", "连接创建（后续 .execute 才是阻塞点）"),
    (r"^sqlite3\.connect\.(execute|executemany|executescript|commit|rollback)$", "db_sync", "med", "certain", None),
    # cpu direct calls
    (r"^(torch|numpy|np|pandas|pd|sklearn|cv2)\.(load|save|read_csv|read_json|read_parquet|read_excel|fromarray|tensor|imread|imwrite)$",
     "cpu_call", "med", "heuristic", None),
    (r"^copy\.deepcopy$", "cpu_call", "med", "heuristic", "deepcopy 开销随对象规模，需人工确认量级"),
    (r"^(fitz|pdfplumber|pymupdf)\.open$", "cpu_call", "med", "heuristic", "PDF 解析为重 CPU 操作"),
]

CTOR_TAGS = [
    (r"^threading\.Thread$", "thread"),
    (r"^queue\.Queue$", "queue"),
    (r"\.submit$", "future"),
    (r"^concurrent\.futures\.(ThreadPoolExecutor|ProcessPoolExecutor)$", "future"),
    (r"^threading\.Event$", "event"),
    (r"^subprocess\.Popen$", "popen"),
    (r"^sqlite3\.connect$", "sqlite"),
    (r"^(socket\.socket|socket\.create_connection)$", "socket"),
    (r"^(pathlib\.)?Path$", "path"),
    (r"^asyncio\.(get_event_loop|new_event_loop|get_running_loop)$", "loop"),
    (r"^PIL\.Image\.open$", "img"),
    (r"^requests\.Session$", "reqsession"),
    (r"^httpx\.Client$", "httpxclient"),
    (r"^threading\.(Lock|RLock|Semaphore|BoundedSemaphore)$", "lock"),
    (r"^asyncio\.(Lock|Semaphore|Event|Condition)$", "alock"),
]

RECV_METHODS = {
    "thread": {"join": ("thread_join", "high")},
    "queue": {"get": ("queue_blocking", "high")},
    "future": {"result": ("future_result", "high")},
    "event": {"wait": ("event_wait", "high")},
    "popen": {"wait": ("subprocess_sync", "high"), "communicate": ("subprocess_sync", "high")},
    "sqlite": {"execute": ("db_sync", "med"), "executemany": ("db_sync", "med"),
               "executescript": ("db_sync", "med"), "commit": ("db_sync", "med"),
               "rollback": ("db_sync", "med")},
    "socket": {"connect": ("socket_sync", "high"), "recv": ("socket_sync", "high"),
               "sendall": ("socket_sync", "high"), "send": ("socket_sync", "high"),
               "accept": ("socket_sync", "high")},
    "path": {"read_text": ("file_sync", "med"), "read_bytes": ("file_sync", "med"),
             "write_text": ("file_sync", "med"), "write_bytes": ("file_sync", "med"),
             "open": ("file_sync", "med"), "unlink": ("file_sync", "low"),
             "mkdir": ("file_sync", "low"), "stat": ("file_sync", "low"),
             "iterdir": ("file_sync", "low"), "glob": ("file_sync", "low"),
             "rglob": ("file_sync", "med"), "rename": ("file_sync", "med"),
             "replace": ("file_sync", "med")},
    "loop": {"run_until_complete": ("nested_event_loop", "high")},
    "img": {"load": ("cpu_call", "med"), "resize": ("cpu_call", "med"),
            "thumbnail": ("cpu_call", "med"), "convert": ("cpu_call", "low")},
    "reqsession": {"get": ("http_sync", "high"), "post": ("http_sync", "high"),
                   "put": ("http_sync", "high"), "patch": ("http_sync", "high"),
                   "delete": ("http_sync", "high"), "head": ("http_sync", "high"),
                   "options": ("http_sync", "high"), "request": ("http_sync", "high"),
                   "send": ("http_sync", "high")},
    "httpxclient": {"get": ("http_sync", "high"), "post": ("http_sync", "high"),
                    "put": ("http_sync", "high"), "patch": ("http_sync", "high"),
                    "delete": ("http_sync", "high"), "head": ("http_sync", "high"),
                    "options": ("http_sync", "high"), "request": ("http_sync", "high"),
                    "stream": ("http_sync", "high"), "send": ("http_sync", "high")},
}

# 锁轴去重：不进主命中表
LOCK_RECV = {"lock": {"acquire"}, "alock": {"acquire", "wait"}}

HEAVY_CORE_RE = re.compile(
    r"(^(hashlib|zlib|gzip|lzma|bz2)\.)"
    r"|(^|\.)(torch|numpy|np|pandas|pd|sklearn|scipy|cv2|fitz|pdfplumber)\."
    r"|(^|_)(embed|tokenize|vectorize|ocr|transcribe)(_|$|\.)"
    r"|(^|\.)(render|build_index|search_index|compute_)"
)
HEAVY_MILD_RE = re.compile(
    r"^(re\.(findall|finditer|sub|split)|json\.(dumps|loads)|orjson\.(dumps|loads)|base64\.)"
)

OFFLOAD_RE = re.compile(
    r"^(asyncio\.to_thread|anyio\.to_thread|anyio\.to_process\.run_sync|.*run_in_executor|.*\.submit)$"
)

RISK_ORDER = {"high": 0, "med": 1, "medium": 1, "low": 2}

GENERIC_FILE_METHODS = {"read_text", "read_bytes", "write_text", "write_bytes"}

ATTR_FALLBACK = {
    "join": r"(^|_)(thread|thr|worker|proc|process|reader|writer|piper)($|_|\d)",
    "result": r"(^|_)(fut|future)($|_|\d)",
    "communicate": r"(^|_)(proc|process|popen|sub)($|_|\d)",
}


def thread_target_names(fn_node: ast.AST, imports: dict) -> set[str]:
    """收集被当作线程/卸载目标引用的函数名（Thread(target=) / submit / to_thread / run_in_executor）。"""
    names: set[str] = set()
    for n in collect_scope_nodes(fn_node):
        if not isinstance(n, ast.Call):
            continue
        full = call_full_name(n, imports) or ""
        tail = full.rsplit(".", 1)[-1]
        if tail == "Thread" or full in {"asyncio.to_thread", "anyio.to_thread"} or tail in {"submit", "run_in_executor"}:
            for kw in n.keywords:
                if kw.arg == "target" and isinstance(kw.value, ast.Name):
                    names.add(kw.value.id)
            args = n.args[1:] if tail == "run_in_executor" else n.args
            for a in args:
                if isinstance(a, ast.Name):
                    names.add(a.id)
    return names


def direct_nested_defs(fn_node: ast.AST) -> list[ast.FunctionDef]:
    """fn 子树里「最近的 enclosing 函数是 fn_node 自身」的同步 def。"""
    out: list[ast.FunctionDef] = []
    stack = list(fn_node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.FunctionDef):
            out.append(n)
            continue
        if isinstance(n, ast.AsyncFunctionDef):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return out


# ---------------------------------------------------------------- scanning

class FnCtx:
    def __init__(self, qualname: str, node: ast.AsyncFunctionDef, scope: str,
                 offloaded: bool = False):
        self.qualname = qualname
        self.node = node
        self.scope = scope  # "" 直接作用域 / "nested-def:<name>"
        self.offloaded = offloaded  # 该 def 是 thread/offload 目标，默认不在 loop 线程执行


def collect_scope_nodes(fn_node: ast.AST):
    """函数体直接作用域节点（不进入嵌套 def）。"""
    out: list[ast.AST] = []
    stack = list(fn_node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        out.append(n)
        stack.extend(ast.iter_child_nodes(n))
    return out


def build_parent_map(nodes: list[ast.AST]) -> dict:
    pm: dict = {}
    for n in nodes:
        for c in ast.iter_child_nodes(n):
            pm[c] = n
    return pm


def subtree_nodes(root: ast.AST) -> list[ast.AST]:
    return list(ast.walk(root))


class Scanner:
    def __init__(self, rel_path: str, tree: ast.Module, src: str):
        self.rel_path = rel_path
        self.tree = tree
        self.src = src
        self.src_lines = src.splitlines()
        self.imports = build_import_map(tree)
        self.hits: list[dict] = []
        self.lock_axis: list[dict] = []
        self.parse_note: str | None = None
        self.async_defs = 0

    # ---- helpers ----
    def excerpt(self, node: ast.AST, limit: int = 200) -> str:
        seg = None
        try:
            seg = ast.get_source_segment(self.src, node)
        except Exception:
            seg = None
        if not seg:
            ln = getattr(node, "lineno", None)
            if ln and 1 <= ln <= len(self.src_lines):
                seg = self.src_lines[ln - 1]
        if not seg:
            return ""
        seg = " ".join(seg.split())
        return seg[:limit] + ("…" if len(seg) > limit else "")

    def add_hit(self, ctx: FnCtx, node: ast.Call | ast.For | ast.While, category: str,
                risk: str, confidence: str, api: str, suggestion: str, dedup_note: str = "") -> None:
        path = self.rel_path
        if "/tests/" in f"/{path}" or path.endswith("/tests") or "/tests" in path.split("/"):
            dedup_note = (dedup_note + "；" if dedup_note else "") + "tests/ 内命中：与 scan-flaky-tests（测试时序轴）交叉，按测试代码解读"
        if category == "http_sync":
            dedup_note = (dedup_note + "；" if dedup_note else "") + "超时配置属 scan-http-clients 轴（AGEN-578），本卡只判阻塞本质"
        if ctx.offloaded:
            risk = {"high": "med", "med": "low", "low": "low"}.get(risk, risk)
            dedup_note = (dedup_note + "；" if dedup_note else "") + "该 def 是 thread/offload 目标，默认不在 loop 线程执行；若被误用于 loop 线程则恢复原风险"
        self.hits.append({
            "file": path,
            "line": node.lineno,
            "col": getattr(node, "col_offset", 0),
            "category": category,
            "api": api,
            "risk": risk,
            "confidence": confidence,
            "async_fn": ctx.qualname,
            "scope": ctx.scope,
            "excerpt": self.excerpt(node),
            "suggestion": suggestion,
            "dedup_note": dedup_note,
        })

    # ---- main ----
    def run(self) -> None:
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                child._dt998_parent = parent
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef):
                self.async_defs += 1
                self.scan_async_fn(node)

    def scan_async_fn(self, node: ast.AsyncFunctionDef) -> None:
        qn = self.qualname_of(node)
        self.scan_scope(FnCtx(qn, node, ""))
        # 嵌套同步 def：单独扫描并降权标注（仅当被 async 上下文同步调用时才阻塞 loop）
        off = thread_target_names(node, self.imports)
        for sub in direct_nested_defs(node):
            self.scan_scope(FnCtx(f"{qn}.<sync>{sub.name}", sub, f"nested-def:{sub.name}",
                                  offloaded=sub.name in off))

    def qualname_of(self, node: ast.AsyncFunctionDef) -> str:
        names = [node.name]
        cur = getattr(node, "_dt998_parent", None)
        while cur is not None:
            if isinstance(cur, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(cur.name)
            cur = getattr(cur, "_dt998_parent", None)
        return ".".join(reversed(names))

    def scan_scope(self, ctx: FnCtx) -> None:
        nodes = collect_scope_nodes(ctx.node)
        pm = build_parent_map(nodes)
        calls = [n for n in nodes if isinstance(n, ast.Call)]
        # offload 包裹的子树整体豁免
        offloaded: set[int] = set()
        for c in calls:
            name = call_full_name(c, self.imports)
            if name and OFFLOAD_RE.match(name):
                for sub in subtree_nodes(c):
                    if sub is not c.func:
                        offloaded.add(id(sub))
        # 变量构造标签表
        tags: dict[str, str] = {}
        for n in nodes:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                name = call_full_name(n.value, self.imports)
                if not name:
                    continue
                # conn.cursor() 之类的次级构造
                recv = self.recv_root(n.value)
                if (recv and tags.get(recv) == "sqlite"
                        and isinstance(n.value.func, ast.Attribute)
                        and n.value.func.attr == "cursor"):
                    tags[n.targets[0].id] = "sqlite"
                    continue
                for pat, tag in CTOR_TAGS:
                    if re.match(pat, name):
                        for t in n.targets:
                            if isinstance(t, ast.Name):
                                tags[t.id] = tag
                        break
        for c in calls:
            if id(c) in offloaded:
                continue
            self.check_call(ctx, c, tags)
        self.check_loops(ctx, nodes, pm, offloaded)

    def recv_root(self, call: ast.Call) -> str | None:
        cur = call.func
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        return cur.id if isinstance(cur, ast.Name) else None

    def check_call(self, ctx: FnCtx, c: ast.Call, tags: dict) -> None:
        name = call_full_name(c, self.imports)
        if not name:
            return
        # 锁轴去重（构造即匹配 threading.Lock().acquire 链或 var.acquire）
        recv = self.recv_root(c)
        recv_tag = tags.get(recv) if recv else None
        if recv_tag in LOCK_RECV and isinstance(c.func, ast.Attribute) and c.func.attr in LOCK_RECV[recv_tag]:
            self.lock_axis.append({"file": self.rel_path, "line": c.lineno,
                                   "api": name, "async_fn": ctx.qualname})
            return
        if recv_tag and isinstance(c.func, ast.Attribute):
            entry = RECV_METHODS.get(recv_tag, {}).get(c.func.attr)
            if entry:
                cat, risk = entry
                conf = "certain" if recv_tag in {"thread", "queue", "future", "event",
                                                 "popen", "sqlite", "socket", "loop",
                                                 "reqsession", "httpxclient", "path", "img"} else "heuristic"
                self.add_hit(ctx, c, cat, risk, conf, name, SUGGESTIONS.get(cat, ""))
                return
        # 属性名启发式兜底：self._thread.join() 等构造标签覆盖不到的写法（await 过的不算）
        if isinstance(c.func, ast.Attribute) and not isinstance(getattr(c, "_dt998_parent", None), ast.Await):
            rname = c.func.value.attr if isinstance(c.func.value, ast.Attribute) else None
            meth = c.func.attr
            pat = ATTR_FALLBACK.get(meth)
            if rname and pat and re.search(pat, rname):
                cat = {"join": "thread_join", "result": "future_result", "communicate": "subprocess_sync"}[meth]
                self.add_hit(ctx, c, cat, "med", "heuristic",
                             f"{rname}.{meth}() 属性名启发式（{cat}）", SUGGESTIONS.get(cat, ""),
                             "按接收者属性名推断，需人工复核；await 过的调用已排除")
                return
        for pat, cat, risk, conf, label in RESOLVED_SPECS:
            if re.match(pat, name):
                api = label or name
                self.add_hit(ctx, c, cat, risk, conf, api, SUGGESTIONS.get(cat, ""))
                return
        # 泛化文件方法兜底：任意接收者 .read_text()/write_text()/...（await 过的跳过，
        # 避免误伤自定义异步包装类）
        if isinstance(c.func, ast.Attribute) and c.func.attr in GENERIC_FILE_METHODS:
            if not isinstance(getattr(c, "_dt998_parent", None), ast.Await):
                self.add_hit(ctx, c, "file_sync", "med", "heuristic",
                             f"{name}（接收者类型未跟踪，启发式）",
                             SUGGESTIONS["file_sync"],
                             "按方法名泛化匹配，需人工复核接收者类型")
                return

    # ---- CPU 循环启发式 ----
    def check_loops(self, ctx: FnCtx, nodes: list[ast.AST], pm: dict, offloaded: set) -> None:
        loops = [n for n in nodes if isinstance(n, (ast.For, ast.While))]
        for lp in loops:
            if id(lp) in offloaded:
                continue
            anc, cur = False, pm.get(lp)
            while cur is not None:
                if isinstance(cur, (ast.For, ast.While)):
                    anc = True
                    break
                cur = pm.get(cur)
            if anc:
                continue  # 内层循环已由外层循环的子树扫描覆盖
            body_nodes = [n for n in subtree_nodes(lp) if isinstance(n, ast.Call)]
            names = []
            for c in body_nodes:
                nm = call_full_name(c, self.imports)
                if nm:
                    names.append(nm)
            sub_nodes = subtree_nodes(lp)
            nested = any(isinstance(n, (ast.For, ast.While)) and n is not lp for n in sub_nodes)
            has_await = any(isinstance(n, ast.Await) for n in sub_nodes)
            core = [nm for nm in names if HEAVY_CORE_RE.search(nm)]
            mild = [nm for nm in names if HEAVY_MILD_RE.search(nm)]
            api_bits = []
            risk = None
            if core:
                risk = "med"
                api_bits.append("重调用: " + ", ".join(sorted(set(core))[:3]))
            if nested:
                if risk is None:
                    risk = "low"
                api_bits.append("async 函数内嵌套循环")
            if mild:
                if risk is None:
                    risk = "low"
                api_bits.append("轻度调用: " + ", ".join(sorted(set(mild))[:3]))
            if risk is None:
                continue
            if has_await:
                api_bits.append("循环含 await 让出点，单轮计算量小时无饥饿风险")
                risk = "low"
            note = "启发式命中，需人工确认量级（大集合/长文本才有饥饿风险；小循环可忽略）"
            api = f"loop@{ctx.qualname}: " + "; ".join(api_bits)
            self.add_hit(ctx, lp, "cpu_loop", risk, "heuristic", api,
                         SUGGESTIONS["cpu_loop"], note)


SUGGESTIONS = {
    "sleep_sync": "改 `await asyncio.sleep(...)`",
    "http_sync": "换 httpx.AsyncClient / aiohttp；短调用可 `await asyncio.to_thread(...)` 过渡",
    "subprocess_sync": "改 `asyncio.create_subprocess_exec/shell`；CPU 密集子任务用进程池",
    "socket_sync": "换 asyncio.open_connection / loop.sock_connect；或 to_thread 包裹",
    "nested_event_loop": "去掉内嵌事件循环，改原生 await / create_task",
    "queue_blocking": "改 asyncio.Queue；跨线程投递用 loop.call_soon_threadsafe",
    "event_wait": "改 asyncio.Event；跨线程用 to_thread 或 call_soon_threadsafe 唤醒",
    "thread_join": "改 async 任务 + await；确需 join 用 to_thread 包裹",
    "future_result": "用 asyncio.wrap_future 或 await executor 派发；勿在 loop 线程 .result()",
    "input_blocking": "loop 线程禁用交互输入，改 to_thread 或移出 async 路径",
    "file_sync": "热点路径 `await asyncio.to_thread(...)` 或 aiofiles；启动期一次性读可保留并注释豁免",
    "db_sync": "改 aiosqlite / 异步驱动；或 to_thread 包裹整段事务",
    "cpu_loop": "run_in_executor(process_pool) / anyio.to_process；或分片间 `await asyncio.sleep(0)` 让路",
    "cpu_call": "run_in_executor(process_pool) 派发；或确认数据量后加豁免注释",
}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("deeptutor")
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path(__file__).parent / "data.json"
    all_hits: list[dict] = []
    lock_axis: list[dict] = []
    files = 0
    parse_errors: list[str] = []
    total_defs = 0
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.as_posix()
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src, filename=rel)
        except SyntaxError as e:
            parse_errors.append(f"{rel}: {e}")
            continue
        files += 1
        sc = Scanner(rel, tree, src)
        sc.run()
        all_hits.extend(sc.hits)
        lock_axis.extend(sc.lock_axis)
        total_defs += sc.async_defs

    for h in all_hits:
        h["risk"] = {"high": "high", "med": "medium", "low": "low"}[h["risk"]]
    # 同一 (file, line, category) 合并为一个命中点，API 列表拼接
    merged: list[dict] = []
    seen: dict = {}
    for h in all_hits:
        key = (h["file"], h["line"], h["category"])
        if key in seen:
            m = seen[key]
            if h["api"] not in m["api"]:
                m["api"] += " + " + h["api"]
            if RISK_ORDER.get(h["risk"], 9) < RISK_ORDER.get(m["risk"], 9):
                m["risk"] = h["risk"]
            m["excerpt"] = m["excerpt"] if len(m["excerpt"]) >= len(h["excerpt"]) else h["excerpt"]
        else:
            seen[key] = h
            merged.append(h)
    all_hits = merged
    all_hits.sort(key=lambda h: (RISK_ORDER[h["risk"]], h["file"], h["line"]))
    for i, h in enumerate(all_hits, 1):
        h["id"] = f"{h['risk'][0].upper()}{i:03d}"

    by_cat: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for h in all_hits:
        by_cat[h["category"]] = by_cat.get(h["category"], 0) + 1
        by_risk[h["risk"]] = by_risk.get(h["risk"], 0) + 1
        by_file[h["file"]] = by_file.get(h["file"], 0) + 1

    data = {
        "meta": {
            "scanner": "scan_async_blocking.py",
            "root": str(root),
            "note": "AST 静态扫描，只读；命中以 path:line 定位，cpu 类为启发式需人工复核",
        },
        "coverage": {"py_files_scanned": files, "parse_errors": parse_errors,
                     "async_defs_total": total_defs,
                     "async_files_with_hits": len({h["file"] for h in all_hits})},
        "counts": {"total_hits": len(all_hits), "by_risk": by_risk,
                   "by_category": by_cat, "top_files":
                   sorted(by_file.items(), key=lambda kv: -kv[1])[:15]},
        "dedup": {"lock_axis_overlap_count": len(lock_axis),
                  "lock_axis_overlap": lock_axis,
                  "notes": ["锁轴证据见 evidence/lock-usage-20261005（AGEN-665）",
                            "超时轴见 scan-http-clients（AGEN-578）",
                            "task 生命周期轴见 evidence/async-tasks-2026-10-04（AGEN-453）",
                            "测试时序轴：tests/ 命中已在 dedup_note 标注"]},
        "hits": all_hits,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"files={files} parse_errors={len(parse_errors)} async_defs={total_defs} "
          f"hits={len(all_hits)} by_risk={by_risk} by_cat={by_cat}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
