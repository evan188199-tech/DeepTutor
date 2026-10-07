#!/usr/bin/env python3
"""Risk analysis for the regex call-site inventory.

Adds to each call site:
  - structural risk signatures (nested unbounded quantifiers, overlapping
    alternation branches, adjacent overlapping unbounded quantifiers, lazy
    any-char scans) found by parsing the pattern text;
  - input-bound and hot-path heuristics derived from the input expression and
    the module path;
  - an empirical timing probe (Python patterns only) run in isolated
    subprocesses with synthetic inputs ("a"*n style) to confirm or refute
    super-linear behavior;
  - a final timeout-risk grade: high / medium / low / review.

Read-only over the repository: it never edits product files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INF = float("inf")

# --------------------------------------------------------------------------- #
# 1. Pattern parser
# --------------------------------------------------------------------------- #

class Node:
    __slots__ = ("kind", "children", "alt", "qmin", "qmax", "lazy", "text", "negated", "members")

    def __init__(self, kind, children=None, alt=None, qmin=0, qmax=1, lazy=False,
                 text="", negated=False, members=None):
        self.kind = kind          # seq | alt | lit | class | dot | anchor | group-ref
        self.children = children or []
        self.alt = alt or []      # for alt: list of Node(seq)
        self.qmin, self.qmax = qmin, qmax
        self.lazy = lazy
        self.text = text
        self.negated = negated
        self.members = members or []  # for class: chars, ranges, class-escapes


class _ParseError(Exception):
    pass


class PatternParser:
    def __init__(self, pat: str):
        self.p = pat
        self.i = 0
        self.n = len(pat)

    def peek(self):
        return self.p[self.i] if self.i < self.n else ""

    def eat(self):
        c = self.p[self.i]
        self.i += 1
        return c

    def parse(self) -> Node:
        node = self.parse_alt()
        if self.i < self.n:
            raise _ParseError(f"unconsumed at {self.i}: {self.p[self.i:][:20]!r}")
        return node

    def parse_alt(self) -> Node:
        branches = [self.parse_seq()]
        while self.peek() == "|":
            self.eat()
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return Node("alt", alt=branches, text=self.p)

    def parse_seq(self) -> Node:
        items: list[Node] = []
        while self.i < self.n and self.peek() not in "|)":
            items.append(self.parse_quant())
        return Node("seq", children=items, text="")

    def parse_quant(self) -> Node:
        atom = self.parse_atom()
        while True:
            c = self.peek()
            if c == "*":
                self.eat(); atom.qmin, atom.qmax = 0, INF
            elif c == "+":
                self.eat(); atom.qmin, atom.qmax = 1, INF
            elif c == "?":
                self.eat(); atom.qmin, atom.qmax = 0, 1
            elif c == "{":
                save = self.i
                self.eat()
                j = self.p.find("}", self.i)
                if j == -1 or not all(ch.isdigit() or ch in ", " for ch in self.p[self.i:j]) or self.p[self.i:j] == "":
                    self.i = save
                    break
                body = self.p[self.i:j].replace(" ", "")
                self.i = j + 1
                if "," in body:
                    lo, hi = body.split(",", 1)
                    atom.qmin = int(lo) if lo else 0
                    atom.qmax = int(hi) if hi else INF
                else:
                    atom.qmin = atom.qmax = int(body)
            else:
                break
            if self.peek() == "?":
                self.eat(); atom.lazy = True
        return atom

    def parse_atom(self) -> Node:
        c = self.peek()
        if c == "(":
            return self.parse_group()
        if c == "[":
            return self.parse_class()
        if c == ".":
            self.eat()
            return Node("dot", text=".")
        if c == "\\":
            return self.parse_escape()
        if c in "^$":
            self.eat()
            return Node("anchor", text=c)
        self.eat()
        return Node("lit", text=c)

    def parse_escape(self) -> Node:
        self.eat()  # backslash
        if self.i >= self.n:
            raise _ParseError("trailing backslash")
        c = self.eat()
        if c.isdigit() and c != "0":
            return Node("group-ref", text="\\" + c)  # backreference: multiple-match ambiguity
        tok = "\\" + c
        if c in "dwsbWSB":
            if c == "b":
                return Node("anchor", text=tok)
            return Node("class", text=tok, members=[tok])
        if c in "AZ":
            return Node("anchor", text=tok)
        return Node("lit", text=tok)

    def parse_group(self) -> Node:
        self.eat()  # (
        if self.peek() == "?":
            self.eat()
            c = self.peek()
            if c == ":":
                self.eat()
            elif c == "<" and self.p[self.i + 1:self.i + 2] in ("=", "!"):
                # lookbehind (?<=...) / (?<!...): parse contents, mark zero-width
                self.eat()
                inner = self.parse_alt()
                if self.peek() != ")":
                    raise _ParseError("expected )")
                self.eat()
                return Node("lookaround", children=[inner], qmin=0, qmax=1, text="lookbehind")
            elif c == "P" and self.p[self.i + 1:self.i + 2] == "=":
                j = self.p.find(")", self.i)
                if j == -1:
                    raise _ParseError("unterminated backreference")
                name = self.p[self.i + 1:j]
                self.i = j + 1
                return Node("group-ref", qmin=0, qmax=1, text=f"(?P={name})")
            elif c == "P" or (c == "<"):
                # named group (?P<name>...) or (?<name>...) — skip the name
                j = self.p.find(">", self.i)
                if j == -1:
                    raise _ParseError("unterminated group name")
                self.i = j + 1
            elif c in "=!":
                # lookahead: parse contents, mark zero-width
                self.eat()
                inner = self.parse_alt()
                if self.peek() != ")":
                    raise _ParseError("expected )")
                self.eat()
                return Node("lookaround", children=[inner], qmin=0, qmax=1, text="lookahead")
            elif c and c in "aiLmsux":
                j = self.i
                while j < self.n and self.p[j] in "aiLmsux":
                    j += 1
                if j < self.n and self.p[j] == ":":
                    self.i = j + 1
                    inner = self.parse_alt()
                    if self.peek() != ")":
                        raise _ParseError("expected )")
                    self.eat()
                    return inner
                elif j < self.n and self.p[j] == ")":
                    self.i = j + 1
                    return Node("seq", children=[], text="inline-flags")
                else:
                    raise _ParseError("bad inline flags")
            elif c == "#":
                j = self.p.find(")", self.i)
                if j == -1:
                    raise _ParseError("unterminated comment")
                self.i = j + 1
                return Node("seq", children=[], text="comment")
            elif c == "(":
                raise _ParseError("conditional not supported")
            else:
                # inline flags (?i) etc.
                j = self.p.find(")", self.i)
                if j == -1:
                    raise _ParseError("unterminated flags")
                self.i = j + 1
                return Node("seq", children=[], text="flags")
        inner = self.parse_alt()
        if self.peek() != ")":
            raise _ParseError("expected )")
        self.eat()
        return inner

    def parse_class(self) -> Node:
        self.eat()  # [
        negated = False
        if self.peek() == "^":
            negated = True
            self.eat()
        members: list[str] = []
        first = True
        while True:
            if self.i >= self.n:
                raise _ParseError("unterminated class")
            c = self.p[self.i]
            if c == "]" and not first:
                self.eat()
                break
            first = False
            if c == "\\":
                self.i += 1
                e = self.eat()
                if e == "b":  # inside class, \b is backspace
                    members.append("\x08")
                elif e in "dws":
                    members.append("\\" + e)
                elif e in "nrtfv0":
                    members.append({"n": "\n", "r": "\r", "t": "\t", "f": "\f", "v": "\v", "0": "\0"}[e])
                elif e == "x" and self.i + 2 <= self.n:
                    h = self.p[self.i:self.i + 2]
                    self.i += 2
                    try:
                        members.append(chr(int(h, 16)))
                    except ValueError:
                        members.append("x")
                else:
                    members.append(e)
                continue
            # range?
            if self.i + 2 < self.n and self.p[self.i + 1] == "-" and self.p[self.i + 2] != "]":
                lo = c
                hi_ch = self.p[self.i + 2]
                members.append(f"{lo}-{hi_ch}")
                self.i += 3
                continue
            members.append(c)
            self.i += 1
        return Node("class", text="class", negated=negated, members=members)


def parse_pattern(pat: str):
    try:
        return PatternParser(pat).parse(), None
    except _ParseError as e:
        return None, str(e)


# --------------------------------------------------------------------------- #
# 2. Structural signature detection
# --------------------------------------------------------------------------- #

def _expand_class(node: Node):
    """Approximate the matchable character set of a class node.
    Returns a set of representative chars, or 'ANY' when unbounded/negated."""
    if node.negated:
        return "ANY"
    out = set()
    for m in node.members:
        if m in ("\\d",):
            out |= set("0123456789")
        elif m == "\\w":
            out |= set("abcXYZ019_")
        elif m == "\\s":
            out |= set(" \t\n")
        elif m == "\\S":
            return "ANY"
        elif m == "\\W" or m == "\\D":
            return "ANY"
        elif "-" in m and len(m) == 3 and m[1] == "-":
            lo, hi = m[0], m[2]
            if ord(hi) - ord(lo) <= 200:
                out |= {chr(x) for x in range(ord(lo), ord(hi) + 1)}
            else:
                return "ANY"
        elif len(m) == 1:
            out.add(m)
        else:
            return "ANY"
    return out if len(out) <= 300 else "ANY"


def _expand_dot(node: Node, dotall: bool):
    return "ANY"


def _first_set(node: Node, dotall: bool):
    """Characters the node can START matching. Returns set or 'ANY'."""
    if node.kind == "lit":
        ch = node.text
        if ch.startswith("\\"):
            m = {"n": "\n", "r": "\r", "t": "\t"}
            return {m.get(ch[1:], ch[1:])}
        return {ch}
    if node.kind == "class":
        return _expand_class(node)
    if node.kind == "dot":
        return "ANY"
    if node.kind == "seq":
        out = set()
        for ch_node in node.children:
            if ch_node.kind == "lookaround":
                continue
            fs = _first_set(ch_node, dotall)
            if fs == "ANY":
                return "ANY"
            out |= fs
            if ch_node.qmin == 0:
                continue
            break
        else:
            if not node.children:
                return set()
        return out
    if node.kind == "alt":
        out = set()
        for br in node.alt:
            fs = _first_set(br, dotall)
            if fs == "ANY":
                return "ANY"
            out |= fs
        return out
    return set()  # anchors, refs


def _sets_overlap(a, b) -> bool:
    if a == "ANY" or b == "ANY":
        return True
    return bool(a & b)


def _iter_nodes(node: Node):
    yield node
    for ch in node.children:
        yield from _iter_nodes(ch)
    for br in node.alt:
        yield from _iter_nodes(br)


def _matchable(node: Node) -> bool:
    return node.kind in ("lit", "class", "dot", "group-ref")


def _contains_matchable(node: Node) -> bool:
    return any(_matchable(x) for x in _iter_nodes(node))


def _nested_unbounded(node: Node):
    """Return list of descriptions of nested-quantifier signatures."""
    out = []
    for x in _iter_nodes(node):
        if x.kind in ("seq", "alt") and x.qmax == INF and x.qmax > 1:
            for inner in _iter_nodes(x):
                if inner is x:
                    continue
                if inner.kind in ("lit", "class", "dot", "group-ref") and inner.qmax == INF:
                    if inner.lazy:
                        out.append(f"nested-quantifier(lazy-mitigated): ({x.text or x.kind})* contains {inner.text}*?")
                    else:
                        out.append(f"nested-quantifier: ({x.text or x.kind})* contains {inner.text}*")
        elif x.kind in ("lit", "class", "dot") and x.qmax == INF:
            pass
    return out


def _overlapping_alternation(node: Node, dotall: bool):
    out = []
    for x in _iter_nodes(node):
        if x.kind != "alt":
            continue
        branches = x.alt
        for i in range(len(branches)):
            for j in range(i + 1, len(branches)):
                fi = _first_set(branches[i], dotall)
                fj = _first_set(branches[j], dotall)
                if _sets_overlap(fi, fj):
                    inside_unbounded = x.qmax == INF or _inside_unbounded_ancestor(node, x)
                    tag = "alternation-overlap(unbounded-outer)" if inside_unbounded else "alternation-overlap"
                    out.append(f"{tag}: branch {i} vs {j}")
    return out


def _inside_unbounded_ancestor(root: Node, target: Node) -> bool:
    stack: list[Node] = []
    found = [False]

    def walk(n) -> bool:
        if n is target:
            found[0] = any(a.qmax == INF for a in stack)
            return True
        stack.append(n)
        hit = False
        for ch in n.children:
            if walk(ch):
                hit = True
                break
        if not hit:
            for br in n.alt:
                if walk(br):
                    hit = True
                    break
        stack.pop()
        return hit

    walk(root)
    return found[0]


def _adjacent_unbounded(node: Node, dotall: bool):
    out = []
    for x in _iter_nodes(node):
        if x.kind != "seq":
            continue
        run = []
        for ch in x.children:
            if _matchable(ch) and ch.qmax == INF:
                run.append(ch)
            else:
                if len(run) >= 2:
                    out.append(run)
                run = []
        if len(run) >= 2:
            out.append(run)
    descs = []
    for run in out:
        ok = True
        for i in range(len(run) - 1):
            si = _char_set_of(run[i], dotall)
            sj = _char_set_of(run[i + 1], dotall)
            if not _sets_overlap(si, sj):
                ok = False
                break
        if ok:
            descs.append("adjacent-unbounded-overlap: " + " ".join(r.text or r.kind for r in run))
    return descs


def _char_set_of(node: Node, dotall: bool):
    if node.kind == "class":
        return _expand_class(node)
    if node.kind == "dot":
        return "ANY"
    if node.kind == "lit":
        return {node.text.lstrip("\\") or node.text}
    return set()


def _lazy_any(node: Node):
    out = []
    for x in _iter_nodes(node):
        if x.kind == "dot" and x.qmax == INF and x.lazy:
            out.append("lazy-dot-star")
        if x.kind == "class" and x.qmax == INF and x.lazy:
            out.append("lazy-class-star")
    return out


def _backreference(node: Node):
    return [f"backreference: {x.text}" for x in _iter_nodes(node) if x.kind == "group-ref"]


# --------------------------------------------------------------------------- #
# 3. Input bound and hot-path heuristics
# --------------------------------------------------------------------------- #

LARGE_HINTS = ("html", "raw", "content", "text", "body", "doc", "document", "markdown",
               "md", "chunk", "page", "file", "source", "prompt", "message", "stream",
               "prose", "full", "log", "report", "answer", "transcript", "output", "buffer",
               "data", "payload", "response", "block", "section", "description", "summary",
               "note", "comment", "query", "sentence", "paragraph", "manifest", "template")
SMALL_HINTS = ("line", "word", "token", "url", "key", "path", "slug", "title", "email",
               "phone", "version", "tag", "prefix", "suffix", "label", "host", "port",
               "id", "name", "ref", "sha", "hash", "ext", "suffix", "char", "cmd", "command",
               "flag", "date", "time", "iso", "lang", "locale", "dir", "branch")
HOT_PATH_DIRS = ("partners/channels", "api/routers", "agents/loop", "services/session",
                 "runtime/", "services/web", "api/", "agents/", "services/skill",
                 "services/chat", "services/reading_hints", "partners/")
COLD_PATH_DIRS = ("tests/", "scripts/", "web/tests/", "web/scripts/", "evidence/")


def input_bound_class(site: dict) -> str:
    """large | small | unknown | tiny"""
    src = (site.get("input_src") or "") + " " + site["path"].rsplit("/", 1)[-1]
    low = src.lower()
    if site["lang"] == "web" and "/tests/" in site["path"]:
        return "tiny"
    if site["path"].startswith(("tests/", "scripts/")) or "/tests/" in site["path"] or "/scripts/" in site["path"]:
        return "tiny"
    has_large = any(h in low for h in LARGE_HINTS)
    has_small = any(h in low for h in SMALL_HINTS)
    if has_large:
        return "large"
    if has_small:
        return "small"
    return "unknown"


def hot_path(site: dict) -> bool:
    p = site["path"]
    if p.startswith(("tests/", "scripts/")) or "/tests/" in p or "/scripts/" in p:
        return False
    if p.startswith("web/"):
        return True  # request/render path in web app
    return any(p.startswith(d) or ("/" + d) in p for d in HOT_PATH_DIRS)


# --------------------------------------------------------------------------- #
# 4. Timing probes (isolated subprocesses, synthetic inputs)
# --------------------------------------------------------------------------- #

def derive_alphabet(pattern: str) -> list[str]:
    """Collect up to 3 representative literal characters the pattern matches."""
    chars: list[str] = []
    try:
        tree, _ = parse_pattern(pattern)
    except Exception:
        tree = None
    if tree is not None:
        for x in _iter_nodes(tree):
            if x.kind == "lit" and len(x.text) == 1 and x.text.isalnum() and x.text not in chars:
                chars.append(x.text)
            elif x.kind == "class" and not x.negated:
                for mem in x.members:
                    if len(mem) == 1 and mem.isalnum() and mem not in chars:
                        chars.append(mem)
    if not chars:
        chars = ["a"]
    return chars[:3]

PROBE_SRC = r'''
import re, sys, time
pat = sys.argv[1]
op = sys.argv[2]
flags_s = sys.argv[3] if len(sys.argv) > 3 else ""
alpha = (sys.argv[4] if len(sys.argv) > 4 else "a") + " !"
A = alpha[0]
B = alpha[1] if len(alpha) > 1 else "b"
flags = 0
for name, val in (("DOTALL", re.S), ("IGNORECASE", re.I), ("MULTILINE", re.M)):
    if name in flags_s:
        flags |= val
rx = re.compile(pat, flags)
builders = {
    "aaaa": lambda n: A * n,
    "aaab": lambda n: A * n + "!",
    "abab": lambda n: (A + B) * (n // 2),
    "mixsp": lambda n: (A * (n // 4) + " ") * 3 + "!",
    "spmix": lambda n: (A + " ") * (n // 2) + "!",
    "spacex": lambda n: " " * n + "!",
    "nlx": lambda n: "\n" * n + "!",
}
size = 50
while size <= 20000:
    worst = 0.0
    for bname, b in builders.items():
        s = b(size)
        t0 = time.perf_counter()
        if op == "match":
            rx.match(s)
        elif op == "fullmatch":
            rx.fullmatch(s)
        elif op == "split":
            rx.split(s)
        elif op == "sub":
            rx.sub("X", s)
        elif op == "findall":
            rx.findall(s)
        elif op == "finditer":
            list(rx.finditer(s))
        else:
            rx.search(s)
        dt = time.perf_counter() - t0
        worst = max(worst, dt)
    print(f"SIZE {size} {worst:.4f}", flush=True)
    if worst > 0.4:
        print("RESULT slow", flush=True)
        sys.exit(0)
    if worst < 0.002:
        size *= 20
    else:
        size *= 4
print("RESULT fast", flush=True)
'''


NODE_PROBE_SRC = r"""
const pat = process.argv[2];
const flags = process.argv[3] || "";
const op = process.argv[4] || "search";
const alpha = (process.argv[5] || "a") + " !";
const A = alpha[0];
const B = alpha[1] || "b";
const rx = new RegExp(pat, flags);
const builders = {
  aaaa: (n) => A.repeat(n),
  aaab: (n) => A.repeat(n) + "!",
  abab: (n) => (A + B).repeat(Math.floor(n / 2)),
  mixsp: (n) => (A.repeat(Math.floor(n / 4)) + " ").repeat(3) + "!",
  spmix: (n) => (A + " ").repeat(Math.floor(n / 2)) + "!",
  spacex: (n) => " ".repeat(n) + "!",
  nlx: (n) => "\n".repeat(n) + "!",
};
let size = 50;
while (size <= 20000) {
  let worst = 0;
  for (const [bname, b] of Object.entries(builders)) {
    const str = b(size);
    const t0 = process.hrtime.bigint();
    if (op === "match") rx.test(str);
    else if (op === "replace") str.replace(rx, "X");
    else if (op === "split") str.split(rx);
    else rx.test(str);
    const dt = Number(process.hrtime.bigint() - t0) / 1e9;
    worst = Math.max(worst, dt);
  }
  console.log(`SIZE ${size} ${worst.toFixed(4)}`);
  if (worst > 0.4) { console.log("RESULT slow"); process.exit(0); }
  size = worst < 0.002 ? size * 20 : size * 4;
}
console.log("RESULT fast");
"""


def probe_pattern_web(pattern: str, op: str, flags: str | None) -> dict:
    """Same protocol as probe_pattern but under node for web patterns."""
    opmap = {"exec": "search", "test": "search", "match": "search", "matchAll": "search",
             "search": "search", "replace": "replace", "replaceAll": "replace",
             "split": "split", "literal": "search", "RegExp": "search"}
    jop = opmap.get(op, "search")
    try:
        alpha = "".join(derive_alphabet(pattern))
        proc = subprocess.run(
            ["node", "-e", NODE_PROBE_SRC, "probe", pattern, flags or "", jop, alpha],
            capture_output=True, text=True, timeout=25,
        )
        lines = proc.stdout.strip().splitlines()
        result = lines[-1] if lines else ""
        sizes = [(int(l.split()[1]), float(l.split()[2])) for l in lines if l.startswith("SIZE")]
        return {"verdict": "slow" if "slow" in result else "fast", "timings": sizes,
                "max_size": max((s for s, _ in sizes), default=0), "engine": "node"}
    except subprocess.TimeoutExpired:
        return {"verdict": "timeout", "timings": [], "max_size": 0, "engine": "node"}
    except Exception as e:
        return {"verdict": "error:" + type(e).__name__, "timings": [], "max_size": 0, "engine": "node"}


def probe_pattern(pattern: str, op: str, flags: str | None) -> dict:
    """Run the timing probe in a subprocess with a hard wall-clock limit."""
    op = {"subn": "sub"}.get(op, op)
    if op not in ("match", "search", "fullmatch", "sub", "split", "findall", "finditer"):
        op = "search"
    try:
        alpha = "".join(derive_alphabet(pattern))
        proc = subprocess.run(
            [sys.executable, "-c", PROBE_SRC, pattern, {"subn": "sub"}.get(op, op), flags or "", alpha],
            capture_output=True, text=True, timeout=25,
        )
        lines = proc.stdout.strip().splitlines()
        result = lines[-1] if lines else ""
        sizes = [(int(l.split()[1]), float(l.split()[2])) for l in lines if l.startswith("SIZE")]
        return {"verdict": "slow" if "slow" in result else "fast", "timings": sizes,
                "max_size": max((s for s, _ in sizes), default=0)}
    except subprocess.TimeoutExpired:
        return {"verdict": "timeout", "timings": [], "max_size": 0}
    except Exception as e:  # pragma: no cover
        return {"verdict": "error:" + type(e).__name__, "timings": [], "max_size": 0}


# --------------------------------------------------------------------------- #
# 5. Per-site analysis
# --------------------------------------------------------------------------- #

def analyze_pattern(pattern: str, dotall: bool):
    """Return (signatures, parse_error)."""
    sigs = []
    tree, err = parse_pattern(pattern)
    if tree is None:
        return ["unparsed:" + (err or "")], err
    sigs += _nested_unbounded(tree)
    sigs += _overlapping_alternation(tree, dotall)
    sigs += _adjacent_unbounded(tree, dotall)
    sigs += _lazy_any(tree)
    sigs += _backreference(tree)
    return sigs, None


def grade_site(site: dict, sigs: list[str], probe: dict | None) -> tuple[str, str]:
    """Return (grade, reason)."""
    op = site["op"]
    if op in ("escape",):
        return "low", "escape-only, no matching"
    bound = input_bound_class(site)
    hot = hot_path(site)
    hard_sigs = [s for s in sigs if s.startswith(("nested-quantifier: ", "alternation-overlap(unbounded-outer)"))]
    adj = [s for s in sigs if s.startswith("adjacent-unbounded-overlap")]
    alt = [s for s in sigs if s == "alternation-overlap"]
    lazy = [s for s in sigs if s.startswith("lazy-")]
    nested_lazy = [s for s in sigs if s.startswith("nested-quantifier(lazy-mitigated)")]

    if probe and probe["verdict"] == "timeout":
        return "high", "probe timeout: catastrophic blow-up on synthetic input"
    if probe and probe["verdict"] == "slow":
        mx = probe.get("max_size", 0)
        if hard_sigs and mx <= 2000:
            return "high", f"probe slow already at n={mx} (exponential-like); {'/'.join(hard_sigs[:2])}"
        return "medium", f"probe super-linear at large n={mx}; bound={bound}"

    if any(sg.startswith("unparsed") for sg in sigs):
        return "review", "pattern could not be parsed by the analyzer; manual review needed"
    if hard_sigs:
        if probe and probe["verdict"] == "fast":
            if probe.get("max_size", 0) >= 5000:
                return "low", f"signature {hard_sigs[0]} but probe linear up to n={probe['max_size']}; bound={bound}"
            return "medium", f"signature {'/'.join(hard_sigs[:2])}; probe only reached n={probe['max_size']}; bound={bound}"
        if bound in ("large", "unknown"):
            return "high", f"{'/'.join(hard_sigs[:2])}; bound={bound}; hot={hot}"
        return "medium" if hot else "low", f"{'/'.join(hard_sigs[:2])}; bound={bound}; hot={hot}"
    if nested_lazy:
        return "medium" if bound in ("large", "unknown") else "low", f"nested with lazy mitigation; bound={bound}"
    if adj:
        if probe and probe["verdict"] == "fast" and probe.get("max_size", 0) >= 5000:
            return "low", f"adjacent overlap but probe linear up to n={probe['max_size']}; bound={bound}"
        g = "medium" if bound in ("large", "unknown") else "low"
        return g, f"{'/'.join(adj[:1])}; bound={bound}"
    if alt:
        g = "medium" if (bound == "large" and hot) else "low"
        return g, f"{'/'.join(alt[:1])}; bound={bound}; hot={hot}"
    if lazy and bound == "large" and hot:
        return "medium", f"{'/'.join(lazy[:1])} on large hot-path input"
    if lazy:
        return "low", f"{'/'.join(lazy[:1])}; bound={bound}"
    return "low", f"no risk signature; bound={bound}"


def main() -> None:
    repo = sys.argv[1]
    infile = sys.argv[2]
    outfile = sys.argv[3]
    with open(infile, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    probe_budget = int(os.environ.get("PROBE_BUDGET", "60"))
    probed = 0
    results = []
    for site in data["sites"]:
        rec = dict(site)
        pattern = site.get("pattern")
        psrc = site.get("pattern_src") or ""
        rec["input_bound"] = input_bound_class(site)
        rec["hot_path"] = hot_path(site)
        probe = None
        if not site.get("pattern_literal"):
            if "re.escape" in psrc:
                rec["signatures"] = ["dynamic-literal(re.escape)"]
                rec["parse_error"] = None
                rec["grade"], rec["grade_reason"] = grade_site(
                    {**site, "pattern_literal": True}, rec["signatures"], None)
            else:
                rec["signatures"] = ["dynamic-pattern"]
                rec["parse_error"] = None
                rec["grade"] = "review"
                rec["grade_reason"] = "pattern built dynamically; manual review needed"
        elif site["lang"] == "py" and pattern is not None:
            dotall = bool(site.get("flags") and "DOTALL" in site["flags"]) or "(?s" in pattern
            sigs, perr = analyze_pattern(pattern, dotall)
            rec["signatures"] = sigs
            rec["parse_error"] = perr
            risky = any(s.startswith(("nested-quantifier", "alternation-overlap(unbounded", "adjacent-unbounded")) for s in sigs)
            if risky and probed < probe_budget:
                probe = probe_pattern(pattern, site["op"], site.get("flags"))
                probed += 1
            rec["probe"] = probe
            rec["grade"], rec["grade_reason"] = grade_site(site, sigs, probe)
        else:
            if pattern is None:
                rec["signatures"] = ["no-static-pattern"]
                rec["parse_error"] = None
                rec["grade"] = "review"
                rec["grade_reason"] = "pattern not statically recoverable"
            else:
                sigs, perr = analyze_pattern(pattern, bool(site.get("flags") and "s" in site["flags"]) or "(?s" in pattern)
                rec["signatures"] = sigs
                rec["parse_error"] = perr
                web_risky = any(sg.startswith(("nested-quantifier:", "alternation-overlap(unbounded", "adjacent-unbounded")) for sg in sigs)
                if web_risky and probed < probe_budget:
                    probe = probe_pattern_web(pattern, site["op"], site.get("flags"))
                    probed += 1
                rec["probe"] = probe
                rec["grade"], rec["grade_reason"] = grade_site(site, sigs, probe)
        results.append(rec)

    from collections import Counter
    grades = Counter(r["grade"] for r in results)
    out = {
        "probe_count": probed,
        "grade_counts": dict(grades),
        "sites": results,
    }
    with open(outfile, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"grades": dict(grades), "probed": probed}))


if __name__ == "__main__":
    main()
