"""Authenticated transport for schema-driven Immersive Reading extensions."""

from __future__ import annotations

import asyncio
from contextvars import copy_context
import inspect
import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    assert_learning_material,
)
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingContext,
    ReadingExtensionResult,
    get_reading_extension_registry,
)
from deeptutor.services.llm.exceptions import LLMError

logger = logging.getLogger(__name__)

router = APIRouter()
# Quiz / translation / vocabulary all call an LLM. Thirty seconds is enough to
# trip a hanging *sync* plugin, but too short for a grounded three-question
# quiz on a reasoning model — and a timeout used to circuit-break the extension
# for the rest of the process.
ACTION_TIMEOUT_S = 120


class ReadingModelSelection(BaseModel):
    profile_id: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    reasoning_effort: str | None = Field(default=None, max_length=32)


def _unavailable_detail(
    *,
    reason: str = "",
    message: str = "This reading action is temporarily unavailable.",
    code: str = "unavailable",
    recoverable: bool = True,
    request_id: str = "",
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "message": message,
        "recoverable": recoverable,
        "code": code,
    }
    if reason:
        detail["reason"] = reason[:500]
    if request_id:
        detail["request_id"] = request_id
    return detail


class ActionPayload(BaseModel):
    llm_selection: ReadingModelSelection | None = None
    locator: int = Field(ge=1)
    selection: str = Field(default="", max_length=10_000)
    locale: str = Field(default="en", max_length=32)


class QuizAnswerItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str = Field(min_length=1)
    selected_index: int = Field(ge=0)


class QuizAnswersPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    locator: int = Field(ge=1)
    source_anchor: str = Field(default="", max_length=2_000)
    section_title: str = Field(default="", max_length=500)
    session_id: str = ""
    turn_id: str = ""
    submission_id: str = Field(default="", max_length=200)
    answers: list[QuizAnswerItem] = Field(min_length=1)


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _verified_selection(candidate: str, unit_text: str) -> str:
    value = _normal(candidate)
    if not value:
        return ""
    unit = _normal(unit_text)
    if value in unit:
        return value
    # A PDF's text layer and its extracted text disagree about where the
    # breaks go: margin line numbers the extractor put on their own lines
    # ("Language\n1\nModels") reach the browser glued to the word before them
    # ("Language1 Models"). Whitespace carries no content, so match without
    # it, and hand the extension the material's own spelling of the span.
    compact: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(unit):
        if not character.isspace():
            compact.append(character)
            positions.append(index)
    needle = re.sub(r"\s+", "", value)
    found = "".join(compact).find(needle)
    if found < 0:
        return ""
    return unit[positions[found] : positions[found + len(needle) - 1] + 1]


def _discard_late_worker_result(worker: asyncio.Future) -> None:
    """Retrieve abandoned worker failures and close unconsumed coroutines."""
    if worker.cancelled():
        return
    try:
        value = worker.result()
        if inspect.iscoroutine(value):
            value.close()
    except Exception:
        logger.exception("Reading extension worker failed after its request ended")


def _record_reading_activity(
    material_id: str,
    *,
    extension_id: str,
    action: str,
    locator: int,
    result_type: str,
) -> None:
    LearningStore().record_reading_activity(
        material_id,
        extension_id=extension_id,
        action=action,
        locator=locator,
        result_type=result_type,
    )


@router.get("/extensions")
async def list_extensions() -> list[dict[str, Any]]:
    allowed = allowed_reading_extensions()
    return [
        extension.manifest.model_dump()
        for extension in get_reading_extension_registry().all()
        if allowed is None or extension.manifest.id in allowed
    ]


@router.post("/materials/{material_id}/extensions/{extension_id}/actions/{action}")
async def run_extension_action(
    material_id: str,
    extension_id: str,
    action: str,
    payload: ActionPayload,
) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    allowed = allowed_reading_extensions()
    if allowed is not None and extension_id not in allowed:
        raise HTTPException(status_code=403, detail="This reading extension is not allowed.")

    registry = get_reading_extension_registry()
    extension = registry.get(extension_id)
    if extension is None:
        raise HTTPException(status_code=404, detail="Reading extension not found.")
    declared_action = next((row for row in extension.manifest.actions if row.id == action), None)
    if declared_action is None:
        raise HTTPException(status_code=404, detail="Reading extension action not found.")
    store = ReadingStore()
    try:
        unit_text = store.unit_text(material_id, payload.locator)
        position = store.position(material_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    selection = _verified_selection(payload.selection, unit_text)
    if "selection" in declared_action.requires and not selection:
        raise HTTPException(status_code=400, detail="Select text from the visible unit first.")
    try:
        context = ReadingContext(
            material_id=material_id,
            locator=payload.locator,
            source_anchor=(position.source_anchor if position.locator == payload.locator else ""),
            locale=payload.locale,
            selection=selection,
            visible_text=unit_text,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="This reading unit is too large for the extension protocol.",
        ) from exc
    request_id = uuid4().hex

    def failure(
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        status: int = 503,
        reason: str = "",
    ) -> HTTPException:
        logger.warning("Reading action %s request=%s code=%s", extension_id, request_id, code)
        return HTTPException(
            status_code=status,
            detail=_unavailable_detail(
                reason=reason,
                message=message,
                code=code,
                recoverable=recoverable,
                request_id=request_id,
            ),
        )

    token = None
    if extension.manifest.requires_llm:
        from deeptutor.multi_user.model_access import apply_allowed_llm_selection
        from deeptutor.services.model_selection.runtime import (
            activate_llm_selection,
            reset_llm_selection,
        )

        try:
            selection_config = (
                payload.llm_selection.model_dump(exclude_none=True)
                if payload.llm_selection
                else None
            )
            selection_config = apply_allowed_llm_selection(selection_config)
            # A shared default is still subject to the caller's model grants.
            if selection_config is None:
                from deeptutor.multi_user.context import get_current_user
                from deeptutor.multi_user.model_access import redacted_model_access
                from deeptutor.services.config.model_catalog import get_model_catalog_service

                user = get_current_user()
                if not user.is_admin:
                    service = get_model_catalog_service().load().get("services", {}).get("llm", {})
                    default = {
                        "profile_id": service.get("active_profile_id"),
                        "model_id": service.get("active_model_id"),
                    }
                    try:
                        apply_allowed_llm_selection(default)
                    except PermissionError:
                        default = None
                    if default is None:
                        default = next(
                            (
                                {
                                    "profile_id": item.get("profile_id"),
                                    "model_id": item.get("model_id"),
                                }
                                for item in redacted_model_access(user.id).get("llm", [])
                                if item.get("available")
                            ),
                            None,
                        )
                    if default is None or not all(default.values()):
                        raise ValueError("No selected model")
                    selection_config = default
            config, token = activate_llm_selection(selection_config)
            if not config.model:
                raise ValueError("No selected model")
        except PermissionError:
            reset_llm_selection(token)
            raise failure(
                "model_forbidden",
                "This model is not assigned to your account. Choose an authorized model or contact your administrator.",
                recoverable=False,
                status=403,
            ) from None
        except Exception as exc:
            reset_llm_selection(token)
            logger.warning(
                "Reading action %s request=%s model configuration failed (%s)",
                extension_id,
                request_id,
                type(exc).__name__,
            )
            raise failure(
                "model_not_configured",
                "Choose a model in the reading conversation before using this action. Contact your administrator if no model is available.",
                recoverable=False,
            ) from None

    # Sync plugins run on a private worker we cannot kill; a timeout must
    # open the circuit so later clicks do not queue behind the stuck call.
    # Async plugins (quiz, translation, …) are cancelled with the request,
    # so a slow LLM must not disable the button for the rest of the process.
    run = extension.run_action
    sync_plugin = not inspect.iscoroutinefunction(run)
    if not registry.begin_action(extension_id, circuit_break=sync_plugin):
        if registry.is_timed_out(extension_id):
            raise failure(
                "worker_running",
                "The previous reading action is still running. Wait for it to finish, or ask an administrator to restart the backend.",
                recoverable=False,
                reason="busy_or_circuit_open",
            ) from None
        raise failure(
            "busy",
            "This reading action is busy. Try again after it finishes.",
            reason="busy_or_circuit_open",
        ) from None
    # Only a still-running worker needs the circuit kept open (#1448).
    # Async cancellation finishes before the reservation is released, including
    # sync handlers that return an awaitable after their worker has finished.
    worker: asyncio.Future | None = None
    try:
        async with asyncio.timeout(ACTION_TIMEOUT_S):
            handler = extension.run_action
            if inspect.iscoroutinefunction(handler):
                value = await handler(action, context)
            else:
                worker = asyncio.get_running_loop().run_in_executor(
                    registry.executor_for(extension_id),
                    copy_context().run,
                    handler,
                    action,
                    context,
                )
                value = await asyncio.shield(worker)
            if inspect.isawaitable(value):
                value = await value
        try:
            result = (
                value
                if isinstance(value, ReadingExtensionResult)
                else ReadingExtensionResult.model_validate(value)
            )
            if result.type not in extension.manifest.result_types:
                raise ValueError("Undeclared result type")
        except (ValueError, TypeError) as exc:
            raise failure(
                "invalid_output",
                "The reading provider returned an invalid result. Please retry.",
                reason=str(exc),
            ) from None
        dumped = result.model_dump()
        quiz_payload = dumped.get("payload")
        if dumped.get("type") == "quiz" and isinstance(quiz_payload, dict):
            await _persist_reading_quiz_pending(material_id, payload.locator, quiz_payload)
    except TimeoutError as exc:
        logger.warning("Reading extension %s action %s timed out", extension_id, action)
        if worker is not None and not worker.done():
            # finally() keeps the circuit open and discards the late result.
            raise failure(
                "worker_running",
                "The reading action timed out but is still running. Wait, or ask an administrator to restart the backend.",
                recoverable=False,
                reason="timed_out",
            ) from exc
        raise failure(
            "timeout",
            "The reading action timed out. You can try again.",
            reason="timed_out",
        ) from exc
    except LLMError as exc:
        logger.warning(
            "Reading extension %s action %s failed via language model: %s",
            extension_id,
            action,
            exc,
        )
        raise failure(
            "provider_error",
            "This reading action needs a working language model. Check the selected model or contact your administrator.",
            reason=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Reading extension %s action %s failed", extension_id, action)
        code = (
            "invalid_output" if isinstance(exc, (ValueError, ValidationError)) else "provider_error"
        )
        message = (
            "The reading provider returned an invalid result. Please retry."
            if code == "invalid_output"
            else "The reading provider failed. Check the selected model or contact your administrator."
        )
        raise failure(code, message, reason=str(exc)) from None
    finally:
        if worker is not None and not worker.done():
            registry.mark_timed_out(extension_id)
            worker.add_done_callback(_discard_late_worker_result)
        registry.finish_action(extension_id)
        if token is not None:
            from deeptutor.services.model_selection.runtime import reset_llm_selection

            reset_llm_selection(token)

    try:
        await asyncio.to_thread(
            _record_reading_activity,
            material_id,
            extension_id=extension_id,
            action=action,
            locator=payload.locator,
            result_type=result.type,
        )
    except Exception:
        logger.exception("Reading action succeeded, but learning activity recording failed")
    return dumped


def _choice_map(choices: list[Any]) -> dict[str, str]:
    return {
        chr(65 + index): str(choice)
        for index, choice in enumerate(choices)
        if isinstance(choice, str) or choice is not None
    }


def _material_title(material_id: str) -> str:
    try:
        manifest = ReadingStore().manifest(material_id)
    except Exception:
        return ""
    return str(getattr(manifest, "title", "") or getattr(manifest, "filename", "") or "")


async def _persist_reading_quiz_pending(
    material_id: str, locator: int, payload: dict[str, Any]
) -> None:
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return
    from deeptutor.services.session import get_sqlite_session_store

    # A regenerated quiz must not reuse q_1 and grade an old card against a new key.
    quiz_id = uuid4().hex
    for index, question in enumerate(questions):
        if isinstance(question, dict):
            question["id"] = f"{quiz_id}:{index}"
    await get_sqlite_session_store().put_reading_quiz_pending(material_id, locator, questions)


@router.post("/materials/{material_id}/extensions/quiz/answers")
async def submit_quiz_answers(material_id: str, payload: QuizAnswersPayload) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    from deeptutor.learning.assessment import (
        AssessmentRecord,
        RecordAssessmentError,
        is_correct_to_result,
        record_assessment,
    )
    from deeptutor.services.session import get_sqlite_session_store

    store = get_sqlite_session_store()
    question_ids = [item.question_id.strip() for item in payload.answers]
    pending = await store.get_reading_quiz_pending(material_id, payload.locator, question_ids)
    missing = [qid for qid in question_ids if qid not in pending]
    if missing:
        raise HTTPException(status_code=409, detail="This reading quiz has expired.")

    # Validate the entire batch before saving any answers.
    for item in payload.answers:
        question = pending[item.question_id.strip()]
        choices = question.get("choices")
        correct_index = question.get("correct_choice_index")
        if (
            not isinstance(choices, list)
            or type(correct_index) is not int
            or not 0 <= correct_index < len(choices)
        ):
            raise HTTPException(
                status_code=409, detail="This reading quiz has an invalid answer key."
            )
        if item.selected_index >= len(choices):
            raise HTTPException(status_code=422, detail="Selected answer is outside the choices.")

    session_id = payload.session_id.strip()
    section_title = payload.section_title.strip() or payload.source_anchor.strip()
    material_title = _material_title(material_id)
    if session_id:
        if await store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Reading session not found.")
    origin_type = "conversation" if session_id else "document_analysis"
    origin_ref = session_id or f"reading:{material_id}"
    turn_id = payload.turn_id.strip() or f"reading:{material_id}:loc:{payload.locator}"
    graded: list[dict[str, Any]] = []
    for item in payload.answers:
        question = pending[item.question_id.strip()]
        choices = question.get("choices") if isinstance(question.get("choices"), list) else []
        try:
            correct_index = int(question.get("correct_choice_index"))
        except (TypeError, ValueError):
            correct_index = -1
        is_correct = item.selected_index == correct_index
        result = is_correct_to_result(is_correct)
        options = _choice_map(choices)
        selected_text = (
            str(choices[item.selected_index]) if 0 <= item.selected_index < len(choices) else ""
        )
        correct_text = str(choices[correct_index]) if 0 <= correct_index < len(choices) else ""
        submission_id = payload.submission_id.strip()
        attempt_id = (
            f"reading:{origin_type}:{origin_ref}:{turn_id}:"
            f"{item.question_id.strip()}:{submission_id}"
            if submission_id
            else ""
        )
        try:
            await record_assessment(
                AssessmentRecord(
                    session_id=session_id,
                    origin_type=origin_type,
                    origin_ref=origin_ref,
                    turn_id=turn_id,
                    question_id=item.question_id.strip(),
                    question=str(question.get("prompt") or "Reading quiz"),
                    question_type="choice",
                    options=options,
                    user_answer=selected_text,
                    correct_answer=correct_text,
                    is_correct=is_correct,
                    result=result,
                    source="immersive_reading",
                    assessment_type="focus_check",
                    material_id=material_id,
                    material_title=material_title,
                    section_id=str(payload.locator),
                    section_title=section_title,
                    mastery_path_id=str(question.get("mastery_path_id") or ""),
                    knowledge_point_id=str(question.get("knowledge_point_id") or ""),
                    attempt_id=attempt_id,
                )
            )
        except RecordAssessmentError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        graded.append(
            {
                "question_id": item.question_id.strip(),
                "is_correct": is_correct,
                "result": result,
            }
        )
    return {"answers": graded}


__all__ = ["router"]
