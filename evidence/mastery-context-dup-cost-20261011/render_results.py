"""Render results.json into a human-readable results.md table."""

import json
import sys
from pathlib import Path

here = Path(__file__).parent
r = json.loads((here / "results.json").read_text(encoding="utf-8"))
lines: list[str] = []
add = lines.append

add("# Measured results — Mastery Path replayed-history duplication")
add("")
add(f"- repo head: `{r['meta']['repo_head'][:12]}`")
add(f"- token estimator: `{r['meta']['token_estimator']}` (serialized-JSON planning estimate, not provider billing)")
add(f"- fixture: shape-faithful mastery tool payloads replayed through real `replay_history`; offline, no LLM")
add("")
add("## Assembly × duplication × size matrix")
add("")
add("| scenario | turns | msgs | bytes | tok~ | tool-result % | whole-msg dup % | subtree dup % |")
add("|---|---:|---:|---:|---:|---:|---:|---:|")
for s in r["scenarios"]:
    add(
        f"| {s['scenario']} | {s['turns']} | {s['replayed_messages']} | "
        f"{s['replayed_bytes_serialized']:,} | {s['replayed_tokens_est']:,} | "
        f"{s['tool_result_share_pct']} | {s['exact_duplicate_messages']['share_pct']} | "
        f"{s['exact_duplicate_subtrees']['share_pct']} |"
    )
add("")
add("Legend: *tool-result %* = share of replayed-history bytes in `role=tool` messages. "
    "*Whole-msg dup %* = bytes in byte-identical repeated messages. "
    "*Subtree dup %* = bytes in JSON subtrees (top-level payload keys) that appear identically "
    "in an earlier tool result of the same history.")
add("")
add("## Per-turn carriage (one new turn, 3 main-loop rounds)")
add("")
add("| prior turns | per-round tok~ | total tok~ | history carried per round tok~ | ratio |")
add("|---|---|---|---|---|")
for k, v in r["loop_carriage"].items():
    add(
        f"| {k} | {', '.join(str(x) for x in v['per_round_tokens_est'])} | "
        f"{v['total_tokens_est']:,} | {v['history_carried_per_round_tokens_est']:,} | "
        f"{v['duplication_ratio']}x |"
    )
add("")
add("## Runtime snapshot accumulation")
add("")
add("| turns | snapshot rows retained | bytes | share of history |")
add("|---|---:|---:|---:|")
for k, v in r["snapshot_accumulation"].items():
    add(f"| {k} | {v['snapshot_rows_retained']} | {v['snapshot_bytes']:,} | {v['snapshot_share_pct']}% |")
add("")
add("## One mastery_status payload, key anatomy (6 modules × 8 KPs)")
add("")
a = r["status_payload_anatomy"]
add(f"- total payload: {a['payload_bytes']:,} B")
add("")
add("| key | bytes |")
add("|---|---:|")
for k, v in a["bytes_by_key"].items():
    add(f"| {k} | {v:,} |")
add("")
add(f"- whole keys byte-stable across two consecutive calls (differ by one graded KP): "
    f"{a['stable_share_pct']}%")
add(f"- per-KP entries inside `map` byte-identical between the same two calls: "
    f"**{a['map_kp_entry_stability_pct']}%** ({a['map_kp_entry_identical_bytes']:,} of "
    f"{a['map_bytes']:,} B)")
add("")
Path(here / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("results.md written")
sys.exit(0)
