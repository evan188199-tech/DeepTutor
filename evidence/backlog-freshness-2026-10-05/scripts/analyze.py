#!/usr/bin/env python3
"""Analyze fetched upstream data and classify each up-* card. Read-only."""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
REPO = "HKUDS/DeepTutor"


def load(name):
    p = os.path.join(CACHE, name)
    return json.load(open(p)) if os.path.exists(p) else None


def issue(n):
    return load(f"repos_HKUDS_DeepTutor_issues_{n}.json")


def pull(n):
    return load(f"repos_HKUDS_DeepTutor_pulls_{n}.json")


def timeline(n):
    out = []
    page = 1
    while True:
        chunk = load(f"repos_HKUDS_DeepTutor_issues_{n}_timeline_per_page=100&page={page}.json")
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return out


def pr_state(n):
    p = pull(n)
    if not p or p.get("_notfound"):
        i = issue(n)
        if i and not i.get("_notfound") and "pull_request" in i:
            return {"number": n, "state": i["state"], "merged": False,
                    "merged_at": None, "title": i.get("title", ""), "closed_at": i.get("closed_at"),
                    "html_url": i.get("html_url", "")}
        return {"number": n, "state": "missing", "merged": False, "merged_at": None,
                "title": "", "closed_at": None, "html_url": ""}
    return {"number": n, "state": p["state"], "merged": p["merged"],
            "merged_at": p.get("merged_at"), "title": p.get("title", ""),
            "closed_at": p.get("closed_at"), "html_url": p.get("html_url", "")}


cards = json.load(open(os.path.join(HERE, "cards.json")))

# pass 1: cross-referenced PR numbers per primary issue
xref = {}
for c in cards:
    n = c["primary_issue"]
    if n is None:
        continue
    refs = []
    for ev in timeline(n):
        if ev.get("event") == "cross-referenced":
            src = ev.get("source", {}).get("issue", {})
            if src.get("pull_request") or "pull_request" in src:
                refs.append({
                    "number": src["number"],
                    "state": src.get("state"),
                    "title": src.get("title", ""),
                })
    # dedupe
    seen, ded = set(), []
    for r in refs:
        if r["number"] not in seen:
            seen.add(r["number"])
            ded.append(r)
    xref[n] = ded

# fetch PR details for xref numbers not already fetched
todo = set()
for n, refs in xref.items():
    for r in refs:
        todo.add(r["number"])
for n in sorted(todo):
    if not pull(n) and not (issue(n) and not issue(n).get("_notfound")):
        print(f"missing pull detail for xref #{n}")

report = {
    "fetched_at_note": "all data read from api.github.com HKUDS/DeepTutor, cached under cache/",
    "cards": [],
    "xref_prs": {},
}
for n in sorted({r["number"] for refs in xref.values() for r in refs}):
    report["xref_prs"][str(n)] = pr_state(n)

for c in cards:
    n = c["primary_issue"]
    row = dict(c)
    row["primary"] = None
    if n is not None:
        i = issue(n)
        if not i or i.get("_notfound"):
            row["primary"] = {"number": n, "kind": "missing"}
        else:
            row["primary"] = {
                "number": n,
                "kind": "pr" if "pull_request" in i else "issue",
                "state": i["state"],
                "state_reason": i.get("state_reason"),
                "closed_at": i.get("closed_at"),
                "title": i.get("title", ""),
                "html_url": i.get("html_url", ""),
                "labels": [l["name"] for l in i.get("labels", [])],
                "comments": i.get("comments"),
            }
    row["xref_prs"] = xref.get(n, [])
    row["pr_states"] = {str(n2): pr_state(n2) for n2 in c["pr_refs"]}
    report["cards"].append(row)

json.dump(report, open(os.path.join(HERE, "analysis.json"), "w"), ensure_ascii=False, indent=1)
print("analyzed", len(report["cards"]), "cards;",
      "xref prs:", len(report["xref_prs"]))
missing = [c["key"] for c in report["cards"] if c["primary"] and c["primary"].get("kind") == "missing"]
print("missing primaries:", missing or "none")
