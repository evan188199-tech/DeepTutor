"""Tests for the soft learning journal store (#740)."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from deeptutor.services.learning_journal.store import (
    JOURNAL_VERSION,
    MAX_INSIGHT_CHARS,
    MAX_LEVEL_CHARS,
    MAX_NEXT_FOCUS_CHARS,
    MAX_RECORDS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    MAX_TOPIC_CHARS,
    MAX_WHY_CHARS,
    LearningJournalStore,
)
from deeptutor.services.path_service import PathService


@pytest.fixture()
def journal_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LearningJournalStore:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service",
        lambda: service,
    )
    return LearningJournalStore()


def test_empty_status_explains_how_to_start(journal_store: LearningJournalStore) -> None:
    text = journal_store.status_markdown()
    assert "No learning journal yet" in text
    assert "learning_update" in text


def test_mission_session_and_records_round_trip(journal_store: LearningJournalStore) -> None:
    mission = journal_store.set_mission(
        topic="Fourier transform",
        why="Need it for signals coursework",
        level="intermediate",
    )
    assert mission.accepted
    session = journal_store.note_session(
        summary="Covered continuous FT definition and duality.",
        next_focus="Discrete FT and sampling intuition",
    )
    assert session.accepted
    record = journal_store.add_record(
        title="Duality",
        insight="Time stretch ↔ frequency squeeze is the first intuition to keep.",
    )
    assert record.accepted
    assert record.record_id == "lr_0001"

    text = journal_store.status_markdown()
    assert "Fourier transform" in text
    assert "Discrete FT" in text
    assert "lr_0001" in text
    assert "Duality" in text

    path = journal_store.journal_path()
    assert path.exists()
    again = journal_store.load()
    assert again.mission.topic == "Fourier transform"
    assert len(again.records) == 1
    assert path.read_text(encoding="utf-8").count("Fourier") >= 1


def test_add_record_dedupes(journal_store: LearningJournalStore) -> None:
    first = journal_store.add_record(title="Nyquist", insight="Sample at >2B.")
    second = journal_store.add_record(title="Nyquist", insight="Sample at >2B.")
    assert first.accepted and second.accepted
    assert second.deduplicated
    assert second.record_id == first.record_id
    assert len(journal_store.load().records) == 1


def test_set_mission_requires_topic(journal_store: LearningJournalStore) -> None:
    result = journal_store.set_mission(topic="  ")
    assert not result.accepted


def test_injection_snapshot_carries_mission_and_handoff(
    journal_store: LearningJournalStore,
) -> None:
    journal_store.set_mission(
        topic="Fourier transform",
        why="Signals coursework",
        level="intermediate",
    )
    journal_store.note_session(
        summary="Covered continuous FT definition.",
        next_focus="Discrete FT and sampling intuition",
    )
    text = journal_store.injection_markdown()
    assert "Fourier transform" in text
    assert "Discrete FT and sampling intuition" in text


def test_injection_snapshot_leaves_records_out(journal_store: LearningJournalStore) -> None:
    journal_store.set_mission(topic="Fourier transform")
    journal_store.add_record(title="Duality", insight="Time stretch means frequency squeeze.")
    text = journal_store.injection_markdown()
    assert "Duality" not in text
    assert "Time stretch" not in text


def test_injection_snapshot_is_empty_for_a_new_learner(journal_store: LearningJournalStore) -> None:
    assert journal_store.injection_markdown() == ""


def test_injection_snapshot_skips_records_only_journal(
    journal_store: LearningJournalStore,
) -> None:
    journal_store.add_record(title="Nyquist", insight="Sample at more than 2B.")
    assert journal_store.injection_markdown() == ""


@pytest.mark.parametrize(
    "content", ["{broken", "[]", '{"version": 2}', '{"mission": []}', '{"records": [{}]}']
)
def test_corrupt_journal_is_preserved_on_read_and_write(journal_store, content):
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(ValueError):
        journal_store.overview()
    with pytest.raises(ValueError):
        journal_store.set_mission(topic="new")
    assert path.read_text() == content


def test_panel_snapshot_matches_injection_and_reads_create_nothing(journal_store):
    path = journal_store.journal_path()
    assert journal_store.overview()["injected_context"] == ""
    assert not path.parent.exists()
    journal_store.set_mission(topic="Signals", why="Exam", level="beginner")
    journal_store.note_session(summary="Sampling", next_focus="Aliasing")
    journal_store.add_record(title="First", insight="First confirmed takeaway")
    journal_store.add_record(title="Second", insight="Second confirmed takeaway")
    before = path.read_bytes()
    snapshot = journal_store.overview()
    assert snapshot["injected_context"] == journal_store.injection_markdown()
    assert [r["title"] for r in snapshot["records"]] == ["Second", "First"]
    assert path.read_bytes() == before


def _write_records(root, prefix):
    import deeptutor.services.learning_journal.store as module

    module.get_path_service = lambda: PathService(workspace_root=Path(root))
    store = module.LearningJournalStore()
    for n in range(10):
        store.add_record(title=f"{prefix}-{n}", insight=f"confirmed {prefix}-{n}")


def test_two_workers_do_not_drop_confirmed_records(journal_store):
    import multiprocessing

    root = journal_store.journal_path().parent.parent
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_write_records, args=(str(root), p)) for p in ("a", "b")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    records = journal_store.load().records
    assert len(records) == 20
    assert len({record.id for record in records}) == 20


# ---------------------------------------------------------------------------
# Concurrency boundaries (in-process threads)
# ---------------------------------------------------------------------------


def test_threads_sharing_one_store_do_not_lose_records(journal_store: LearningJournalStore) -> None:
    threads_count, per_thread = 8, 5
    barrier = threading.Barrier(threads_count)
    failures: list[BaseException] = []

    def worker(worker_index: int) -> None:
        try:
            barrier.wait(timeout=10)
            for n in range(per_thread):
                result = journal_store.add_record(
                    title=f"t{worker_index}-{n}", insight=f"i{worker_index}-{n}"
                )
                assert result.accepted
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    assert failures == []

    journal = journal_store.load()
    assert len(journal.records) == threads_count * per_thread
    ids = [record.id for record in journal.records]
    assert ids == [f"lr_{n:04d}" for n in range(1, threads_count * per_thread + 1)]
    pairs = {(record.title, record.insight) for record in journal.records}
    assert len(pairs) == threads_count * per_thread


def test_threads_with_separate_stores_share_the_file_lock(
    journal_store: LearningJournalStore,
) -> None:
    threads_count, per_thread = 6, 4
    barrier = threading.Barrier(threads_count)
    failures: list[BaseException] = []

    def worker(worker_index: int) -> None:
        try:
            store = LearningJournalStore()
            barrier.wait(timeout=10)
            for n in range(per_thread):
                result = store.add_record(
                    title=f"w{worker_index}-{n}", insight=f"confirmed w{worker_index}-{n}"
                )
                assert result.accepted
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    assert failures == []

    records = journal_store.load().records
    assert len(records) == threads_count * per_thread
    assert len({record.id for record in records}) == threads_count * per_thread
    assert {record.title for record in records} == {
        f"w{i}-{n}" for i in range(threads_count) for n in range(per_thread)
    }


def test_concurrent_mixed_ops_keep_journal_consistent(journal_store: LearningJournalStore) -> None:
    barrier = threading.Barrier(10)
    failures: list[BaseException] = []

    def mission_worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            assert journal_store.set_mission(topic=f"topic-{index}").accepted
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    def session_worker() -> None:
        try:
            barrier.wait(timeout=10)
            assert journal_store.note_session(summary="summary", next_focus="focus").accepted
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    def record_worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            assert journal_store.add_record(title=f"r{index}", insight=f"insight {index}").accepted
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    threads = [threading.Thread(target=mission_worker, args=(i,)) for i in range(3)]
    threads += [threading.Thread(target=session_worker) for _ in range(2)]
    threads += [threading.Thread(target=record_worker, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    assert failures == []

    journal = journal_store.load()
    assert journal.mission.topic in {f"topic-{i}" for i in range(3)}
    assert journal.last_session.summary == "summary"
    assert len(journal.records) == 5
    assert {record.insight for record in journal.records} == {f"insight {i}" for i in range(5)}


# ---------------------------------------------------------------------------
# Corruption and recovery boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "",
        "\ufeff" + json.dumps({"version": JOURNAL_VERSION}),
        '{"records": [{"id": "lr_',
        json.dumps({"version": JOURNAL_VERSION, "last_session": {"summary": 3}}),
        json.dumps(
            {
                "version": JOURNAL_VERSION,
                "records": [
                    {"id": "lr_0001", "title": "t", "insight": "i"},
                    {"id": "", "title": "broken", "insight": ""},
                ],
            }
        ),
    ],
)
def test_more_corrupt_variants_are_preserved_byte_for_byte(journal_store, content):
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        journal_store.load()
    with pytest.raises(ValueError):
        journal_store.note_session(summary="should not write")
    with pytest.raises(ValueError):
        journal_store.add_record(title="t", insight="i")
    assert path.read_text(encoding="utf-8") == content
    assert sorted(item.name for item in path.parent.iterdir()) == ["journal.json", "journal.lock"]


def test_minimal_and_empty_object_files_load_as_empty_journal(journal_store):
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True)
    for content in ("{}", json.dumps({"version": JOURNAL_VERSION})):
        path.write_text(content, encoding="utf-8")
        journal = journal_store.load()
        assert journal.is_empty()
        assert journal.version == JOURNAL_VERSION
        result = journal_store.add_record(title="t", insight="i")
        assert result.accepted
        assert result.record_id == "lr_0001"


def test_journal_resumes_after_external_repair(journal_store: LearningJournalStore) -> None:
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        journal_store.add_record(title="t", insight="i")

    repaired = {
        "version": JOURNAL_VERSION,
        "updated_at": "2026-01-01T00:00:00Z",
        "mission": {"topic": "Repaired topic"},
        "records": [
            {"id": f"lr_{n:04d}", "title": f"t{n}", "insight": f"i{n}"} for n in range(3, 6)
        ],
    }
    path.write_text(json.dumps(repaired), encoding="utf-8")
    journal = journal_store.load()
    assert journal.mission.topic == "Repaired topic"
    assert [record.id for record in journal.records] == ["lr_0003", "lr_0004", "lr_0005"]

    result = journal_store.add_record(title="new", insight="post-repair insight")
    assert result.accepted
    assert result.record_id == "lr_0006"
    assert len(journal_store.load().records) == 4


def test_stale_lock_file_does_not_block_use(journal_store: LearningJournalStore) -> None:
    lock_path = journal_store.journal_path().with_suffix(".lock")
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"garbage-from-a-crashed-writer")

    assert journal_store.load().is_empty()
    assert journal_store.set_mission(topic="After stale lock").accepted
    assert journal_store.add_record(title="t", insight="i").record_id == "lr_0001"
    assert lock_path.exists()


# ---------------------------------------------------------------------------
# Empty / overlong entry boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", " ", "\t\n  "])
def test_add_record_rejects_blank_insight_and_writes_nothing(journal_store, blank):
    result = journal_store.add_record(title="Title", insight=blank)
    assert not result.accepted
    assert "insight" in result.message
    assert not journal_store.journal_path().parent.exists()


def test_add_record_without_title_derives_it_from_insight(
    journal_store: LearningJournalStore,
) -> None:
    long_insight = "abcdefghij" * 10
    result = journal_store.add_record(title="", insight=long_insight)
    assert result.accepted
    record = journal_store.load().records[0]
    assert record.title == "abcdefghij" * 5 + "abcdefghi" + "…"
    assert len(record.title) == 60

    short = journal_store.add_record(title=" ", insight="short insight")
    assert short.accepted
    assert journal_store.load().records[1].title == "short insight"


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("topic", MAX_TOPIC_CHARS),
        ("why", MAX_WHY_CHARS),
        ("level", MAX_LEVEL_CHARS),
        ("summary", MAX_SUMMARY_CHARS),
        ("next_focus", MAX_NEXT_FOCUS_CHARS),
        ("title", MAX_TITLE_CHARS),
        ("insight", MAX_INSIGHT_CHARS),
    ],
)
def test_oversized_values_clip_to_exact_limit(journal_store, field, limit):
    journal_store.set_mission(topic="seed")
    fill = "入" * 900

    if field == "topic":
        journal_store.set_mission(topic=fill)
        stored = journal_store.load().mission
    elif field in ("why", "level"):
        journal_store.set_mission(topic="seed", **{field: fill})
        stored = journal_store.load().mission
    elif field == "summary":
        journal_store.note_session(summary=fill)
        stored = journal_store.load().last_session
    elif field == "next_focus":
        journal_store.note_session(summary="kept", next_focus=fill)
        stored = journal_store.load().last_session
    elif field == "title":
        journal_store.add_record(title=fill, insight="kept")
        stored = journal_store.load().records[0]
    else:
        journal_store.add_record(title="kept", insight=fill)
        stored = journal_store.load().records[0]

    value = getattr(stored, field)
    assert len(value) == limit
    assert value == "入" * (limit - 1) + "…"
    assert "\n" not in value


@pytest.mark.parametrize(
    ("field", "limit", "write"),
    [
        ("topic", MAX_TOPIC_CHARS, lambda s, v: s.set_mission(topic=v)),
        ("insight", MAX_INSIGHT_CHARS, lambda s, v: s.add_record(title="t", insight=v)),
    ],
)
def test_value_exactly_at_limit_is_kept_unchanged(journal_store, field, limit, write):
    exact = "a" * limit
    assert write(journal_store, exact).accepted
    stored = journal_store.load()
    value = getattr(stored.mission if field == "topic" else stored.records[0], field)
    assert value == exact


def test_whitespace_collapses_to_single_spaces(journal_store: LearningJournalStore) -> None:
    messy = "  sparks \n\n sample\t at  2x  "
    journal_store.set_mission(topic=messy)
    journal_store.add_record(title=messy, insight=messy)
    journal = journal_store.load()
    assert journal.mission.topic == "sparks sample at 2x"
    assert journal.records[0].title == "sparks sample at 2x"
    assert journal.records[0].insight == "sparks sample at 2x"


def test_note_session_requires_summary_or_focus(journal_store: LearningJournalStore) -> None:
    rejected = journal_store.note_session(summary="   ", next_focus="\t\n")
    assert not rejected.accepted
    assert not journal_store.journal_path().parent.exists()

    focus_only = journal_store.note_session(summary="", next_focus="Aliasing")
    assert focus_only.accepted
    session = journal_store.load().last_session
    assert session.summary == ""
    assert session.next_focus == "Aliasing"
    assert session.updated_at.endswith("Z")


# ---------------------------------------------------------------------------
# Dedup boundaries
# ---------------------------------------------------------------------------


def test_dedupe_normalizes_case_and_whitespace(journal_store: LearningJournalStore) -> None:
    first = journal_store.add_record(
        title="Fourier Transform", insight="Time stretch squeezes frequency."
    )
    path = journal_store.journal_path()
    before = path.read_bytes()

    second = journal_store.add_record(
        title="  fourier   TRANSFORM ", insight="time\nstretch\tsqueezes frequency."
    )
    assert first.accepted and second.accepted
    assert second.deduplicated
    assert second.record_id == first.record_id
    records = journal_store.load().records
    assert len(records) == 1
    assert path.read_bytes() == before


def test_same_title_with_different_insight_is_not_a_duplicate(
    journal_store: LearningJournalStore,
) -> None:
    first = journal_store.add_record(title="Nyquist", insight="Sample above twice the bandwidth.")
    second = journal_store.add_record(title="Nyquist", insight="Sampling lower aliases signals.")
    assert first.accepted and second.accepted
    assert not second.deduplicated
    assert second.record_id != first.record_id
    assert [record.id for record in journal_store.load().records] == [
        first.record_id,
        second.record_id,
    ]


def test_record_cap_keeps_the_newest_window(journal_store: LearningJournalStore) -> None:
    for n in range(1, MAX_RECORDS + 6):
        result = journal_store.add_record(title=f"t{n}", insight=f"i{n}")
        assert result.accepted

    records = journal_store.load().records
    assert len(records) == MAX_RECORDS
    assert [record.id for record in records] == [f"lr_{n:04d}" for n in range(6, MAX_RECORDS + 6)]
    assert records[-1].title == f"t{MAX_RECORDS + 5}"

    readded = journal_store.add_record(title="t1", insight="i1")
    assert readded.accepted
    assert not readded.deduplicated
    assert readded.record_id == f"lr_{MAX_RECORDS + 6:04d}"
    still = journal_store.load().records
    assert len(still) == MAX_RECORDS
    assert still[0].id == f"lr_{7:04d}"


def test_record_numbering_scans_existing_ids_on_disk(journal_store: LearningJournalStore) -> None:
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": JOURNAL_VERSION,
                "records": [
                    {"id": "lr_0005", "title": "t5", "insight": "i5"},
                    {"id": "legacy-9", "title": "manual", "insight": "imported"},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = journal_store.add_record(title="next", insight="after import")
    assert result.accepted
    assert result.record_id == "lr_0006"
    ids = [record.id for record in journal_store.load().records]
    assert ids == ["lr_0005", "legacy-9", "lr_0006"]
