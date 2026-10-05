#!/usr/bin/env python3
"""Parse backlog jsonl files, extract up-* cards and their upstream references."""
import json
import re
import sys

BASE = "/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve/backlog/"
FILES = ["deeptour.0priority.jsonl", "deeptour.auto.jsonl", "deeptour.jsonl"]

cards = []
for fn in FILES:
    for lineno, line in enumerate(open(BASE + fn), 1):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        key = o.get("key", "")
        if not key.startswith("up-"):
            continue
        title = o.get("title", "")
        desc = o.get("description", "")
        text = title + "\n" + desc
        # trailing (#N) in title = primary upstream issue (ASCII or full-width parens)
        m = re.search(r"[（(]#(\d+)[)）]\s*$", title)
        primary_issue = int(m.group(1)) if m else None
        if primary_issue is None:
            # e.g. （#1447 未认领切片） — full-width parens with trailing text
            m = re.search(r"[（(]#(\d+)[ 　]", title)
            primary_issue = int(m.group(1)) if m else None
        # all #N refs in title+description
        refs = sorted({int(x) for x in re.findall(r"#(\d+)", text)})
        # explicit PR mentions like "PR #1682" / "pull #1682"
        pr_refs = sorted({int(x) for x in re.findall(r"[Pp][Rr]\s*#(\d+)", text)})
        cards.append({
            "file": fn,
            "line": lineno,
            "key": key,
            "title": title,
            "kind": key.split("-", 1)[0] if False else title.split("(", 1)[0].strip(": "),
            "priority": o.get("priority"),
            "primary_issue": primary_issue,
            "pr_refs": pr_refs,
            "all_refs": refs,
            "desc_head": desc[:400],
        })

out = sys.argv[1] if len(sys.argv) > 1 else "cards.json"
json.dump(cards, open(out, "w"), ensure_ascii=False, indent=1)
print(f"cards: {len(cards)}")
unique_nums = sorted({n for c in cards for n in c["all_refs"]})
print(f"unique referenced numbers: {len(unique_nums)}")
print(" ".join(str(n) for n in unique_nums))
