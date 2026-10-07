"""Contract tests for the ``learning.assessment`` entry point and envelopes.

Complements ``test_assessment.py``: this module pins the pure result-mapping
helpers, the ``AssessmentRecord`` normalization table, the derived audit and
attempt identities, the notebook item envelope, and the coordination branches
of ``record_assessment`` / ``reconcile_linked_assessments`` against a mocked
session store — no database, LLM, or server is required.
"""

from __future__ import annotations

import asyncio
from hashlib import sha1
from typing import Any

import pytest

import deeptutor.learning.assessment as assessment_module
from deeptutor.learning.assessment import (
    AssessmentOutcome,
    AssessmentRecord,
    RecordAssessmentError,
    build_grade_result,
    is_correct_to_result,
    reconcile_linked_assessments,
    record_assessment,
    result_to_is_correct,
    to_notebook_item,
)


def _record(**overrides: Any) -> AssessmentRecord:
    values: dict[str, Any] = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "question_id": "q-1",
        "question": "What is 2+2?",
        "user_answer": "4",
        "source": "book",
        "assessment_type": "focus_check",
    }
    values.update(overrides)
    return AssessmentRecord(**values)


class FakeSessionStore:
    """Async double for the session-store surface the adapter depends on."""

    def __init__(
        self,
        *,
        entry_id: int = 7,
        upserted: bool = True,
        attempt_recorded: bool = True,
        persist: bool = True,
        fail_record: bool = False,
        pending: list[dict[str, Any]] | None = None,
    ) -> None:
        self.attempts: dict[str, dict[str, Any]] = {}
        self.record_calls: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
        self.marked: list[str] = []
        self.entry_id = entry_id
        self.upserted = upserted
        self.attempt_recorded = attempt_recorded
        self.persist = persist
        self.fail_record = fail_record
        self.pending = list(pending or [])

    async def get_assessment_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        return self.attempts.get(attempt_id)

    async def record_assessment(
        self, session_id: str | None, item: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[int, bool, bool]:
        if self.fail_record:
            raise RuntimeError("session store unavailable")
        self.record_calls.append((session_id, item, payload))
        if self.persist:
            self.attempts[payload["attempt_id"]] = dict(payload)
        return self.entry_id, self.upserted, self.attempt_recorded

    async def mark_assessment_link_applied(self, attempt_id: str) -> None:
        self.marked.append(attempt_id)

    async def pending_linked_assessments(self) -> list[dict[str, Any]]:
        return self.pending


@pytest.fixture
def install_store(monkeypatch: pytest.MonkeyPatch):
    def _install(store: FakeSessionStore) -> FakeSessionStore:
        monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", lambda: store)
        return store

    return _install


def _forbid_store() -> Any:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("this path must not open the learning store")

    return forbidden


class TestResultHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("correct", True),
            ("  correct  ", True),
            ("Correct", False),
            ("incorrect", False),
            ("partial", False),
            ("ungraded", False),
            ("voided", False),
            ("", False),
            (None, False),
        ],
    )
    def test_result_to_is_correct_table(self, raw, expected):
        assert result_to_is_correct(raw) is expected

    @pytest.mark.parametrize(
        ("flag", "expected"),
        [(True, "correct"), (False, "incorrect"), (None, "ungraded")],
    )
    def test_is_correct_to_result_table(self, flag, expected):
        assert is_correct_to_result(flag) == expected

    @pytest.mark.parametrize(
        ("result", "flag", "expected"),
        [
            ("correct", False, "correct"),
            ("incorrect", True, "incorrect"),
            ("  partial  ", None, "partial"),
            ("bogus", True, "correct"),
            ("bogus", False, "incorrect"),
            ("", None, "ungraded"),
            ("", False, "incorrect"),
        ],
    )
    def test_build_grade_result_table(self, result, flag, expected):
        assert build_grade_result(result=result, is_correct=flag) == expected


class TestRecordNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected", "origin_ref"),
        [
            ("external_import", "external_import", "ref-1"),
            ("nonsense", "conversation", ""),
            (" document_analysis ", "document_analysis", "ref-2"),
        ],
    )
    def test_origin_type_fallbacks(self, raw, expected, origin_ref):
        assert _record(origin_type=raw, origin_ref=origin_ref).origin_type == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("partner_chat", "partner_chat"),
            ("nope", "deep_question"),
            (None, "deep_question"),
            ("", "deep_question"),
        ],
    )
    def test_source_fallbacks(self, raw, expected):
        assert _record(source=raw).source == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("review", "review"), ("exam", "quiz"), (None, "quiz")],
    )
    def test_assessment_type_fallbacks(self, raw, expected):
        assert _record(assessment_type=raw).assessment_type == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("voided", "voided"), ("unknown", ""), (None, "")],
    )
    def test_result_field_fallbacks(self, raw, expected):
        assert _record(result=raw).result == expected

    def test_text_fields_are_stripped(self):
        record = _record(
            question_id="  q-9  ",
            turn_id=" turn-x ",
            user_answer="  42 ",
            material_title=" Calculus\t",
        )
        assert record.question_id == "q-9"
        assert record.turn_id == "turn-x"
        assert record.user_answer == "42"
        assert record.material_title == "Calculus"

    @pytest.mark.parametrize("raw", [None, "list", 12])
    def test_non_dict_options_become_empty(self, raw):
        assert _record(options=raw).options == {}

    def test_option_values_are_stringified(self):
        record = _record(options={"A": 1, "B": None})
        assert record.options == {"A": "1", "B": "None"}

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("4", 4), (0, 1), (-2, 1), ("abc", 1), (None, 1)],
    )
    def test_attempt_count_floors_at_one(self, raw, expected):
        assert _record(attempt_count=raw).attempt_count == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("5", 5), (-1, 0), ("junk", 0), (None, 0)],
    )
    def test_hints_used_floors_at_zero(self, raw, expected):
        assert _record(hints_used=raw).hints_used == expected

    def test_unknown_fields_are_ignored(self):
        record = _record(unexpected_column="x")
        assert not hasattr(record, "unexpected_column")


class TestIdentityValidation:
    def test_conversation_origin_ref_backfilled_from_session(self):
        record = _record()
        assert record.origin_type == "conversation"
        assert record.origin_ref == "session-1"

    def test_conversation_origin_ref_must_match_session(self):
        with pytest.raises(ValueError, match="origin_ref"):
            _record(origin_ref="other-session")

    def test_non_conversation_requires_origin_ref(self):
        with pytest.raises(ValueError, match="external_import"):
            _record(origin_type="external_import", origin_ref="  ")


class TestDerivedIdentities:
    def test_conversation_owner_is_session_only(self):
        record = _record(turn_id="t-1", question_id="q-1")
        expected = sha1(b"session-1|t-1|q-1", usedforsecurity=False).hexdigest()
        assert record.assessment_id == expected

    def test_scoped_owner_includes_origin_prefix(self):
        record = _record(
            origin_type="external_import",
            origin_ref="ref-1",
            turn_id="t-9",
            question_id="q-9",
        )
        expected = sha1(b"external_import:ref-1|t-9|q-9", usedforsecurity=False).hexdigest()
        assert record.assessment_id == expected

    def test_explicit_attempt_id_wins(self):
        assert _record(attempt_id="attempt-77").attempt_identity == "attempt-77"

    def test_fallback_attempt_identity_is_stable_and_input_sensitive(self):
        first = _record(user_answer="4", result="correct", is_correct=True)
        second = _record(user_answer="4", result="correct", is_correct=True)
        assert first.attempt_identity == second.attempt_identity
        changed = _record(user_answer="5", result="correct", is_correct=True)
        assert changed.attempt_identity != first.attempt_identity

    def test_fallback_attempt_identity_matches_reference_digest(self):
        record = _record(
            user_answer="4",
            result="correct",
            is_correct=True,
            attempt_count=2,
            source="book",
            assessment_type="focus_check",
        )
        raw = "|".join(
            (
                "session-1",
                "turn-1",
                "q-1",
                "book",
                "focus_check",
                "2",
                "4",
                "correct",
                "True",
            )
        )
        expected = sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
        assert record.attempt_identity == expected


class TestResultConflictDiagnostics:
    @pytest.mark.parametrize(
        ("result", "flag", "conflict"),
        [
            ("correct", False, True),
            ("incorrect", True, True),
            ("ungraded", True, True),
            ("voided", True, True),
            ("correct", True, False),
            ("correct", None, False),
            ("partial", False, False),
            ("partial", None, False),
        ],
    )
    def test_conflict_table(self, result, flag, conflict):
        record = _record(result=result, is_correct=flag)
        diagnostics: list[str] = []
        item = to_notebook_item(record, diagnostics)
        assert ("is_correct_result_conflict" in diagnostics) is conflict
        assert item["result"] == result


class TestNotebookItemEnvelope:
    EXPECTED_KEYS = {
        "origin_type",
        "origin_ref",
        "turn_id",
        "question_id",
        "question",
        "question_type",
        "options",
        "correct_answer",
        "explanation",
        "difficulty",
        "user_answer",
        "is_correct",
        "source",
        "material_id",
        "material_title",
        "section_id",
        "section_title",
        "assessment_type",
        "result",
        "mastery_path_id",
        "knowledge_point_id",
        "attempt_count",
        "hints_used",
        "confidence",
        "response_time",
        "quality",
    }

    def test_envelope_key_set_is_pinned(self):
        item = to_notebook_item(_record(), [])
        assert set(item) == self.EXPECTED_KEYS

    def test_bool_only_record_resolves_to_graded_result(self):
        item = to_notebook_item(_record(is_correct=True), [])
        assert item["result"] == "correct"
        assert item["is_correct"] is True


class TestRecordAssessmentEntry:
    def test_outcome_envelope_without_linkage(self, install_store):
        store = install_store(FakeSessionStore(entry_id=11, upserted=False, attempt_recorded=False))
        record = _record(result="correct", is_correct=True)
        outcome = asyncio.run(record_assessment(record))
        assert isinstance(outcome, AssessmentOutcome)
        assert outcome.entry_id == 11
        assert outcome.upserted is False
        assert outcome.attempt_recorded is False
        assert outcome.attempt_id == record.attempt_identity
        assert outcome.diagnostics == []
        assert store.marked == []
        session_id, _item, payload = store.record_calls[0]
        assert session_id == "session-1"
        assert payload["attempt_id"] == record.attempt_identity
        assert payload["occurred_at"] == record.created_at
        assert payload["result"] == "correct"
        assert payload["is_correct"] is True

    def test_missing_session_is_passed_as_none(self, install_store):
        store = install_store(FakeSessionStore())
        record = _record(session_id="", origin_type="external_import", origin_ref="ref-1")
        asyncio.run(record_assessment(record))
        assert store.record_calls[0][0] is None

    def test_retry_inherits_linkage_from_durable_attempt(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore())
        record = _record(attempt_id="attempt-1")
        store.attempts["attempt-1"] = {
            **record.model_dump(mode="json"),
            "attempt_id": "attempt-1",
            "mastery_path_id": "path-9",
            "knowledge_point_id": "kp-9",
        }
        applied: list[tuple[str, str]] = []

        def fake_apply(_record, *, result, attempt_id):
            applied.append((attempt_id, result))
            return True

        monkeypatch.setattr(assessment_module, "_apply_linked_retention", fake_apply)
        outcome = asyncio.run(record_assessment(record))
        assert store.record_calls[0][2]["mastery_path_id"] == "path-9"
        assert store.record_calls[0][2]["knowledge_point_id"] == "kp-9"
        assert outcome.diagnostics == ["linked_retention_updated"]
        assert store.marked == ["attempt-1"]
        assert applied == [("attempt-1", "ungraded")]

    def test_untrusted_linkage_is_dropped_before_persist(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore())
        checked: list[tuple[str, str]] = []

        def fake_trust(path_id, knowledge_point_id):
            checked.append((path_id, knowledge_point_id))
            return False

        monkeypatch.setattr(assessment_module, "_is_trusted_linkage", fake_trust)
        record = _record(mastery_path_id="path-2", knowledge_point_id="kp-2")
        outcome = asyncio.run(record_assessment(record))
        assert checked == [("path-2", "kp-2")]
        assert "dropped_invalid_mastery_linkage" in outcome.diagnostics
        payload = store.record_calls[0][2]
        assert payload["mastery_path_id"] == ""
        assert payload["knowledge_point_id"] == ""
        assert store.marked == []

    def test_trusted_linkage_is_kept_and_marked_once(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore())
        monkeypatch.setattr(assessment_module, "_is_trusted_linkage", lambda p, k: True)
        monkeypatch.setattr(assessment_module, "_apply_linked_retention", lambda *a, **k: False)
        record = _record(
            mastery_path_id="path-3",
            knowledge_point_id="kp-3",
            result="correct",
            is_correct=True,
        )
        outcome = asyncio.run(record_assessment(record))
        assert outcome.diagnostics == []
        assert store.record_calls[0][2]["mastery_path_id"] == "path-3"
        assert store.marked == [record.attempt_identity]

    def test_mastery_source_skips_trust_check(self, install_store, monkeypatch: pytest.MonkeyPatch):
        store = install_store(FakeSessionStore())
        monkeypatch.setattr(assessment_module, "_is_trusted_linkage", _forbid_store())
        monkeypatch.setattr(assessment_module, "_apply_linked_retention", lambda *a, **k: True)
        record = _record(source="mastery_path", mastery_path_id="path-4", knowledge_point_id="kp-4")
        outcome = asyncio.run(record_assessment(record))
        assert "dropped_invalid_mastery_linkage" not in outcome.diagnostics
        assert store.marked == [record.attempt_identity]

    def test_store_failure_raises_record_error(self, install_store):
        install_store(FakeSessionStore(fail_record=True))
        with pytest.raises(RecordAssessmentError):
            asyncio.run(record_assessment(_record()))

    def test_missing_durable_attempt_after_record_raises(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore(persist=False))
        monkeypatch.setattr(assessment_module, "_is_trusted_linkage", lambda p, k: True)
        monkeypatch.setattr(assessment_module, "_apply_linked_retention", lambda *a, **k: True)
        record = _record(mastery_path_id="path-5", knowledge_point_id="kp-5")
        with pytest.raises(RecordAssessmentError):
            asyncio.run(record_assessment(record))
        assert store.marked == []

    def test_retention_failure_raises_after_persist(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore())

        def explode(*_args, **_kwargs):
            raise RuntimeError("retention unavailable")

        monkeypatch.setattr(assessment_module, "_is_trusted_linkage", lambda p, k: True)
        monkeypatch.setattr(assessment_module, "_apply_linked_retention", explode)
        record = _record(mastery_path_id="path-6", knowledge_point_id="kp-6")
        with pytest.raises(RecordAssessmentError):
            asyncio.run(record_assessment(record))
        assert store.marked == []


class TestLinkedRetentionGuards:
    @pytest.mark.parametrize(
        ("source", "result"),
        [
            ("mastery_path", "correct"),
            ("book", "ungraded"),
            ("book", "voided"),
        ],
    )
    def test_guarded_submissions_never_touch_the_store(
        self, source, result, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(assessment_module, "_get_learning_store", _forbid_store())
        record = _record(
            source=source,
            result=result,
            mastery_path_id="path-1",
            knowledge_point_id="kp-1",
        )
        applied = assessment_module._apply_linked_retention(record, result=result, attempt_id="a-1")
        assert applied is False

    def test_missing_linkage_is_skipped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(assessment_module, "_get_learning_store", _forbid_store())
        record = _record(result="correct")
        applied = assessment_module._apply_linked_retention(
            record, result="correct", attempt_id="a-2"
        )
        assert applied is False


class TestReconcileLinkedAssessments:
    def test_replays_pending_and_counts_failures(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        good = _record(
            result="correct",
            is_correct=True,
            mastery_path_id="path-1",
            knowledge_point_id="kp-1",
            attempt_id="a-good",
        )
        pending = [
            {**good.model_dump(mode="json"), "attempt_id": "a-good"},
            {"attempt_id": "a-bad"},
        ]
        store = install_store(FakeSessionStore(pending=pending))
        replayed: list[str] = []

        def fake_apply(_record, *, result, attempt_id):
            replayed.append(attempt_id)
            return True

        monkeypatch.setattr(assessment_module, "_apply_linked_retention", fake_apply)
        recovered, failed = asyncio.run(reconcile_linked_assessments())
        assert (recovered, failed) == (1, 1)
        assert replayed == ["a-good"]
        assert store.marked == ["a-good"]

    def test_all_invalid_pending_reports_failures(
        self, install_store, monkeypatch: pytest.MonkeyPatch
    ):
        store = install_store(FakeSessionStore(pending=[{"attempt_id": "x"}, {}]))
        monkeypatch.setattr(assessment_module, "_apply_linked_retention", lambda *a, **k: True)
        recovered, failed = asyncio.run(reconcile_linked_assessments())
        assert (recovered, failed) == (0, 2)
        assert store.marked == []
