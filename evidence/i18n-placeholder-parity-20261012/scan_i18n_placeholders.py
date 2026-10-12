#!/usr/bin/env python3
"""Read-only i18n placeholder / interpolation parity scanner.

Scans four i18n surfaces and reports, for every message key, whether the
set of interpolation placeholders differs between the languages that
provide that key ("missing / extra {var}" findings):

  A. backend.messages   deeptutor/services/i18n.py          `_MESSAGES` (en, zh),
                        placeholders rendered with str.format, e.g. {name}, {app!r}
  B. backend.metadata   deeptutor/i18n/metadata_i18n.py     capability/tool
                        description dicts (en, zh), static text today
  C. backend.status     deeptutor/agents/<module>/prompts/{en,zh}/*.yaml
                        top-level `status:` sections consumed by
                        deeptutor/i18n/status_i18n.py via str.format
  D. web.locales        web/locales/<lang>/<ns>.json (de,en,fr,pl,uk,zh),
                        i18next interpolation, e.g. {{count}}, {{count, number}}

The scanner never writes to scanned sources. Outputs are written to the
--out directory (default: next to this script):

  report.md      human-readable difference report with path:line evidence
  table.tsv      machine-readable key x language placeholder table
  raw.json       full extraction of every key / language / placeholder set
  SHA256SUMS     sha256 of every emitted file

Usage (from a DeepTutor checkout):
  python3 evidence/i18n-placeholder-parity-20261012/scan_i18n_placeholders.py \
      --repo-root /path/to/DeepTutor [--out <dir>]

Exit code 0 always (evidence tooling); findings live in the outputs.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

PY_PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+)((?:!?[^{}]*)?)\}")
I18N_PH = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,\s*([^}]+?))?\s*\}\}")


def py_placeholders(text: str) -> dict[str, str]:
    """str.format placeholders by name; `{{`/`}}` are literal braces."""
    unescaped = text.replace("{{", "\x00").replace("}}", "\x01")
    out: dict[str, str] = {}
    for match in PY_PH.finditer(unescaped):
        out.setdefault(match.group(1), match.group(2) or "")
    return out


def i18n_placeholders(text: str) -> dict[str, str]:
    """i18next {{var}} / {{var, formatter}} placeholders by name."""
    out: dict[str, str] = {}
    for match in I18N_PH.finditer(text):
        out.setdefault(match.group(1), (match.group(2) or "").strip())
    return out


def json_line_of(text: str, key: str) -> int:
    pattern = re.compile(r'"%s"\s*:' % re.escape(key))
    match = pattern.search(text)
    return text[: match.start()].count("\n") + 1 if match else 0


def parse_ast_string_dicts(path: Path) -> dict[str, dict[str, dict[str, object]]]:
    """Parse `<module>.py` assignments of the shape NAME = { key: { lang: "text" } }.

    Returns {varname: {outer_key: {lang: {"text", "line"}}}} using AST line
    numbers (value node). Only str->str inner mappings are collected.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, dict[str, object]]] = {}
    for node in tree.body:
        if not (isinstance(node, ast.AnnAssign) or isinstance(node, ast.Assign)):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        outer: dict[str, dict[str, object]] = {}
        for k, v in zip(value.keys, value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if not isinstance(v, ast.Dict):
                continue
            langs: dict[str, object] = {}
            for lk, lv in zip(v.keys, v.values):
                if not (isinstance(lk, ast.Constant) and isinstance(lk.value, str)):
                    continue
                if isinstance(lv, ast.Constant) and isinstance(lv.value, str):
                    langs[lk.value] = {"text": lv.value, "line": lv.lineno}
            if langs:
                outer[k.value] = langs
        if outer:
            result[names[0]] = outer
    return result


def parse_ast_lang_major(path: Path, varname: str) -> dict[str, dict[str, dict[str, object]]]:
    """Parse NAME = { lang: { key: "text" } } (language-major layout).

    Returns {lang: {key: {"text", "line"}}}.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, dict[str, object]]] = {}
    for node in tree.body:
        if not (isinstance(node, ast.AnnAssign) or isinstance(node, ast.Assign)):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if not any(isinstance(t, ast.Name) and t.id == varname for t in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for lang_k, lang_v in zip(value.keys, value.values):
            if not (isinstance(lang_k, ast.Constant) and isinstance(lang_k.value, str)):
                continue
            if not isinstance(lang_v, ast.Dict):
                continue
            entries: dict[str, dict[str, object]] = {}
            for mk, mv in zip(lang_v.keys, lang_v.values):
                if not (isinstance(mk, ast.Constant) and isinstance(mk.value, str)):
                    continue
                if isinstance(mv, ast.Constant) and isinstance(mv.value, str):
                    entries[mk.value] = {"text": mv.value, "line": mv.lineno}
            result[lang_k.value] = entries
    return result


def parse_status_yaml(path: Path) -> dict[str, dict[str, object]]:
    """Parse the top-level `status:` mapping of a prompt YAML, with line numbers.

    Handles flat `key: "value"` / `key: value` entries (the only form used by
    these files). Cross-checked against PyYAML when it is importable.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    strings: dict[str, dict[str, object]] = {}
    in_status = False
    for idx, line in enumerate(lines, start=1):
        if re.match(r"^status:\s*(#.*)?$", line):
            in_status = True
            continue
        if in_status:
            if line and not line[0].isspace():
                in_status = False
                continue
            entry = re.match(r'^\s+([A-Za-z0-9_]+):\s+(.*)$', line)
            if not entry:
                continue
            key, raw = entry.group(1), entry.group(2).strip()
            if raw.startswith(('"', "'")):
                quote = raw[0]
                end = raw.find(quote, 1)
                if end != -1:
                    value = raw[1:end]
                else:  # unterminated - take the rest verbatim
                    value = raw[1:]
            else:
                value = raw.split("  #", 1)[0].strip()
            strings[key] = {"text": value, "line": idx}
    try:
        import yaml  # optional cross-check

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ref = loaded.get("status") if isinstance(loaded, dict) else None
        if isinstance(ref, dict):
            for key, val in ref.items():
                if key in strings and strings[key]["text"] != str(val):
                    strings[key]["text_mismatch_yaml"] = str(val)
    except ImportError:
        pass
    return strings


class Surface:
    def __init__(self, surface_id: str, syntax: str, files: dict[str, Path]):
        self.id = surface_id
        self.syntax = syntax  # "str.format" | "i18next"
        self.files = files    # lang -> source file (same file may repeat)
        self.keys: dict[str, dict[str, dict]] = {}  # key -> lang -> entry
        self.rel = {lang: str(p) for lang, p in files.items()}


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def build_surfaces(root: Path) -> list[Surface]:
    surfaces: list[Surface] = []

    i18n_py = root / "deeptutor/services/i18n.py"
    if i18n_py.exists():
        messages = parse_ast_lang_major(i18n_py, "_MESSAGES")
        surface = Surface("backend.messages", "str.format",
                          {"en": i18n_py, "zh": i18n_py})
        for lang, entries in messages.items():
            for key, info in entries.items():
                surface.keys.setdefault(key, {})[lang] = {
                    "file": rel(root, i18n_py), "line": info["line"],
                    "text": info["text"],
                    "placeholders": py_placeholders(info["text"]),
                }
        surfaces.append(surface)

    meta_py = root / "deeptutor/i18n/metadata_i18n.py"
    if meta_py.exists():
        mod = parse_ast_string_dicts(meta_py)
        surface = Surface("backend.metadata", "str.format",
                          {"en": meta_py, "zh": meta_py})
        for varname, outer in mod.items():
            for key, langs in outer.items():
                surface.keys[f"{varname}.{key}"] = {
                    lang: {"file": rel(root, meta_py), "line": info["line"],
                           "text": info["text"],
                           "placeholders": py_placeholders(info["text"])}
                    for lang, info in langs.items()
                }
        surfaces.append(surface)

    status_surfaces: dict[str, Surface] = {}
    for yaml_path in sorted(root.glob("deeptutor/agents/*/prompts/*/*.yaml")):
        status = parse_status_yaml(yaml_path)
        if not status:
            continue
        lang = yaml_path.parent.name
        module = yaml_path.parent.parent.parent.name
        agent = yaml_path.stem
        surface = status_surfaces.setdefault(
            "backend.status",
            Surface("backend.status", "str.format", {}),
        )
        surface.files.setdefault(lang, yaml_path)
        for key, info in status.items():
            surface.keys.setdefault(f"{module}/{agent}:{key}", {})[lang] = {
                "file": rel(root, yaml_path), "line": info["line"],
                "text": info["text"],
                "placeholders": py_placeholders(str(info["text"])),
            }
    surfaces.extend(status_surfaces.values())

    locales = root / "web/locales"
    if locales.exists():
        json_surfaces: dict[str, Surface] = {}
        for lang_dir in sorted(p for p in locales.iterdir() if p.is_dir()):
            lang = lang_dir.name
            for json_path in sorted(lang_dir.glob("*.json")):
                ns = json_path.stem
                surface = json_surfaces.setdefault(
                    f"web.locales.{ns}",
                    Surface(f"web.locales.{ns}", "i18next", {}),
                )
                surface.files[lang] = json_path
                data = json.loads(json_path.read_text(encoding="utf-8"))
                raw_text = json_path.read_text(encoding="utf-8")
                for key, val in data.items():
                    if not isinstance(val, str):
                        continue
                    surface.keys.setdefault(key, {})[lang] = {
                        "file": rel(root, json_path),
                        "line": json_line_of(raw_text, key),
                        "text": val,
                        "placeholders": i18n_placeholders(val),
                    }
        surfaces.extend(json_surfaces.values())
    for s in surfaces:
        s.rel = {lang: rel(root, p) for lang, p in s.files.items()}
    return surfaces


def find_differences(surface: Surface) -> tuple[list[dict], int, int]:
    """Return (findings, keys_compared, single_language_keys)."""
    findings: list[dict] = []
    compared = 0
    single = 0
    for key, langs in surface.keys.items():
        if len(langs) < 2:
            single += 1
            continue
        compared += 1
        reference = langs.get("en") or next(iter(langs.values()))
        ref_names = set(reference["placeholders"])
        # duplicate usage differences (same name used N vs M times)
        ref_counts: dict[str, int] = {}
        for name in reference["placeholders"]:
            ref_counts[name] = ref_counts.get(name, 0) + 1
        for lang, entry in sorted(langs.items()):
            if entry is reference:
                continue
            names = set(entry["placeholders"])
            missing = sorted(ref_names - names)
            extra = sorted(names - ref_names)
            counts: dict[str, int] = {}
            for name in entry["placeholders"]:
                counts[name] = counts.get(name, 0) + 1
            dup_diff = sorted(n for n in counts
                              if counts[n] != ref_counts.get(n, 0)
                              and n not in missing and n not in extra)
            spec_diff = sorted(
                n for n in names & ref_names
                if entry["placeholders"][n] != reference["placeholders"][n]
            )
            if missing or extra or dup_diff or spec_diff:
                findings.append({
                    "surface": surface.id,
                    "key": key,
                    "reference_lang": "en" if "en" in langs else sorted(langs)[0],
                    "lang": lang,
                    "missing": missing,
                    "extra": extra,
                    "duplicate_count_diff": dup_diff,
                    "format_spec_diff": spec_diff,
                    "ref_placeholders": reference["placeholders"],
                    "lang_placeholders": entry["placeholders"],
                    "ref_loc": f"{reference['file']}:{reference['line']}",
                    "lang_loc": f"{entry['file']}:{entry['line']}",
                })
    return findings, compared, single


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".",
                        help="DeepTutor checkout root (default: .)")
    parser.add_argument("--out", default=None,
                        help="output directory (default: script directory)")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    out_dir = Path(args.out).resolve() if args.out else Path(__file__).resolve().parent

    surfaces = build_surfaces(root)
    raw = OrderedDict()
    all_findings: list[dict] = []
    for surface in surfaces:
        findings, compared, single = find_differences(surface)
        all_findings.extend(findings)
        raw[surface.id] = {
            "syntax": surface.syntax,
            "files": surface.rel,
            "keys_total": len(surface.keys),
            "keys_compared_multi_language": compared,
            "keys_single_language": single,
            "findings": findings,
            "keys": {
                key: {
                    lang: {
                        "placeholders": entry["placeholders"],
                        "loc": f"{entry['file']}:{entry['line']}",
                    } for lang, entry in sorted(langs.items())
                } for key, langs in sorted(surface.keys.items())
            },
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    head = ""
    try:
        import subprocess
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root),
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except Exception:
        pass

    raw_path = out_dir / "raw.json"
    raw_path.write_text(json.dumps({
        "scanned_head": head,
        "repo_root": str(root),
        "surfaces": raw,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tsv_path = out_dir / "table.tsv"
    with tsv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["surface", "key", "lang", "missing_vs_ref", "extra_vs_ref",
                         "duplicate_count_diff", "format_spec_diff",
                         "placeholders", "ref_placeholders", "ref_loc", "lang_loc"])
        for f in all_findings:
            writer.writerow([
                f["surface"], f["key"], f["lang"],
                ";".join(f["missing"]), ";".join(f["extra"]),
                ";".join(f["duplicate_count_diff"]), ";".join(f["format_spec_diff"]),
                json.dumps(f["lang_placeholders"], ensure_ascii=False, sort_keys=True),
                json.dumps(f["ref_placeholders"], ensure_ascii=False, sort_keys=True),
                f["ref_loc"], f["lang_loc"],
            ])

    lines: list[str] = []
    lines.append("# i18n placeholder / interpolation parity scan")
    lines.append("")
    lines.append(f"- Repo root: `{root}`")
    lines.append(f"- Scanned HEAD: `{head}`")
    lines.append("- Syntax by surface: `backend.*` uses Python `str.format` "
                 "placeholders (`{name}`, `{name!r}`); `web.locales.*` uses "
                 "i18next `{{name}}`.")
    lines.append("- Comparison rule: per key, every language is diffed against "
                 "the `en` entry (or the first language when `en` is absent): "
                 "`missing` = in reference but not in this language, `extra` = "
                 "the reverse.")
    lines.append("")
    lines.append("| surface | syntax | keys | compared (>=2 langs) | single-lang keys | findings |")
    lines.append("|---|---|---|---|---|---|")
    for surface in surfaces:
        _, compared, single = find_differences(surface)
        fcount = sum(1 for f in all_findings if f["surface"] == surface.id)
        lines.append(f"| `{surface.id}` | {surface.syntax} | "
                     f"{len(surface.keys)} | {compared} | {single} | {fcount} |")
    lines.append("")
    lines.append(f"Total findings: **{len(all_findings)}**")
    lines.append("")
    if all_findings:
        current = None
        for f in all_findings:
            if (f["surface"], f["key"]) != current:
                current = (f["surface"], f["key"])
                lines.append(f"## {f['surface']} — key `{f['key']}`")
            missing_txt = ", ".join(f"missing `{{{n}}}`" for n in f["missing"])
            extra_txt = ", ".join(f"extra `{{{n}}}`" for n in f["extra"])
            dup_txt = ", ".join(f"count differs `{n}`" for n in f["duplicate_count_diff"])
            spec_txt = ", ".join(f"format spec differs `{n}`" for n in f["format_spec_diff"])
            detail = "; ".join(x for x in (missing_txt, extra_txt, dup_txt, spec_txt) if x)
            lines.append(f"- `{f['lang']}` vs `{f['reference_lang']}`: {detail}.")
            lines.append(f"  - {f['reference_lang']}: `{f['ref_loc']}` → "
                         f"`{json.dumps(f['ref_placeholders'], ensure_ascii=False, sort_keys=True)}`")
            lines.append(f"  - {f['lang']}: `{f['lang_loc']}` → "
                         f"`{json.dumps(f['lang_placeholders'], ensure_ascii=False, sort_keys=True)}`")
        lines.append("")
    else:
        lines.append("No placeholder-set differences found on any surface.")
        lines.append("")
    lines.append("Re-run:")
    lines.append("```bash")
    lines.append("python3 evidence/i18n-placeholder-parity-20261012/"
                 "scan_i18n_placeholders.py --repo-root .")
    lines.append("```")
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sums_path = out_dir / "SHA256SUMS"
    entries = []
    for name in ("scan_i18n_placeholders.py", "report.md", "table.tsv", "raw.json",
                 "findings-analysis.md"):
        target = out_dir / name
        if target.exists():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            entries.append(f"{digest}  {name}")
    sums_path.write_text("\n".join(entries) + "\n", encoding="utf-8")

    print(f"surfaces={len(surfaces)} findings={len(all_findings)} out={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
