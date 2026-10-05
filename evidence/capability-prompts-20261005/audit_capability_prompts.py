#!/usr/bin/env python3
"""Capability prompts en/zh alignment audit (read-only).

Extends the per-key parity checks of
tests/capabilities/test_status_i18n_consistency.py (visualize status pack)
to every prompts/ directory under deeptutor/capabilities/.

Reproducible from a clean checkout of the audited commit:

    python3 evidence/capability-prompts-20261005/audit_capability_prompts.py \
        --repo . --commit <sha> --out evidence/capability-prompts-20261005

Checks
    E1  file-set parity between prompts/en and prompts/zh
    Y1  YAML key-path parity (nested), both directions
    Y2  YAML value-type drift (str vs mapping)
    Y3  YAML empty/whitespace string value on one side
    PH  {placeholder} parity, per YAML key path and per markdown file
    M1  markdown heading structure drift (count / level sequence, not text)
    M2  markdown list-item / fenced-block count drift
    M3  markdown char-length ratio zh/en outside [0.2, 4.0] (informational)
    L1  loader-expected file missing for a language
    C1  key path referenced by capability code missing from the en or zh YAML
    C2  YAML leaf key never referenced by capability code (dead-copy
        heuristic; tolerant of dynamic dispatch, mirrors
        test_no_orphan_yaml_keys)

Code-reference patterns understood by C1/C2:
    _t("dotted.path"), _t(f"prefix.{var}")          dotted walks (own pack)
    prompt_text(prompts, ("a", "b"))                tuple walks (own pack)
    pack.get("x") / section.get("y")                leaf-name mentions
    get_prompt(prompts, "section", "field")         section/field walks
    i18n.t("key")  (StatusI18n)                     status.<key>
    plus every dotted key used by the shared loop assembler
    (deeptutor/agents/loop/prompt_blocks.py), which serves all packs.

Severity: P1 = user-visible failure or wrong/missing text at runtime;
P2 = silent fallback / one-language degradation; P3 = structural drift
signal, dormant hook, or dead copy.

No product code is modified: the script only reads the repository and
writes report.md / findings.json / SHA256SUMS under --out.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
from pathlib import Path

import yaml

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
FENCE = re.compile(r"^\s*```")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
HEADING = re.compile(r"^(#{1,6})\s+")
# _t("a.b.c") — also matches calls that pass extra kwargs after the literal.
DOTTED_T = re.compile(r'\b_t\(\s*f?"([^"{}]+)"')
# _t(f"prefix.{var}") — dynamic prefix dispatch.
FSTRING_T_PREFIX = re.compile(r'\b_t\(\s*f"([^"{}.]+)\.')
# StatusI18n: i18n.t("key") resolves inside the pack's status: section.
STATUS_T = re.compile(r'\bi18n\.t\(\s*"([^"]+)"')
PROMPT_TEXT_PATH = re.compile(r"prompt_text\(\s*\w+\s*,\s*\(([^)]*?)\)", re.DOTALL)
GET_LITERAL = re.compile(r'\.get\(\s*"([^"]+)"')
GET_PROMPT_CALL = re.compile(r'get_prompt\(\s*\w+\s*,\s*"([^"]+)"(?:\s*,\s*"([^"]+)")?')

# Shared loop assembler: its dotted keys are looked up in whatever pack the
# active pipeline was built with, so they count as references for every pack.
SHARED_ASSEMBLER = "deeptutor/agents/loop/prompt_blocks.py"

# Loader ground truth, derived from the audited commit (report §3 lists the
# code references).  dirs are relative to the repository root.
#   base:  prompt_base_module/agent the capability's loop pipeline merges
#          underneath its own pack (deeptutor/agents/loop/pipeline.py
#          _load_prompt_pack) — assembler keys resolve against the merge.
#   hook:  capability name used as the first segment of an override lookup
#          inside system_block(prompts=...) (mastery/loop.py:236).
LOADERS: dict[str, dict] = {
    "ask_questions": {"kind": "resources_md", "dir": "deeptutor/capabilities/ask_questions/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/ask_questions/loop.py"]},
    "ima": {"kind": "resources_md", "dir": "deeptutor/capabilities/ima/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/ima/capability.py"]},
    "marginnote4": {"kind": "resources_md", "dir": "deeptutor/capabilities/marginnote4/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/marginnote4/capability.py"]},
    "obsidian": {"kind": "resources_md", "dir": "deeptutor/capabilities/obsidian/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/obsidian/capability.py"]},
    "setup": {"kind": "resources_md", "dir": "deeptutor/capabilities/setup/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/setup/capability.py"]},
    "solve": {"kind": "resources_md", "dir": "deeptutor/capabilities/solve/prompts", "files": ["system.md"], "code": ["deeptutor/capabilities/solve/loop.py"]},
    "partner_authoring": {"kind": "resources_md", "dir": "deeptutor/capabilities/partner_authoring/prompts", "files": ["system.md", "heuristic.md"], "code": ["deeptutor/capabilities/partner_authoring/capability.py"]},
    "partner_group": {"kind": "resources_md", "dir": "deeptutor/capabilities/partner_group/prompts", "files": ["system.md", "invoke_other.md"], "code": ["deeptutor/capabilities/partner_group/capability.py"]},
    "course_study": {"kind": "resources_yaml", "dir": "deeptutor/capabilities/course_study/prompts", "files": ["course_study.yaml"], "code": ["deeptutor/capabilities/course_study/capability.py"]},
    "explore_context": {"kind": "resources_yaml", "dir": "deeptutor/capabilities/explore_context/prompts", "files": ["explore_context.yaml"], "code": ["deeptutor/capabilities/explore_context/capability.py", "deeptutor/capabilities/explore_context/explorer.py"]},
    "reading": {"kind": "resources_yaml", "dir": "deeptutor/capabilities/reading/prompts", "files": ["reading.yaml"], "code": ["deeptutor/capabilities/reading/capability.py"]},
    "mastery": {"kind": "manager_yaml", "dir": "deeptutor/capabilities/mastery/prompts", "files": ["mastery_loop.yaml"], "code": ["deeptutor/capabilities/mastery/loop.py", "deeptutor/capabilities/mastery/tools.py", "deeptutor/capabilities/mastery/pipeline.py"], "base": {"module": "chat", "agent": "agentic_chat", "dir": "deeptutor/agents/chat/prompts"}, "hook": "mastery"},
    "audio_overview (shared dir)": {"kind": "manager_yaml", "dir": "deeptutor/capabilities/prompts", "files": ["audio_overview.yaml"], "code": ["deeptutor/capabilities/audio_overview/capability.py"]},
}


def flat_keys(node, prefix=()):
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = prefix + (str(k),)
            out.append(path)
            out.extend(flat_keys(v, path))
    return out


def leaf_entries(node, prefix=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaf_entries(v, prefix + (str(k),))
    else:
        yield prefix, node


def placeholders(text):
    return set(PLACEHOLDER.findall(text or ""))


def heading_seq(text):
    return [(len(m.group(1)),) for ln in (text or "").splitlines() if (m := HEADING.match(ln))]


def md_stats(text):
    lines = (text or "").splitlines()
    return {
        "headings": heading_seq(text or ""),
        "list_items": sum(1 for ln in lines if LIST_ITEM.match(ln)),
        "fences": sum(1 for ln in lines if FENCE.match(ln)),
        "placeholders": placeholders(text or ""),
        "chars": len(text or ""),
    }


class Findings:
    def __init__(self):
        self.rows = []

    def add(self, severity, kind, path, detail):
        self.rows.append({"severity": severity, "kind": kind, "path": path, "detail": detail})

    def sorted(self):
        order = {"P1": 0, "P2": 1, "P3": 2}
        return sorted(self.rows, key=lambda r: (order[r["severity"]], r["kind"], r["path"]))


def audit_md_pair(findings, en_path: Path, zh_path: Path, ratios: list[dict]):
    rel_en, rel_zh = str(en_path), str(zh_path)
    en_text = en_path.read_text(encoding="utf-8")
    zh_text = zh_path.read_text(encoding="utf-8")
    en, zh = md_stats(en_text), md_stats(zh_text)
    ratio = round(zh["chars"] / en["chars"], 2) if en["chars"] else None
    ratios.append({"file": rel_en, "chars_en": en["chars"], "chars_zh": zh["chars"], "ratio_zh_per_en": ratio})
    if en["placeholders"] - zh["placeholders"]:
        findings.add("P1", "PH", rel_zh, f"placeholders only in en: {sorted(en['placeholders'] - zh['placeholders'])}")
    if zh["placeholders"] - en["placeholders"]:
        findings.add("P2", "PH", rel_zh, f"placeholders only in zh: {sorted(zh['placeholders'] - en['placeholders'])}")
    if en["headings"] != zh["headings"]:
        findings.add(
            "P2", "M1", rel_zh,
            f"heading structure drift: en count={len(en['headings'])} levels={[l for l, in en['headings']]} "
            f"zh count={len(zh['headings'])} levels={[l for l, in zh['headings']]}",
        )
    if en["list_items"] != zh["list_items"]:
        findings.add("P3", "M2", rel_zh, f"list-item count en={en['list_items']} zh={zh['list_items']}")
    if en["fences"] != zh["fences"]:
        findings.add("P2", "M2", rel_zh, f"fenced-block count en={en['fences']} zh={zh['fences']}")
    if ratio is not None and not (0.2 <= ratio <= 4.0):
        findings.add("P3", "M3", rel_zh, f"char ratio zh/en={ratio} outside [0.2, 4.0] (en={en['chars']}, zh={zh['chars']})")


def audit_yaml_pair(findings, en_path: Path, zh_path: Path):
    rel_en, rel_zh = str(en_path), str(zh_path)
    en_data = yaml.safe_load(en_path.read_text(encoding="utf-8")) or {}
    zh_data = yaml.safe_load(zh_path.read_text(encoding="utf-8")) or {}
    en_paths = set(map(tuple, flat_keys(en_data)))
    zh_paths = set(map(tuple, flat_keys(zh_data)))
    for p in sorted(en_paths - zh_paths):
        findings.add("P1", "Y1", rel_zh, f"key missing in zh: {'.'.join(p)!r}")
    for p in sorted(zh_paths - en_paths):
        findings.add("P2", "Y1", rel_zh, f"key missing in en (zh-only): {'.'.join(p)!r}")
    en_leaf = dict(leaf_entries(en_data))
    zh_leaf = dict(leaf_entries(zh_data))
    for p in sorted(set(en_leaf) & set(zh_leaf)):
        ev, zv = en_leaf[p], zh_leaf[p]
        if isinstance(ev, str) != isinstance(zv, str):
            findings.add("P2", "Y2", rel_zh, f"type drift at {'.'.join(p)!r}: en={'str' if isinstance(ev, str) else type(ev).__name__} zh={'str' if isinstance(zv, str) else type(zv).__name__}")
            continue
        if isinstance(ev, str):
            if not ev.strip():
                findings.add("P2", "Y3", rel_en, f"empty string value at {'.'.join(p)!r}")
            if not zv.strip():
                findings.add("P2", "Y3", rel_zh, f"empty string value at {'.'.join(p)!r}")
            ep, zp = placeholders(ev), placeholders(zv)
            if ep - zp:
                findings.add("P1", "PH", rel_zh, f"placeholders only in en at {'.'.join(p)!r}: {sorted(ep - zp)}")
            if zp - ep:
                findings.add("P2", "PH", rel_zh, f"placeholders only in zh at {'.'.join(p)!r}: {sorted(zp - ep)}")


def code_key_references(code_files: list[Path], has_default_ref: dict | None = None):
    """All ways a piece of code can name a prompt-pack key.

    has_default_ref, when given, receives dotted-literal -> bool entries
    recording whether the lookup call passed a default= argument.
    """
    names: set[str] = set()          # bare leaf names (from .get("x"))
    dotted: set[tuple[str, ...]] = set()
    prefixes: list[str] = []         # f-string dynamic prefixes
    has_default: dict[str, bool] = {}  # dotted literal -> call passes default=

    for cf in code_files:
        src = cf.read_text(encoding="utf-8")
        for m in DOTTED_T.finditer(src):
            dotted.add(tuple(m.group(1).split(".")))
            # Heuristic: does this lookup pass a default=? A missing key with
            # a default degrades to that default (wrong language, not missing
            # text); without one it yields "" or the caller's own fallback.
            window = src[m.end(): m.end() + 300]
            call_closed = window.find(")") if window.find(")") != -1 else len(window)
            has_default[m.group(1)] = "default=" in window[:call_closed]
        for m in FSTRING_T_PREFIX.finditer(src):
            prefixes.append(m.group(1) + ".")
        for m in STATUS_T.finditer(src):
            dotted.add(("status", m.group(1)))
        for m in PROMPT_TEXT_PATH.finditer(src):
            parts = re.findall(r'"([^"]+)"', m.group(1))
            if parts:
                dotted.add(tuple(parts))
        for m in GET_PROMPT_CALL.finditer(src):
            section, field = m.group(1), m.group(2)
            dotted.add((section,) if field is None else (section, field))
        for m in GET_LITERAL.finditer(src):
            names.add(m.group(1))
    if has_default_ref is not None:
        has_default_ref.update(has_default)
    return names, dotted, prefixes


def deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def audit_code_refs(findings, spec, en_data, zh_data, base_en_data, base_zh_data, code_files, shared_assembler):
    if not en_data:
        return
    names, dotted, prefixes = code_key_references(code_files)
    defaults_map: dict[str, bool] = {}
    code_key_references(code_files, defaults_map)
    defaults = defaults_map
    # A loop-pipeline pack (mastery) is also read by the shared assembler with
    # base(pack) merged underneath, so the assembler's keys resolve against the
    # merged pack, not the capability yaml alone.
    pipeline_pack = base_en_data is not None
    if pipeline_pack and shared_assembler and shared_assembler.exists():
        a_names, a_dotted, a_prefixes = code_key_references([shared_assembler])
        names |= a_names
        dotted |= a_dotted
        prefixes += a_prefixes
    effective_en_leaf = dict(leaf_entries(deep_merge(base_en_data or {}, en_data)))
    effective_zh_leaf = dict(leaf_entries(deep_merge(base_zh_data or {}, zh_data)))
    own_en_leaf = dict(leaf_entries(en_data))
    own_zh_leaf = dict(leaf_entries(zh_data))
    base_en_leaf = dict(leaf_entries(base_en_data or {}))
    hook_name = spec.get("hook")
    dir_label = spec["dir"]

    def referenced(path: tuple[str, ...]) -> bool:
        if path in dotted:
            return True
        full = ".".join(path)
        if any(full.startswith(pre) for pre in prefixes):
            return True
        return path[-1] in names

    for p in sorted(dotted):
        label = ".".join(p)
        if hook_name and p[0] == hook_name and p not in own_en_leaf and p not in base_en_leaf:
            findings.add("P3", "C1", dir_label, f"dormant override hook: lookup path {label!r} is provided by neither the capability yaml nor the base pack (always falls back)")
            continue
        missing_en = p not in effective_en_leaf
        missing_zh = p not in effective_zh_leaf
        if missing_en or missing_zh:
            # A lookup whose call passes default= silently degrades to that
            # default (wrong language, content intact); without one the user
            # gets an empty string.
            guarded = defaults.get(".".join(p), False) or any(
                defaults.get(seg, False) for seg in (".".join(p),)
            )
            severity = "P2" if guarded else "P1"
            side = "en" if missing_en else "zh"
            suffix = " (call passes default= — zh users silently get the default text)" if guarded else ""
            findings.add(severity, "C1", dir_label, f"code-referenced key path missing in {side} yaml: {label!r}{suffix}")
    for p in sorted(set(own_en_leaf)):
        if not referenced(p):
            findings.add("P3", "C2", dir_label, f"yaml key never referenced by capability code (dead copy?): {'.'.join(p)!r}")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="repository root (read-only)")
    ap.add_argument("--out", required=True, help="output directory for report.md, findings.json, SHA256SUMS")
    ap.add_argument("--commit", default=None, help="audited commit recorded into findings.json")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    shared_assembler = repo / SHARED_ASSEMBLER

    findings = Findings()
    hashes: list[str] = []
    capability_rows: list[dict] = []
    md_ratios: list[dict] = []

    prompts_dirs = sorted(p for p in (repo / "deeptutor" / "capabilities").rglob("prompts") if p.is_dir())
    for pdir in prompts_dirs:
        if pdir == repo / "deeptutor" / "capabilities" / "prompts":
            cap_label = "audio_overview (shared dir)"
        else:
            cap_label = pdir.parent.name
        en_dir, zh_dir = pdir / "en", pdir / "zh"
        en_files = sorted(p.name for p in en_dir.iterdir() if p.is_file()) if en_dir.is_dir() else []
        zh_files = sorted(p.name for p in zh_dir.iterdir() if p.is_file()) if zh_dir.is_dir() else []
        for f in sorted(set(en_files) - set(zh_files)):
            findings.add("P1", "E1", str(zh_dir / f), "file missing in zh (en-only file)")
        for f in sorted(set(zh_files) - set(en_files)):
            findings.add("P1", "E1", str(en_dir / f), "file missing in en (zh-only file)")
        for f in sorted(set(en_files) & set(zh_files)):
            en_p, zh_p = en_dir / f, zh_dir / f
            hashes.append(f"{sha256_of(en_p)}  {en_p.relative_to(repo)}")
            hashes.append(f"{sha256_of(zh_p)}  {zh_p.relative_to(repo)}")
            if f.endswith((".yaml", ".yml")):
                audit_yaml_pair(findings, en_p, zh_p)
            else:
                audit_md_pair(findings, en_p, zh_p, md_ratios)
        capability_rows.append(
            {"capability": cap_label, "dir": str(pdir.relative_to(repo)), "en_files": en_files, "zh_files": zh_files}
        )

    for cap, spec in LOADERS.items():
        pdir = repo / spec["dir"]
        for lang in ("en", "zh"):
            for fname in spec["files"]:
                if not (pdir / lang / fname).exists():
                    findings.add(
                        "P1" if spec["kind"] == "resources_md" else "P2",
                        "L1",
                        f"{spec['dir']}/{lang}/{fname}",
                        "loader-expected file missing",
                    )
        yaml_name = next((f for f in spec["files"] if f.endswith(".yaml")), None)
        if yaml_name:
            en_data = yaml.safe_load((pdir / "en" / yaml_name).read_text(encoding="utf-8")) or {}
            zh_data = yaml.safe_load((pdir / "zh" / yaml_name).read_text(encoding="utf-8")) or {}
            base_spec = spec.get("base")
            base_en = base_zh = None
            if base_spec:
                base_en = yaml.safe_load((repo / base_spec["dir"] / "en" / f"{base_spec['agent']}.yaml").read_text(encoding="utf-8")) or {}
                base_zh = yaml.safe_load((repo / base_spec["dir"] / "zh" / f"{base_spec['agent']}.yaml").read_text(encoding="utf-8")) or {}
            code_files = [repo / c for c in spec["code"]]
            audit_code_refs(findings, spec, en_data, zh_data, base_en, base_zh, code_files, shared_assembler)

    rows = findings.sorted()
    stamp = _dt.date.today().isoformat()
    payload = {
        "audited_repo_commit": args.commit,
        "generated": stamp,
        "capability_rows": capability_rows,
        "md_char_ratios": md_ratios,
        "findings": rows,
    }
    (out / "findings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("\n".join(sorted(hashes)) + "\n", encoding="utf-8")
    counts = {s: sum(1 for r in rows if r["severity"] == s) for s in ("P1", "P2", "P3")}
    print(f"findings={len(rows)} P1={counts['P1']} P2={counts['P2']} P3={counts['P3']}")
    print(f"wrote {out/'findings.json'} and {out/'SHA256SUMS'}")


if __name__ == "__main__":
    main()
