"""Interactive block – self-contained interactive HTML widget.

Wraps :class:`deeptutor.agents.visualize.pipeline.VisualizePipeline` with
``render_mode="html"``. The payload carries an HTML document the frontend
renders in an isolated iframe.

The draft is checked by the deterministic local ``validate_visualization``.
HTML has no repair pass (full single-file documents are too large for a
useful targeted fix), so an unrenderable document raises
``GenerationFailure`` and lets the book engine retry — better than baking a
placeholder page into the book.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from ..models import BlockType, ObjectiveReference, SourceAnchor
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, GenerationFailure

logger = logging.getLogger(__name__)


def _objective_references(objectives: Any) -> list[ObjectiveReference]:
    """Create stable ids for objective text without changing the source model.

    Hashing only the normalized text intentionally gives identical objectives
    in different chapters the same id. A regenerate that keeps the objective
    wording also keeps its evidence linkage.
    """

    references: list[ObjectiveReference] = []
    seen: set[str] = set()
    for raw in objectives or []:
        label = " ".join(str(raw or "").strip().split())
        if not label:
            continue
        digest = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:16]
        objective_id = f"obj_{digest}"
        if objective_id in seen:
            continue
        seen.add(objective_id)
        references.append(ObjectiveReference(id=objective_id, label=label))
    return references


class InteractiveGenerator(BlockGenerator):
    block_type = BlockType.INTERACTIVE

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        params = ctx.block.params
        chapter_title = params.get("chapter_title", ctx.chapter.title)
        chapter_summary = params.get("chapter_summary", ctx.chapter.summary)
        objectives = params.get("objectives") or ctx.chapter.learning_objectives
        objective_refs = _objective_references(objectives)
        focus = str(params.get("focus") or "")
        interaction = str(params.get("interaction") or "interactive")
        prompts = load_book_prompts("interactive", ctx.language)

        history_lines: list[str] = []
        if chapter_summary:
            history_lines.append(
                get_book_prompt(prompts, "context_summary")
                .strip()
                .format(chapter_summary=chapter_summary)
            )
        if objectives:
            history_lines.append(get_book_prompt(prompts, "context_objectives").strip())
            for obj in objectives:
                history_lines.append(f"- {obj}")
        history_context = "\n".join(history_lines)

        focus_clause = (
            get_book_prompt(prompts, "focus_clause").rstrip().format(focus=focus) if focus else ""
        )
        user_input = (
            get_book_prompt(prompts, "brief")
            .strip()
            .format(
                interaction=interaction,
                chapter_title=chapter_title,
                focus_clause=focus_clause,
            )
        )
        if objective_refs:
            activity_bridge = get_book_prompt(prompts, "activity_bridge").strip()
            user_input = (
                user_input
                + "\n\n"
                + activity_bridge.format(
                    objective_ids=json.dumps([ref.id for ref in objective_refs])
                )
            )

        try:
            from deeptutor.agents.visualize.pipeline import VisualizePipeline
            from deeptutor.agents.visualize.utils import validate_visualization
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            pipeline = VisualizePipeline(
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_version=llm_config.api_version,
                language=ctx.language,
            )
            analysis = await pipeline.run_analysis(
                user_input=user_input,
                history_context=history_context,
                render_mode="html",
            )
            code = await pipeline.run_code_generation(
                user_input=user_input,
                history_context=history_context,
                analysis=analysis,
            )
        except Exception as exc:
            logger.warning(f"InteractiveGenerator failed: {exc}", exc_info=True)
            raise GenerationFailure(f"interactive generation failed: {exc}") from exc

        ok, validation_error = validate_visualization(code, "html")
        if not ok:
            raise GenerationFailure(f"interactive html failed validation: {validation_error}")

        return (
            {
                "render_type": "html",
                "code": {"language": "html", "content": code},
                "description": analysis.description,
                "chart_type": analysis.chart_type,
                "learning_objectives": [ref.model_dump(mode="json") for ref in objective_refs],
                "activity_schema_version": 1,
            },
            [],
            {
                "review_changed": False,
                "review_notes": "Passed local validation.",
            },
        )


__all__ = ["InteractiveGenerator"]
