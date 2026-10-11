"""Offline fixture measurement of replayed-history duplication in Mastery Path.

No LLM calls, no servers, no network. The fixture replays synthetic but
shape-faithful mastery session rows through the real assembly functions:

- ``model_history.replay_history`` (verbatim turn-group concatenation)
- ``context_builder.count_tokens`` / ``_count_model_context_tokens``
  (the app's own planning estimators)

Payload shapes mirror ``MasteryStatusTool`` / ``MasteryBuildTool`` /
``MasteryQuizTool`` / ``MasteryGradeTool`` results and ``policy.map_summary``.

Usage: python3 measure_context_dup.py [--out results.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from deeptutor.services.session.context_builder import (  # noqa: E402
    _count_model_context_tokens,
    count_tokens,
)
from deeptutor.services.session.model_history import (  # noqa: E402
    normalize_model_turn,
    replay_history,
)

TOKEN_ENGINE = "unknown"


def _detect_token_engine() -> str:
    try:
        import tiktoken  # noqa: F401

        return "tiktoken/cl100k_base"
    except Exception:
        return "chars//4"


def cjson(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(cjson(obj).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Fixture builders (shape-faithful to the tool payloads cited in the report)
# --------------------------------------------------------------------------

KP_TYPES = ["memory", "procedure", "concept", "design"]


def build_map(n_modules: int, kps: int, revision: int, progressed: int = 0) -> dict:
    """policy.map_summary shape (deeptutor/learning/policy.py:365-419)."""
    modules = []
    total = mastered = 0
    kp_index = 0
    for m in range(n_modules):
        points = []
        for k in range(kps):
            status = "mastered" if kp_index < progressed else "learning"
            total += 1
            mastered += status == "mastered"
            points.append(
                {
                    "id": f"kp-{revision}-{m}-{k}",
                    "name": f"Knowledge point {m}.{k}: concept block with a long descriptive name "
                    "used by both the tutor and the dashboard render",
                    "type": KP_TYPES[(m + k) % 4],
                    "prerequisite_ids": [f"kp-{revision}-{m}-{k - 1}"] if k else [],
                    "topic_source_ids": [f"src-{m % 3}"] if k % 2 == 0 else [],
                    "status": status,
                    "mastery": round(0.42 + 0.01 * (kp_index % 40), 3),
                    "mastery_source": "graded" if status == "mastered" else "estimate",
                    "override_note": "",
                    "deferred": False,
                }
            )
            kp_index += 1
        modules.append(
            {
                "id": f"mod-{revision}-{m}",
                "name": f"Module {m}: foundations and applied practice",
                "objective": f"Learner can do module-{m} tasks unaided after this module.",
                "order": m,
                "mastered": mastered if m == 0 else 0,
                "total": kps,
                "knowledge_points": points,
            }
        )
    return {
        "name": "Quadratic equations and functions",
        "counts": {"mastered": mastered, "learning": total - mastered, "new": 0, "total": total},
        "due_reviews": 1,
        "complete": False,
        "modules": modules,
    }


def profile_block(turn: int) -> dict:
    """tools._profile_status shape (tools.py:507-540)."""
    return {
        "learner_profile": {
            "prior_knowledge": "Comfortable with linear equations; struggled with word problems.",
            "target_level": "Exam-ready within four weeks.",
            "time_budget": "30 minutes per day.",
            "preferences": ["worked examples first", "visual explanations"],
            "teaching_strategy": "Socratic questioning before revealing steps.",
            "notes": f"Learner corrected pacing on turn {turn}: slow down before quizzes.",
        },
        "intake_needed": False,
    }


def status_payload(map_obj: dict, revision: int, turn: int, answered: bool) -> dict:
    """MasteryStatusTool payload shape (tools.py:764-823)."""
    stages = {
        kp["id"]: "mastered" if kp["status"] == "mastered" else "learning"
        for mod in map_obj["modules"]
        for kp in mod["knowledge_points"]
    }
    visuals = {
        kp["id"]: {"required": [], "demonstrated": []}
        for mod in map_obj["modules"]
        for kp in mod["knowledge_points"]
    }
    payload = {
        "status": "active",
        "path_revision": revision,
        "path_id": "path-fixture-001",
        "path_name": map_obj["name"],
        "goal": "Pass the mid-term exam with a solid grasp of quadratics.",
        "sources": [
            {"id": f"src-{i}", "kind": "knowledge_base", "label": f"Textbook ch.{i+1}", "available": True}
            for i in range(3)
        ],
        "mode": "study",
        "next": dict(map_obj["modules"][0]["knowledge_points"][0], module="Module 0"),
        "map": map_obj,
        **profile_block(turn),
        "learning_stages": stages,
        "visual_requirements": visuals,
    }
    if answered:
        payload["pending_interaction"] = {
            "question_id": f"q-{turn}",
            "status": "answered",
            "learner_answer": "I think the discriminant is 9, so two real roots.",
        }
    else:
        payload["pending_interaction"] = {
            "question_id": f"q-{turn}",
            "status": "answer_pending",
            "instruction": "A question is already open. If the learner has answered it anywhere in "
            "this conversation, call mastery_grade with their answer and this question_id.",
        }
    return payload


def quiz_payload(map_obj: dict, revision: int, turn: int) -> dict:
    """MasteryQuizTool payload shape (tools.py:1121-1130)."""
    kp = map_obj["modules"][0]["knowledge_points"][0]
    return {
        "status": "registered",
        "path_revision": revision,
        "knowledge_point_id": kp["id"],
        "question_id": f"q-{turn}",
        "pending_question": {
            "question_id": f"q-{turn}",
            "knowledge_point_id": kp["id"],
            "question_type": "choice",
            "text": "Which sign of the discriminant gives two distinct real roots?",
            "options": {"A": "b^2-4ac > 0", "B": "b^2-4ac = 0", "C": "b^2-4ac < 0", "D": "None"},
            "answer": "A",
            "explanation": "Two distinct real roots require a positive discriminant.",
        },
    }


def grade_payload(map_obj: dict, revision: int, turn: int) -> dict:
    """MasteryGradeTool payload shape (tools.py:1372-1418)."""
    kp = map_obj["modules"][0]["knowledge_points"][0]
    return {
        "is_correct": True,
        "replayed": False,
        "path_revision": revision,
        "knowledge_point_id": kp["id"],
        "question_id": f"q-{turn}",
        "mastery": 0.72,
        "threshold": 0.85,
        "gate": {"type": "numeric", "threshold": 0.85},
        "mastered": False,
        "next": dict(map_obj["modules"][0]["knowledge_points"][1], module="Module 0"),
        "result": {
            "question_id": f"q-{turn}",
            "is_correct": True,
            "learner_answer": "I think the discriminant is 9, so two real roots.",
            "correct_label": "A",
            "explanation": "Two distinct real roots require a positive discriminant.",
        },
    }


TUTOR_TEXT = (
    "Good — the discriminant is indeed 9 here, so two distinct real roots exist. "
    "Let's connect that to the graph: a positive discriminant means the parabola crosses "
    "the x-axis twice. Before we move on, try this: for x^2 - 6x + 9, compute the "
    "discriminant and tell me what the graph does. Notice the value is exactly zero — "
    "what shape of intersection does that suggest? Take your time; we will verify with "
    "the vertex form afterwards and then look at one word-problem example."
)
LEARNER_TEXT = "Can we go over why the vertex form helps here before I try the word problem?"


def make_tool_call(call_id: str, name: str, args: str = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def make_turn_row(
    turn: int, tool_exchanges: list[tuple[str, dict]], snapshots: list[dict] | None = None
) -> dict:
    """One stored assistant row carrying a complete model_turn record
    (model_history.normalize_model_turn shape, persisted at agent_loop.py:355-366)."""
    messages: list[dict] = [
        {"role": "user", "content": LEARNER_TEXT + f" (turn {turn})"},
    ]
    for i, (name, payload) in enumerate(tool_exchanges):
        call_id = f"call-t{turn}-{i}-{name}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [make_tool_call(call_id, name)],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
    messages.append({"role": "assistant", "content": TUTOR_TEXT})
    for snap in snapshots or []:
        messages.append({"role": "user", "content": snap["content"], "_context_snapshot": snap["name"]})
    record = normalize_model_turn(
        {"version": 1, "messages": messages, "system": "SYS" * 16, "tools": [], "route": None}
    )
    return {"role": "assistant", "content": TUTOR_TEXT, "metadata": {"model_turn": record}}


def build_session_rows(n_turns: int, n_modules: int, kps: int) -> list[dict]:
    """Session the #1920 repro describes: profile update, outline revise,
    repeated status inspection, quiz + grade, continued tutoring."""
    rows: list[dict] = []
    revision = 1
    progressed = 0
    for turn in range(1, n_turns + 1):
        m = build_map(n_modules, kps, revision, progressed)
        exchanges: list[tuple[str, dict]] = [("mastery_status", status_payload(m, revision, turn, False))]
        if turn == 1:
            exchanges.append(("mastery_build", {
                "status": "built", "path_revision": revision, "mode": "replace",
                "path_name": m["name"], "modules_added": n_modules,
                "knowledge_points_added": n_modules * kps, "map": m,
            }))
        elif turn % 3 == 0:
            revision += 1
            m2 = build_map(n_modules, kps, revision, progressed)
            exchanges.append(("mastery_revise", {
                "status": "revised", "path_revision": revision, "module_id": m2["modules"][0]["id"],
                "added": 1, "dropped": 0, "map": m2,
            }))
            m = m2
        if turn % 2 == 0:
            exchanges.append(("mastery_quiz", quiz_payload(m, revision, turn)))
            progressed += 1
            m3 = build_map(n_modules, kps, revision, progressed)
            exchanges.append(("mastery_grade", grade_payload(m3, revision, turn)))
            exchanges.append(("mastery_status", status_payload(m3, revision, turn, True)))
            m = m3
        else:
            exchanges.append(("mastery_status", status_payload(m, revision, turn, False)))
        # A learner_profile runtime snapshot changed this turn (pipeline.py:525-527
        # appends it; older copies stay in the replayed history).
        snap = {
            "name": "learner_profile",
            "content": f"[Runtime context: learner_profile]\nPrior: linear equations ok. "
            f"Pacing note after turn {turn}: slow down before quizzes. Target: exam in 4 weeks.",
        }
        rows.append({"role": "user", "content": LEARNER_TEXT, "id": 2 * turn - 1})
        rows.append(make_turn_row(turn, exchanges, [snap]))
    return rows


def dialogue_only_rows(n_turns: int) -> list[dict]:
    rows = []
    for turn in range(1, n_turns + 1):
        rows.append({"role": "user", "content": LEARNER_TEXT, "id": 2 * turn - 1})
        rows.append(make_turn_row(turn, []))
    return rows


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def tool_name_of(message: dict, call_names: dict[str, str]) -> str:
    if message.get("role") == "tool":
        return call_names.get(message.get("tool_call_id", ""), "tool")
    if message.get("role") == "assistant" and message.get("tool_calls"):
        for call in message["tool_calls"]:
            call_names[call["id"]] = call["function"]["name"]
    return message.get("role", "?")


def measure_rows(rows: list[dict], label: str) -> dict:
    replayed = replay_history(rows)
    serialized_bytes = len(cjson(replayed).encode("utf-8"))
    token_estimate = _count_model_context_tokens(replayed)

    call_names: dict[str, str] = {}
    per_class: dict[str, int] = {}
    per_tool: dict[str, int] = {}
    msg_hashes: dict[str, list[int]] = {}
    total_tool_result_bytes = 0
    for idx, msg in enumerate(replayed):
        name = tool_name_of(msg, call_names)
        size = len(cjson(msg).encode("utf-8"))
        if msg.get("role") == "tool":
            per_tool[name] = per_tool.get(name, 0) + size
            total_tool_result_bytes += size
        per_class[msg.get("role", "?")] = per_class.get(msg.get("role", "?"), 0) + size
        h = sha(msg)
        msg_hashes.setdefault(h, []).append(idx)

    # Whole-message exact duplicates (same canonical content appearing again)
    dup_msg_count = sum(len(v) - 1 for v in msg_hashes.values() if len(v) > 1)
    dup_msg_bytes = sum(
        (len(v) - 1) * len(cjson(replayed[v[0]]).encode("utf-8"))
        for v in msg_hashes.values()
        if len(v) > 1
    )

    # Subtree-level exact duplicates across tool results (top-level JSON keys)
    subtree_seen: dict[str, tuple[str, int]] = {}
    dup_subtree_bytes = 0
    dup_subtree_occurrences = 0
    biggest_subtree = ("", 0, 0)
    for msg in replayed:
        if msg.get("role") != "tool":
            continue
        try:
            payload = json.loads(msg.get("content") or "{}")
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        tool = call_names.get(msg.get("tool_call_id", ""), "tool")
        for key, value in payload.items():
            h = sha(value)
            size = len(cjson(value).encode("utf-8"))
            if h in subtree_seen:
                dup_subtree_bytes += size
                dup_subtree_occurrences += 1
                if size > biggest_subtree[1]:
                    biggest_subtree = (f"{tool}.{key}", size, subtree_seen[h][1])
            else:
                subtree_seen[h] = (f"{tool}.{key}", size)

    return {
        "scenario": label,
        "turns": sum(1 for r in rows if r.get("role") == "assistant"),
        "replayed_messages": len(replayed),
        "replayed_bytes_serialized": serialized_bytes,
        "replayed_tokens_est": token_estimate,
        "bytes_by_role": per_class,
        "tool_result_bytes": total_tool_result_bytes,
        "tool_result_share_pct": round(100.0 * total_tool_result_bytes / max(1, serialized_bytes), 1),
        "bytes_by_tool": per_tool,
        "exact_duplicate_messages": {
            "count": dup_msg_count,
            "bytes": dup_msg_bytes,
            "share_pct": round(100.0 * dup_msg_bytes / max(1, serialized_bytes), 1),
        },
        "exact_duplicate_subtrees": {
            "occurrences": dup_subtree_occurrences,
            "bytes": dup_subtree_bytes,
            "share_pct": round(100.0 * dup_subtree_bytes / max(1, serialized_bytes), 1),
            "largest_repeat": {"where": biggest_subtree[0], "bytes": biggest_subtree[1], "seen_at_turn": biggest_subtree[2]},
        },
    }


def measure_loop_carriage(rows: list[dict], rounds: int = 3) -> dict:
    """#1926's observed shape: one turn whose main loop makes K model calls.
    Every call re-sends system + replayed history + all earlier rounds
    (agent_loop.py:410-728 accumulates on one message list)."""
    replayed = replay_history(rows)
    system = {"role": "system", "content": "S" * 4096}
    user = {"role": "user", "content": "U" * 512}
    per_round: list[int] = []
    running = [system, *replayed, user]
    for i in range(rounds):
        per_round.append(_count_model_context_tokens(running))
        running = running + [
            {"role": "assistant", "content": "A" * 512, "tool_calls": [make_tool_call(f"c{i}", "mastery_status")]},
            {"role": "tool", "tool_call_id": f"c{i}", "name": "mastery_status", "content": cjson(status_payload(build_map(6, 8, 1, 0), 1, 1, False))},
        ]
    unique_bytes = len(cjson(running).encode("utf-8"))
    total = sum(per_round)
    return {
        "rounds": rounds,
        "per_round_tokens_est": per_round,
        "total_tokens_est": total,
        "history_carried_per_round_tokens_est": _count_model_context_tokens(replayed),
        "duplication_ratio": round(total / max(1, per_round[0]), 2),
        "final_merged_bytes": unique_bytes,
    }


def measure_snapshot_accumulation(n_turns: int, snapshot_bytes: int = 220) -> dict:
    """Runtime snapshots (prompt_blocks.py:27-40, pipeline.py:515-527): a new
    ``_context_snapshot`` user row is appended whenever a runtime block changes;
    earlier copies remain in the replayed history verbatim."""
    rows = build_session_rows(n_turns, 6, 8)
    replayed = replay_history(rows)
    snaps = [m for m in replayed if isinstance(m.get("_context_snapshot"), str)]
    snap_bytes = sum(len(cjson(m).encode("utf-8")) for m in snaps)
    total = len(cjson(replayed).encode("utf-8"))
    return {
        "turns": n_turns,
        "snapshot_rows_retained": len(snaps),
        "snapshot_bytes": snap_bytes,
        "history_bytes": total,
        "snapshot_share_pct": round(100.0 * snap_bytes / max(1, total), 2),
        "distinct_snapshot_values": len({m["content"] for m in snaps}),
    }


def measure_status_payload_anatomy(n_modules: int = 6, kps: int = 8) -> dict:
    """Which top-level keys of one mastery_status payload carry the bytes, and
    which keys are byte-identical between two consecutive status calls that
    differ only by one graded knowledge point (the volatile/fracture set)."""
    m1 = build_map(n_modules, kps, 3, progressed=4)
    m2 = build_map(n_modules, kps, 3, progressed=5)
    p1 = status_payload(m1, 3, 6, False)
    p2 = status_payload(m2, 3, 7, False)
    keys = {}
    stable_keys = []
    for key in p1:
        size = len(cjson(p1[key]).encode("utf-8"))
        keys[key] = size
        if cjson(p1[key]) == cjson(p2.get(key)):
            stable_keys.append(key)
    total = sum(keys.values())
    stable_bytes = sum(keys[k] for k in stable_keys)
    # KP-entry granularity inside map: two consecutive status calls whose only
    # difference is one graded knowledge point. How much of map's byte volume
    # is per-KP entries identical in both calls?
    kp_sizes_1: dict[str, int] = {}
    for mod in m1["modules"]:
        for kp in mod["knowledge_points"]:
            kp_sizes_1[kp["id"]] = len(cjson(kp).encode("utf-8"))
    kp_ids_2 = {
        kp["id"]: cjson(kp)
        for mod in m2["modules"]
        for kp in mod["knowledge_points"]
    }
    map_bytes = keys["map"]
    identical_kp_bytes = 0
    for mod in m1["modules"]:
        for kp in mod["knowledge_points"]:
            if kp_ids_2.get(kp["id"]) == cjson(kp):
                identical_kp_bytes += kp_sizes_1[kp["id"]]
    return {
        "payload_bytes": total,
        "bytes_by_key": dict(sorted(keys.items(), key=lambda kv: -kv[1])),
        "unchanged_between_consecutive_calls": stable_keys,
        "stable_bytes": stable_bytes,
        "stable_share_pct": round(100.0 * stable_bytes / max(1, total), 1),
        "map_kp_entry_stability_pct": round(100.0 * identical_kp_bytes / max(1, map_bytes), 1),
        "map_kp_entry_identical_bytes": identical_kp_bytes,
        "map_bytes": map_bytes,
    }


def main() -> int:
    global TOKEN_ENGINE
    TOKEN_ENGINE = _detect_token_engine()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).parent / "results.json"))
    args = parser.parse_args()

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()

    scenarios: list[dict] = [measure_rows(dialogue_only_rows(20), "dialogue-only baseline (20 turns, no mastery tools)")]
    for label, n_modules, kps in (("S", 3, 5), ("M", 6, 8), ("L", 10, 12)):
        for turns in (5, 10, 20):
            rows = build_session_rows(turns, n_modules, kps)
            scenarios.append(measure_rows(rows, f"mastery {label} ({n_modules}x{kps}, {turns} turns)"))

    carriage = {f"turns={t}": measure_loop_carriage(build_session_rows(t, 6, 8)) for t in (10, 20)}
    snapshots = {f"turns={t}": measure_snapshot_accumulation(t) for t in (5, 10, 20)}
    anatomy = measure_status_payload_anatomy()

    results = {
        "meta": {
            "repo_head": head,
            "token_estimator": TOKEN_ENGINE,
            "fixture": "shape-faithful mastery tool payloads; replayed via real replay_history",
            "offline": True,
            "python": platform.python_version(),
        },
        "scenarios": scenarios,
        "loop_carriage": carriage,
        "snapshot_accumulation": snapshots,
        "status_payload_anatomy": anatomy,
    }
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Console summary
    print(f"token estimator: {TOKEN_ENGINE}; repo head {head[:12]}")
    hdr = f"{'scenario':46s} {'turns':>5} {'msgs':>5} {'bytes':>9} {'tok~':>7} {'toolres%':>8} {'dupMsg%':>8} {'dupSub%':>8}"
    print(hdr)
    for s in scenarios:
        print(
            f"{s['scenario'][:46]:46s} {s['turns']:>5} {s['replayed_messages']:>5} "
            f"{s['replayed_bytes_serialized']:>9} {s['replayed_tokens_est']:>7} "
            f"{s['tool_result_share_pct']:>8} {s['exact_duplicate_messages']['share_pct']:>8} "
            f"{s['exact_duplicate_subtrees']['share_pct']:>8}"
        )
    for k, v in carriage.items():
        print(f"carriage {k}: per-round={[round(x) for x in v['per_round_tokens_est']]} "
              f"total={v['total_tokens_est']} ratio={v['duplication_ratio']}")
    for k, v in snapshots.items():
        print(f"snapshots {k}: retained={v['snapshot_rows_retained']} "
              f"bytes={v['snapshot_bytes']} share={v['snapshot_share_pct']}%")
    a = results["status_payload_anatomy"]
    print(f"status payload anatomy: total={a['payload_bytes']}B map={a['map_bytes']}B "
          f"stable-keys={a['stable_share_pct']}% "
          f"kp-entries-identical={a['map_kp_entry_stability_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
