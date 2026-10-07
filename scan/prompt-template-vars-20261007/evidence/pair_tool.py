#!/usr/bin/env python3
"""Pair prompt-template keys with call sites; classify placeholder drift.

Usage: pair_tool.py <repo-checkout> <scan_raw.json> <out.json>
Read-only: the checkout is only read, never written.
"""
from __future__ import annotations

import json
import re
import string
import sys
from difflib import SequenceMatcher
from pathlib import Path

import yaml

REPO = Path(sys.argv[1]).resolve()
RAW = Path(sys.argv[2])
OUT = Path(sys.argv[3])

FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]]+\])*$")


def fields(text: str):
    named, bad = set(), []
    try:
        for _, field, _, _ in string.Formatter().parse(text):
            if field is None:
                continue
            if FIELD_RE.match(field):
                named.add(field)
            else:
                bad.append(field)
    except ValueError as e:
        bad.append(f"<unparseable:{e}>")
    return named, bad


def walk(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, str):
                yield path, v
            elif isinstance(v, (dict, list)):
                yield from walk(v, path)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, prefix)


def per_key(rel: str) -> dict[str, set[str]]:
    f = REPO / rel
    out: dict[str, set[str]] = {}
    if f.suffix == ".md":
        named, _ = fields(f.read_text(encoding="utf-8"))
        out["__file__"] = named
        return out
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    for path, s in walk(data):
        named, _ = fields(s)
        if named:
            out[path] = named
    return out


def lang_pair(rel: str) -> tuple[str, str]:
    """(zh_variant, en_canonical) template paths for one pairing entry."""
    if rel.endswith("/en.yaml"):
        return rel[: -len("en.yaml")] + "zh.yaml", rel
    return rel.replace("/en/", "/zh/"), rel


# ------------------------------------------------------------------ table
P: list[dict] = []


def add(tpl, call, line, key, provided):
    P.append({"tpl": tpl, "call": call, "line": line, "key": key,
              "provided": sorted(provided) if provided is not None else None})


# ---- chat pack (agents/chat/prompts/{en,zh}/agentic_chat.yaml), consumed by
# AgentChatLoop pipeline + prompt blocks + capability system_block overrides.
CHAT = "deeptutor/agents/chat/prompts/en/agentic_chat.yaml"
add(CHAT, "deeptutor/agents/loop/pipeline.py", 1126, "notices.too_many_tool_calls", {"requested", "limit"})
add(CHAT, "deeptutor/agents/loop/pipeline.py", 1112, "notices.tool_error", {"tool", "error"})
add(CHAT, "deeptutor/agents/loop/pipeline.py", 1151, "notices.tool_error", {"tool", "error"})
add(CHAT, "deeptutor/agents/loop/agent_loop.py", 827, "notices.loop_error_finish", {"error"})
add(CHAT, "deeptutor/agents/loop/prompt_blocks.py", 137, "tool_call_policy", {"limit"})
add(CHAT, "deeptutor/agents/loop/prompt_blocks.py", 218, "general_partner", {"name"})
add(CHAT, "deeptutor/agents/loop/prompt_blocks.py", 224, "general_partner_description", {"description"})
add(CHAT, "deeptutor/agents/loop/prompt_blocks.py", 256, "runtime_context", {"datetime"})
add(CHAT, "deeptutor/agents/loop/prompt_blocks.py", 276, "loop.user", {"user_message"})
add(CHAT, "deeptutor/capabilities/solve/loop.py", 46, "solve.system", set())
add(CHAT, "deeptutor/capabilities/setup/capability.py", 58, "setup.system", set())
add(CHAT, "deeptutor/capabilities/ima/capability.py", 54, "ima.system", set())
add(CHAT, "deeptutor/capabilities/marginnote4/capability.py", 50, "marginnote4.system", set())
add(CHAT, "deeptutor/capabilities/obsidian/capability.py", 50, "obsidian.system", set())
add(CHAT, "deeptutor/capabilities/mastery/loop.py", 236, "mastery.system", set())

# ---- math_animator agent packs (PromptManager agents)
MA = "deeptutor/agents/math_animator/prompts/en/"
add(MA + "code_generator_agent.yaml", "deeptutor/agents/math_animator/agents/code_generator_agent.py", 80, "generate_user_template", {"user_input", "output_mode", "duration_requirement", "analysis_json", "design_json"})
add(MA + "code_generator_agent.yaml", "deeptutor/agents/math_animator/agents/code_generator_agent.py", 120, "retry_user_template", {"user_input", "output_mode", "attempt", "duration_requirement", "error_message", "current_code"})
add(MA + "code_generator_agent.yaml", "deeptutor/agents/math_animator/agents/code_generator_agent.py", 75, "generate_system", set())
add(MA + "code_generator_agent.yaml", "deeptutor/agents/math_animator/agents/code_generator_agent.py", 115, "retry_system", set())
add(MA + "concept_analysis_agent.yaml", "deeptutor/agents/math_animator/agents/concept_analysis_agent.py", 58, "user_template", {"user_input", "history_context", "output_mode", "style_hint", "reference_count"})
add(MA + "concept_analysis_agent.yaml", "deeptutor/agents/math_animator/agents/concept_analysis_agent.py", 52, "user_template", {"user_input", "history_context", "output_mode", "style_hint", "reference_count"})
add(MA + "concept_analysis_agent.yaml", "deeptutor/agents/math_animator/agents/concept_analysis_agent.py", 40, "system", set())
add(MA + "concept_design_agent.yaml", "deeptutor/agents/math_animator/agents/concept_design_agent.py", 44, "user_template", {"user_input", "output_mode", "style_hint", "analysis_json"})
add(MA + "concept_design_agent.yaml", "deeptutor/agents/math_animator/agents/concept_design_agent.py", 39, "system", set())
add(MA + "summary_agent.yaml", "deeptutor/agents/math_animator/agents/summary_agent.py", 45, "user_template", {"user_input", "output_mode", "analysis_json", "design_json", "render_json"})
add(MA + "summary_agent.yaml", "deeptutor/agents/math_animator/agents/summary_agent.py", 40, "system", set())
add(MA + "visual_review_agent.yaml", "deeptutor/agents/math_animator/agents/visual_review_agent.py", 62, "user_template", {"user_input", "output_mode", "reviewed_frames", "render_json", "current_code"})
add(MA + "visual_review_agent.yaml", "deeptutor/agents/math_animator/agents/visual_review_agent.py", 57, "system", set())
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 112, "status.code_prepared", set())
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 120, "status.retry", {"attempt", "error"})
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 153, "status.rendering", {"mode", "quality"})
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 189, "status.artifacts_one", {"count"})
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 189, "status.artifacts_many", {"count"})
add(MA + "math_animator.yaml", "deeptutor/agents/math_animator/capability.py", 306, "status.llm_call_failed", set())

# ---- notebook
NB = "deeptutor/agents/notebook/prompts/en/"
add(NB + "analysis_agent.yaml", "deeptutor/agents/notebook/analysis_agent.py", 302, "thinking.user_template", {"user_question", "catalog"})
add(NB + "analysis_agent.yaml", "deeptutor/agents/notebook/analysis_agent.py", 313, "acting.user_template", {"user_question", "thinking_text", "catalog"})
add(NB + "analysis_agent.yaml", "deeptutor/agents/notebook/analysis_agent.py", 342, "observing.user_template", {"user_question", "thinking_text", "detailed_blocks"})
add(NB + "summarize_agent.yaml", "deeptutor/agents/notebook/summarize_agent.py", 105, "user_template", {"record_type", "record_hint", "title", "user_query", "output", "metadata"})

# ---- question
Q = "deeptutor/agents/question/prompts/en/"
QP = "deeptutor/agents/question/pipeline.py"
add(Q + "followup_agent.yaml", "deeptutor/agents/question/agents/followup_agent.py", 46, "answer_followup", {"question_context", "history_context", "user_message"})
add(Q + "followup_agent.yaml", "deeptutor/agents/question/agents/followup_agent.py", 35, "system", set())
add(Q + "pipeline.yaml", QP, 645, "explore.system", {"kb_note", "tool_list", "num_questions"})
add(Q + "pipeline.yaml", QP, 657, "explore.user_template", {"user_message", "num_questions", "allowed_types", "per_type_counts", "difficulty", "attachments_summary", "conversation_context", "quiz_history"})
add(Q + "pipeline.yaml", QP, 720, "plan.system", {"num_questions"})
add(Q + "pipeline.yaml", QP, 722, "plan.user_template", {"user_message", "exploration_trace", "num_questions", "allowed_types", "per_type_counts", "difficulty"})
add(Q + "pipeline.yaml", QP, 797, "notices.plan_count_mismatch", {"got", "requested"})
add(Q + "pipeline.yaml", QP, 890, "quiz_step.system", {"question_number", "total_questions", "kb_note", "tool_list"})
add(Q + "pipeline.yaml", QP, 898, "quiz_step.user_template", {"question_id", "topic", "question_type", "difficulty", "exploration_trace", "plan_summary", "previous_questions", "reference_block"})
add(Q + "pipeline.yaml", QP, 982, "repair.user_template", {"question_id", "topic", "question_type", "difficulty", "invalid_payload", "issues"})
add(Q + "pipeline.yaml", QP, 1069, "tool_summarizer.user_template", {"tool_result"})
add(Q + "pipeline.yaml", QP, 1145, "notices.tool_summarizer_failed", {"error"})
add(Q + "pipeline.yaml", QP, 1225, "trace.iteration_tool_call", {"n", "tool"})
add(Q + "pipeline.yaml", QP, 1245, "trace.iteration_thought", {"n"})
add(Q + "pipeline.yaml", QP, 1255, "trace.iteration_tool_result", {"n", "tool"})
add(Q + "pipeline.yaml", QP, 2063, "notices.too_many_tool_calls", {"requested", "limit"})
add(Q + "pipeline.yaml", QP, 2087, "notices.tool_error", {"tool", "error"})
add(Q + "deep_question.yaml", "deeptutor/agents/question/capability.py", 56, "status.topic_required", set())
add(Q + "deep_question.yaml", "deeptutor/agents/question/capability.py", 137, "status.topic_required", set())
add(Q + "deep_question.yaml", "deeptutor/agents/question/capability.py", 264, "status.parsing_uploaded", set())
add(Q + "deep_question.yaml", "deeptutor/agents/question/capability.py", 299, "status.parsing_directory", set())
add(Q + "deep_question.yaml", "deeptutor/agents/question/capability.py", 348, "status.mimic_needs_paper", set())

# ---- research
RP = "deeptutor/agents/research/pipeline.py"
R = "deeptutor/agents/research/prompts/en/pipeline.yaml"
add(R, RP, 672, "notices.partial_results", {"failed", "total"})
add(R, RP, 785, "rephrase.system", {"max_rounds", "max_questions_per_round", "topic"})
add(R, RP, 791, "rephrase.user_template", {"topic"})
add(R, RP, 866, "decompose.user_template", {"topic", "num_subtopics"})
add(R, RP, 975, "research_step.system", {"topic", "block_title", "block_overview", "mode", "max_iterations", "kb_note", "tool_list"})
add(R, RP, 993, "research_step.user_template", {"accumulated_knowledge", "sibling_topics"})
add(R, RP, 1118, "system.obsidian_kb_system_note", {"kb_name"})
add(R, RP, 1144, "system.kb_system_note", {"kb_name", "kb_name_repr"})
add(R, RP, 1248, "note.user_template", {"tool_name", "query", "raw_answer"})
add(R, RP, 1321, "notices.report_incomplete", {"parts"})
add(R, RP, 1576, "report.outline.user_template", {"topic", "block_summaries"})
add(R, RP, 1745, "report.intro.system", {"section_number"})
add(R, RP, 1746, "report.intro.user_template", {"topic", "title", "section_number", "sections_overview"})
add(R, RP, 1788, "report.section.system", {"section_number"})
add(R, RP, 1789, "report.section.user_template", {"topic", "report_title", "section_id", "section_title", "section_intent", "section_number", "evidence"})
add(R, RP, 1836, "report.conclusion.system", {"section_number"})
add(R, RP, 1837, "report.conclusion.user_template", {"topic", "title", "section_number", "sections_recap"})
add(R, RP, 2757, "notices.tool_error", {"tool", "error"})
add(R, RP, 2923, "notices.append_rejected_full_progress", {"title"})
add(R, RP, 2948, "notices.append_rejected_dup_progress", {"title", "existing"})
add(R, RP, 2967, "notices.append_rejected_duplicate", {"existing_id", "existing_title"})
add(R, RP, 2985, "notices.append_accepted_progress", {"title", "new_block_id"})
add(R, RP, 3001, "notices.append_accepted", {"new_block_id", "title"})
add(R, RP, 3085, "notices.rephrase_only_ask_user", {"tool"})
add(R, RP, 3102, "notices.rephrase_cap_reached", {"max_rounds"})
add(R, RP, 3121, "notices.too_many_tool_calls", {"requested", "limit"})
add(R, RP, 3143, "notices.tool_error", {"tool", "error"})

# ---- visualize
V = "deeptutor/agents/visualize/prompts/en/"
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 73, "user_template_fixed", {"user_input", "history_context", "render_type"})
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 73, "user_template_figure", {"user_input", "history_context"})
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 73, "user_template", {"user_input", "history_context"})
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 53, "system_fixed", set())
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 58, "system_figure", set())
add(V + "analysis_agent.yaml", "deeptutor/agents/visualize/agents/analysis_agent.py", 61, "system", set())
add(V + "code_generator_agent.yaml", "deeptutor/agents/visualize/agents/code_generator_agent.py", 54, "user_template", {"user_input", "history_context", "render_type", "analysis_json"})
add(V + "code_generator_agent.yaml", "deeptutor/agents/visualize/agents/code_generator_agent.py", 45, "system_base", set())
add(V + "code_generator_agent.yaml", "deeptutor/agents/visualize/agents/code_generator_agent.py", 46, "rules_general", set())
add(V + "review_agent.yaml", "deeptutor/agents/visualize/agents/review_agent.py", 50, "repair_user_template", {"user_input", "render_type", "error", "analysis_json", "code"})
add(V + "review_agent.yaml", "deeptutor/agents/visualize/agents/review_agent.py", 45, "repair_system", set())
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 158, "status.tool_calling_disabled", {"target"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 202, "status.no_payload_tool_calling_disabled", {"target"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 208, "status.no_payload", set())
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 366, "status.manim_code_prepared", set())
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 374, "status.manim_retry", {"attempt", "error"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 407, "status.manim_rendering", {"mode", "quality"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 448, "status.manim_artifacts_one", {"count"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 448, "status.manim_artifacts_many", {"count"})
add(V + "visualize.yaml", "deeptutor/agents/visualize/capability.py", 564, "status.llm_call_failed", set())

# ---- book packs (load_book_prompts + get_book_prompt)
BOOK = "deeptutor/book/prompts/en/"
add(BOOK + "animation.yaml", "deeptutor/book/blocks/animation.py", 52, "context_summary", {"chapter_summary"})
add(BOOK + "animation.yaml", "deeptutor/book/blocks/animation.py", 57, "context_objectives", set())
add(BOOK + "animation.yaml", "deeptutor/book/blocks/animation.py", 63, "focus_clause", {"focus"})
add(BOOK + "animation.yaml", "deeptutor/book/blocks/animation.py", 66, "brief", {"chapter_title", "focus_clause"})
add(BOOK + "animation.yaml", "deeptutor/book/blocks/animation.py", 49, "system", set())
add(BOOK + "callout.yaml", "deeptutor/book/blocks/callout.py", 40, "user_template", {"chapter_title", "chapter_summary", "objectives_inline", "variant", "label"})
add(BOOK + "callout.yaml", "deeptutor/book/blocks/callout.py", 49, "system", set())
add(BOOK + "code.yaml", "deeptutor/book/blocks/code.py", 76, "user_template", {"chapter_title", "chapter_summary", "objectives_inline", "intent", "language"})
add(BOOK + "code.yaml", "deeptutor/book/blocks/code.py", 85, "system", set())
add(BOOK + "deep_dive.yaml", "deeptutor/book/blocks/deep_dive.py", 33, "user_template", {"chapter_title", "chapter_summary"})
add(BOOK + "deep_dive.yaml", "deeptutor/book/blocks/deep_dive.py", 39, "system", set())
add(BOOK + "figure.yaml", "deeptutor/book/blocks/figure.py", 45, "context_summary", {"chapter_summary"})
add(BOOK + "figure.yaml", "deeptutor/book/blocks/figure.py", 50, "context_objectives", set())
add(BOOK + "figure.yaml", "deeptutor/book/blocks/figure.py", 56, "focus_clause", {"focus"})
add(BOOK + "figure.yaml", "deeptutor/book/blocks/figure.py", 59, "brief", {"chapter_title", "focus_clause", "variant"})
add(BOOK + "figure.yaml", "deeptutor/book/blocks/figure.py", 61, "system", set())
add(BOOK + "flash_cards.yaml", "deeptutor/book/blocks/flash_cards.py", 33, "system_template", {"count"})
add(BOOK + "flash_cards.yaml", "deeptutor/book/blocks/flash_cards.py", 34, "user_template", {"chapter_title", "chapter_summary", "objectives_inline"})
add(BOOK + "interactive.yaml", "deeptutor/book/blocks/interactive.py", 45, "context_summary", {"chapter_summary"})
add(BOOK + "interactive.yaml", "deeptutor/book/blocks/interactive.py", 50, "context_objectives", set())
add(BOOK + "interactive.yaml", "deeptutor/book/blocks/interactive.py", 56, "focus_clause", {"focus"})
add(BOOK + "interactive.yaml", "deeptutor/book/blocks/interactive.py", 59, "brief", {"chapter_title", "focus_clause", "interaction"})
add(BOOK + "interactive.yaml", "deeptutor/book/blocks/interactive.py", 61, "system", set())
add(BOOK + "section.yaml", "deeptutor/book/blocks/section.py", 194, "outline_user", {"chapter_title", "chapter_summary", "objectives_block", "focus_topic", "section_role", "target_words", "rag_section"})
add(BOOK + "section.yaml", "deeptutor/book/blocks/section.py", 206, "outline_system", set())
add(BOOK + "section.yaml", "deeptutor/book/blocks/section.py", 294, "subsection_user", {"chapter_title", "section_focus", "outline_intro", "heading", "role", "focus", "target_words", "evidence_section"})
add(BOOK + "section.yaml", "deeptutor/book/blocks/section.py", 307, "subsection_system", set())
add(BOOK + "text.yaml", "deeptutor/book/blocks/text.py", 56, "user_template", {"chapter_title", "chapter_summary", "objectives_block", "role", "previous_section", "rag_section"})
add(BOOK + "text.yaml", "deeptutor/book/blocks/text.py", 66, "system", set())
add(BOOK + "text.yaml", "deeptutor/book/blocks/text.py", 101, "bridge_user_template", {"chapter_title", "previous_block_summary", "next_block_hint"})
add(BOOK + "text.yaml", "deeptutor/book/blocks/text.py", 108, "bridge_system", set())
add(BOOK + "timeline.yaml", "deeptutor/book/blocks/timeline.py", 31, "user_template", {"chapter_title", "chapter_summary"})
add(BOOK + "timeline.yaml", "deeptutor/book/blocks/timeline.py", 33, "system", set())
add(BOOK + "page_planner.yaml", "deeptutor/book/agents/page_planner.py", 276, "architect_user", {"chapter_title", "chapter_summary", "content_type", "objectives_block", "exploration_summary"})
add(BOOK + "page_planner.yaml", "deeptutor/book/agents/page_planner.py", 262, "architect_system", {"block_catalog"})
add(BOOK + "ideation_agent.yaml", "deeptutor/book/agents/ideation_agent.py", 56, "user_template", {"ideation_context"})
add(BOOK + "ideation_agent.yaml", "deeptutor/book/agents/ideation_agent.py", 53, "system", set())
add(BOOK + "source_explorer.yaml", "deeptutor/book/agents/source_explorer.py", 294, "queries_user", {"user_intent", "proposal_block", "kb_list", "extra_context"})
add(BOOK + "source_explorer.yaml", "deeptutor/book/agents/source_explorer.py", 259, "queries_system", set())
add(BOOK + "source_explorer.yaml", "deeptutor/book/agents/source_explorer.py", 699, "summary_user", {"user_intent", "proposal_title", "proposal_scope", "coverage_block", "chunks_block"})
add(BOOK + "source_explorer.yaml", "deeptutor/book/agents/source_explorer.py", 684, "summary_system", set())
add(BOOK + "spine_agent.yaml", "deeptutor/book/agents/spine_agent.py", 69, "user_template", {"proposal_block", "source_material"})
add(BOOK + "spine_agent.yaml", "deeptutor/book/agents/spine_agent.py", 59, "system", set())
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 195, "draft_user", {"proposal_block", "exploration_summary", "candidate_concepts", "chunks_block"})
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 193, "draft_system", set())
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 219, "critique_user", {"proposal_block", "exploration_summary", "draft_block"})
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 215, "critique_system", set())
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 244, "revise_user", {"proposal_block", "critique_block", "draft_block"})
add(BOOK + "spine_synthesizer.yaml", "deeptutor/book/agents/spine_synthesizer.py", 240, "revise_system", set())

# ---- learning (learning/prompts/{en,zh}.yaml via prompt_text paths)
LEARN = "deeptutor/learning/prompts/en.yaml"
add(LEARN, "deeptutor/learning/prompts.py", 58, "notebook.user", {"records_json"})
add(LEARN, "deeptutor/learning/prompts.py", 107, "topic.user", {"name", "goal", "sources_json", "must_cover_block"})
add(LEARN, "deeptutor/learning/prompts.py", 106, "topic.system", {"module_limit"})
add(LEARN, "deeptutor/learning/prompts.py", 117, "notebook.default_module_name", {"index"})

# ---- memory consolidator (load_prompt -> consolidator/prompts/{lang}/<n>.yaml)
MEM = "deeptutor/services/memory/consolidator/prompts/en/"
add(MEM + "audit_l2.yaml", "deeptutor/services/memory/consolidator/modes/audit.py", 175, "system", {"user_label", "surface", "focus", "today"})
add(MEM + "audit_l2.yaml", "deeptutor/services/memory/consolidator/modes/audit.py", 181, "user", {"surface", "chunk"})
add(MEM + "audit_l3.yaml", "deeptutor/services/memory/consolidator/modes/audit.py", 316, "system", {"user_label", "slot", "focus", "today"})
add(MEM + "audit_l3.yaml", "deeptutor/services/memory/consolidator/modes/audit.py", 322, "user", {"slot", "chunk"})
add(MEM + "dedup.yaml", "deeptutor/services/memory/consolidator/modes/dedup.py", 126, "system", {"user_label", "today"})
add(MEM + "dedup.yaml", "deeptutor/services/memory/consolidator/modes/dedup.py", 127, "user", {"doc", "iteration", "iterations_total"})
add(MEM + "update_l2.yaml", "deeptutor/services/memory/consolidator/modes/update.py", 231, "system", {"user_label", "surface", "sections", "focus", "today"})
add(MEM + "update_l2.yaml", "deeptutor/services/memory/consolidator/modes/update.py", 245, "user", {"surface", "existing", "chunk", "chunk_index", "chunk_total", "chunk_start", "chunk_end"})
add(MEM + "update_l3.yaml", "deeptutor/services/memory/consolidator/modes/update.py", 459, "system", {"user_label", "slot", "sections", "focus", "today"})
add(MEM + "update_l3.yaml", "deeptutor/services/memory/consolidator/modes/update.py", 478, "user", {"slot", "existing", "chunk", "chunk_index", "chunk_total"})

# ---- co_writer (BaseAgent module co_writer)
CW = "deeptutor/co_writer/prompts/en/"
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 167, "system", {"available_tools"})
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 176, "action_template", {"action_verb", "instruction"})
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 182, "context_template", {"context", "source_label"})
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 191, "user_template", {"text"})
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 335, "auto_mark_system", set())
add(CW + "edit_agent.yaml", "deeptutor/co_writer/edit_agent.py", 339, "auto_mark_user_template", {"text"})

# ---- capability prompt files
CAP = "deeptutor/capabilities/"
add(CAP + "ima/prompts/en/system.md", "deeptutor/capabilities/ima/capability.py", 61, "__file__", {"kb_names"})
add(CAP + "marginnote4/prompts/en/system.md", "deeptutor/capabilities/marginnote4/capability.py", 52, "__file__", {"library_name"})
add(CAP + "obsidian/prompts/en/system.md", "deeptutor/capabilities/obsidian/capability.py", 52, "__file__", {"vault_name"})
add(CAP + "reading/prompts/en/reading.yaml", "deeptutor/capabilities/reading/capability.py", 221, "material_facts", {"summary", "unit", "unit_count", "annotations"})
add(CAP + "course_study/prompts/en/course_study.yaml", "deeptutor/capabilities/course_study/capability.py", 408, "course_facts", {"course_id"})
add(CAP + "explore_context/prompts/en/explore_context.yaml", "deeptutor/capabilities/explore_context/explorer.py", 186, "loop.system", {"tool_call_limit"})
add(CAP + "explore_context/prompts/en/explore_context.yaml", "deeptutor/capabilities/explore_context/explorer.py", 196, "loop.user_template", {"question", "mode", "manifest"})
add(CAP + "explore_context/prompts/en/explore_context.yaml", "deeptutor/capabilities/explore_context/explorer.py", 449, "user_template", {"question", "mode", "manifest", "sources"})
add(CAP + "explore_context/prompts/en/explore_context.yaml", "deeptutor/capabilities/explore_context/explorer.py", 446, "system", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/capabilities/mastery/loop.py", 549, "general", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/capabilities/mastery/loop.py", 549, "runtime_policy", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/capabilities/mastery/loop.py", 549, "loop.system", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/capabilities/mastery/loop.py", 549, "playbook", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/capabilities/mastery/tools.py", 597, "session", set())
add(CAP + "mastery/prompts/en/mastery_loop.yaml", "deeptutor/agents/loop/prompt_blocks.py", 276, "loop.user", {"user_message"})
add("deeptutor/capabilities/prompts/en/audio_overview.yaml", "deeptutor/capabilities/audio_overview/capability.py", 44, "status.missing_kb", set())
add("deeptutor/capabilities/prompts/en/audio_overview.yaml", "deeptutor/capabilities/audio_overview/capability.py", 56, "status.missing_workspace", set())
add("deeptutor/agents/vision_solver/prompts/geogebra.md", "deeptutor/agents/vision_solver/vision_solver_agent.py", 41, "__file__", set())
add("deeptutor/capabilities/ask_questions/prompts/en/system.md", "deeptutor/capabilities/ask_questions/loop.py", 49, "__file__", set())
add("deeptutor/capabilities/solve/prompts/en/system.md", "deeptutor/capabilities/solve/loop.py", 79, "__file__", set())
add("deeptutor/capabilities/setup/prompts/en/system.md", "deeptutor/capabilities/setup/capability.py", 104, "__file__", set())
add("deeptutor/capabilities/partner_authoring/prompts/en/system.md", "deeptutor/capabilities/partner_authoring/capability.py", 38, "__file__", set())
add("deeptutor/capabilities/partner_authoring/prompts/en/heuristic.md", "deeptutor/capabilities/partner_authoring/capability.py", 38, "__file__", set())
add("deeptutor/capabilities/partner_group/prompts/en/system.md", "deeptutor/capabilities/partner_group/capability.py", 59, "__file__", set())
add("deeptutor/capabilities/partner_group/prompts/en/invoke_other.md", "deeptutor/capabilities/partner_group/capability.py", 61, "__file__", set())


def similar(a: str, b: str) -> float:
    base_a, base_b = a.split(".")[-1], b.split(".")[-1]
    return SequenceMatcher(None, base_a, base_b).ratio()


def main():
    cache: dict[str, dict[str, set]] = {}

    def keys_for(rel: str) -> dict[str, set]:
        if rel not in cache:
            cache[rel] = per_key(rel)
        return cache[rel]

    findings = []
    paired_files = {p["tpl"] for p in P}
    for p in P:
        zh_rel, en_rel = lang_pair(p["tpl"])
        for lang, rel in (("zh", zh_rel), ("en", en_rel)):
            if not (REPO / rel).exists():
                findings.append({"class": "FILE_MISSING", "lang": lang, "en_rel": en_rel,
                                 "call": p["call"], "line": p["line"], "key": p["key"]})
                continue
            km = keys_for(rel)
            ph = km.get(p["key"])
            provided = set(p["provided"]) if p["provided"] is not None else set()
            if ph is None:
                if provided:
                    findings.append({"class": "KEY_MISSING_IN_TEMPLATE", "lang": lang, "tpl": rel,
                                     "en_rel": en_rel, "call": p["call"], "line": p["line"],
                                     "key": p["key"], "provided": sorted(provided)})
                continue
            missing, extra = ph - provided, provided - ph
            drift = [e for e in extra if max((similar(e, m) for m in missing), default=0.0) >= 0.75]
            entry = {"lang": lang, "tpl": rel, "en_rel": en_rel, "call": p["call"], "line": p["line"],
                     "key": p["key"], "placeholders": sorted(ph), "provided": sorted(provided)}
            if missing:
                findings.append({**entry, "class": "MISSING_PARAM", "missing": sorted(missing)})
            if extra:
                cls = "NAMING_DRIFT" if drift else "EXTRA_PARAM"
                findings.append({**entry, "class": cls, "extra": sorted(extra), "drift": sorted(drift)})

    # zh/en placeholder divergence per paired template
    for rel in sorted(paired_files):
        zh_rel, en_rel = lang_pair(rel)
        if zh_rel == en_rel or not (REPO / zh_rel).exists() or not (REPO / en_rel).exists():
            continue
        kz, ke = keys_for(zh_rel), keys_for(en_rel)
        for k in sorted(set(kz) | set(ke)):
            zs, es = kz.get(k, set()), ke.get(k, set())
            if zs != es:
                findings.append({"class": "ZH_EN_DIVERGENCE", "tpl": en_rel, "key": k,
                                 "zh_only": sorted(zs - es), "en_only": sorted(es - zs)})

    # residual: placeholder-bearing keys in paired files with no pairing entry
    referenced: dict[str, set[str]] = {}
    for p in P:
        zh_rel, en_rel = lang_pair(p["tpl"])
        for rel in (zh_rel, en_rel):
            referenced.setdefault(rel, set()).add(p["key"])
    for rel in sorted(referenced):
        if not (REPO / rel).exists():
            continue
        for k, ph in sorted(keys_for(rel).items()):
            if k in referenced[rel]:
                continue
            findings.append({"class": "PLACEHOLDER_WITHOUT_PAIRING", "tpl": rel, "key": k,
                             "placeholders": sorted(ph)})

    # orphan templates: files carrying placeholders but no pairing at all
    all_tpl = {t["file"] for t in json.loads(RAW.read_text())["templates"]}
    for rel in sorted(all_tpl - set(referenced)):
        if rel.endswith("_meta.yaml"):
            continue
        km = keys_for(rel)
        if km:
            findings.append({"class": "ORPHAN_TEMPLATE", "tpl": rel,
                             "keys": {k: sorted(v) for k, v in sorted(km.items())}})

    OUT.write_text(json.dumps({"pairings": len(P), "findings": findings, "table": P},
                              ensure_ascii=False, indent=1))
    print(f"pairings={len(P)} findings={len(findings)}")


if __name__ == "__main__":
    main()
