"""MarginNote loop capability — agentic retrieval over a live MN4 notebook."""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.marginnote.binding import marginnote_notebook_refs, notebook_for_turn
from deeptutor.capabilities.marginnote.tools import MARGINNOTE_TOOL_NAMES
from deeptutor.capabilities.protocol import KnowledgeCapability, PromptBlock
from deeptutor.core.context import UnifiedContext


class MarginNoteCapability(KnowledgeCapability):
    """Turn-scoped integration for a connected MarginNote 4 notebook."""

    name = "marginnote"
    owned_tools = MARGINNOTE_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return notebook_for_turn(context) is not None

    def owned_kbs(self, context: UnifiedContext) -> set[str]:
        return marginnote_notebook_refs(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        binding = notebook_for_turn(context)
        if binding is None:
            return None
        override = _prompt_text(prompts, ("marginnote", "system"))
        content = override or _load_system_prompt(language)
        content = content.replace("{notebook_name}", binding["name"])
        mastery = _mastery_status_note(context)
        if mastery:
            content = f"{content}\n\n{mastery}"
        return PromptBlock("marginnote", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name not in MARGINNOTE_TOOL_NAMES:
            return kwargs
        binding = notebook_for_turn(context)
        if binding is None:
            return kwargs
        updated = dict(kwargs)
        updated["_notebook_path"] = binding["path"]
        updated["_adapter"] = binding["adapter"]
        updated["_writeback_path"] = binding["writeback_path"]
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        if path_id:
            updated["_mastery_path_id"] = path_id
        return updated

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


def _mastery_status_note(context: UnifiedContext) -> str:
    path_id = str(context.metadata.get("mastery_path_id") or "").strip()
    if not path_id:
        return ""
    try:
        from deeptutor.learning.policy import map_summary
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(path_id)
    except Exception:
        return ""
    if progress is None:
        return ""
    summary = map_summary(progress)
    counts = summary.get("counts") or {}
    return (
        "## Active mastery path\n\n"
        f"Path `{path_id}` is attached to this turn. "
        f"Mastered {counts.get('mastered', 0)}/{counts.get('total', 0)} "
        "knowledge points. When writing a summary back to MarginNote, include "
        "this path id in the note frontmatter."
    )


__all__ = ["MarginNoteCapability"]
