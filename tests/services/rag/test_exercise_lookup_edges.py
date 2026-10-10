"""Edge-path contracts for the structural exercise lookup.

Complements ``test_exercise_lookup.py`` with the degradation, trimming and
ordering contracts of ``exercise_lookup``: query-assembly boundaries, cache
manifest hygiene (hidden/escaping/malformed), full-vs-partial parse selection,
mtime-keyed cache invalidation, per-question match truncation, content-budget
overflow and stable status/source ordering. Everything is synthetic and
offline; no index, embedding or network is involved.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest

from deeptutor.services.rag.pipelines.llamaindex.exercise_lookup import (
    MAX_QUESTIONS,
    _page,
    _parsed,
    _source_hash,
    _text,
    lookup_exercises,
    requested_exercises,
)

T1 = 1_700_000_000_000_000_000
T2 = 1_700_000_001_000_000_000


def text(s, page=1, **kwargs):
    return {"type": "text", "text": s, "original_page": page, **kwargs}


def simple_blocks(*problems):
    blocks = [text("第二章 磁场"), text("习题")]
    blocks.extend(text(p) for p in problems)
    return blocks


def seed_source(kb, cache, name, blocks, *, content_name="full_content_list.json", manifest=None):
    source = kb / "raw" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"pdf:" + name.encode())
    st = source.stat()
    digest = _source_hash(str(source), st.st_mtime_ns, st.st_size)
    folder = cache / digest[:2] / digest / "sig"
    folder.mkdir(parents=True)
    meta = {"source_hash": digest} if manifest is None else manifest
    (folder / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / content_name).write_text(json.dumps(blocks), encoding="utf-8")
    return folder


def make_source_with_digest(kb, cache, name):
    source = kb / "raw" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"pdf:" + name.encode())
    st = source.stat()
    digest = _source_hash(str(source), st.st_mtime_ns, st.st_size)
    digest_dir = cache / digest[:2] / digest
    digest_dir.mkdir(parents=True)
    return digest_dir, digest


def write_parse(digest_dir, digest, subdir, blocks):
    folder = digest_dir / subdir
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"source_hash": digest}), encoding="utf-8")
    (folder / "full_content_list.json").write_text(json.dumps(blocks), encoding="utf-8")
    return folder


class QueryAssemblyEdgeTests(unittest.TestCase):
    def test_bare_numbers_and_lookup_verb_queries(self):
        self.assertEqual(requested_exercises("2-13、2-14")[0], [(2, 13), (2, 14)])
        self.assertEqual(requested_exercises("find 3-1")[0], [(3, 1)])
        self.assertEqual(requested_exercises("查找 2-13 和 2-15")[0], [(2, 13), (2, 15)])
        self.assertIsNone(requested_exercises("find 3-1")[1])

    def test_chapter_prefix_with_digits_and_multiple_numbers(self):
        self.assertEqual(requested_exercises("第2章 第13题")[0], [(2, 13)])
        self.assertEqual(requested_exercises("第3章第1题和第2题")[0], [(3, 1), (3, 2)])
        self.assertEqual(requested_exercises("第十二章 第5题")[0], [(12, 5)])
        self.assertEqual(requested_exercises("第二十五章第3题")[0], [(25, 3)])

    def test_explicit_intent_overrides_formula_exclusion(self):
        self.assertEqual(requested_exercises("习题2-13的公式推导")[0], [(2, 13)])
        keys, kind = requested_exercises("思考题 2-14 什么意思")
        self.assertEqual(keys, [(2, 14)])
        self.assertEqual(kind, "思考题")
        self.assertEqual(requested_exercises("公式2-13"), ([], None))

    def test_range_cap_and_dash_normalization_dedup(self):
        self.assertEqual(requested_exercises("习题2-1至2-31")[0], [(2, 1), (2, 31)])
        expanded = requested_exercises("习题2-1至2-30")[0]
        self.assertEqual(len(expanded), 30)
        self.assertEqual(expanded[-1], (2, 30))
        self.assertEqual(requested_exercises("2-13 2－13 2—13")[0], [(2, 13)])
        self.assertEqual(requested_exercises("2－13 2—14")[0], [(2, 13), (2, 14)])


class DegradationPathTests(unittest.TestCase):
    def test_batch_limit_over_max_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            (kb / "raw").mkdir(parents=True)
            query = "习题2-1至2-30 3-1 3-2"
            self.assertGreater(len(requested_exercises(query)[0]), MAX_QUESTIONS)
            result = lookup_exercises(query, kb, root / "cache")
            self.assertEqual(result["retrieval_method"], "exercise_exact")
            self.assertEqual(result["sources"], [])
            self.assertEqual(result["exercise_status"], [])
            self.assertIn("32", result["content"])
            self.assertEqual(result["answer"], result["content"])

    def test_malformed_manifests_degrade_to_none(self):
        cases = [
            None,
            {"format": "mineru"},
            {"source_hash": "0" * 16},
        ]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    kb = root / "kb"
                    folder = seed_source(
                        kb,
                        root / "cache",
                        "book.pdf",
                        simple_blocks("2-13 甲"),
                        manifest=manifest,
                    )
                    if manifest is None:
                        (folder / "manifest.json").write_text("{not json", encoding="utf-8")
                    self.assertIsNone(lookup_exercises("习题2-13", kb, root / "cache"))

    def test_hidden_and_escaping_manifests_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            digest_dir, digest = make_source_with_digest(kb, cache, "book.pdf")
            write_parse(digest_dir, digest, ".stale", simple_blocks("2-13 甲"))
            self.assertIsNone(lookup_exercises("习题2-13", kb, cache))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            digest_dir, digest = make_source_with_digest(kb, cache, "book.pdf")
            outside = root / "outside" / "esc"
            outside.mkdir(parents=True)
            (outside / "manifest.json").write_text(
                json.dumps({"source_hash": digest}), encoding="utf-8"
            )
            (outside / "full_content_list.json").write_text(
                json.dumps(simple_blocks("2-13 甲")), encoding="utf-8"
            )
            link = digest_dir / "linked"
            link.symlink_to(outside, target_is_directory=True)
            self.assertIsNone(lookup_exercises("习题2-13", kb, cache))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            digest_dir, digest = make_source_with_digest(kb, cache, "book.pdf")
            folder = write_parse(digest_dir, digest, "real", simple_blocks("2-13 甲"))
            (folder / "manifest.json").unlink()
            (folder / "manifest.json").symlink_to(folder / "manifest.json.bak")
            self.assertIsNone(lookup_exercises("习题2-13", kb, cache))

    def test_full_content_list_preferred_over_partials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            seed_source(
                kb,
                cache,
                "book.pdf",
                simple_blocks("5-1 全文"),
            )
            digest_dir = next((cache / next(cache.iterdir())).iterdir())
            (digest_dir / "sig" / "part_a_content_list.json").write_text(
                json.dumps(simple_blocks("2-13 甲")), encoding="utf-8"
            )
            result = lookup_exercises("习题5-1", kb, cache)
            self.assertEqual(result["exercise_status"][0]["status"], "found")
            result = lookup_exercises("习题2-13", kb, cache)
            self.assertEqual(result["exercise_status"][0]["status"], "not_found")

    def test_sorted_partial_used_when_no_full_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            folder = seed_source(
                kb, cache, "book.pdf", simple_blocks("2-13 甲"), content_name="a_content_list.json"
            )
            (folder / "b_content_list.json").write_text(
                json.dumps(simple_blocks("3-1 乙")), encoding="utf-8"
            )
            self.assertEqual(
                lookup_exercises("习题2-13", kb, cache)["exercise_status"][0]["status"], "found"
            )
            self.assertEqual(
                lookup_exercises("习题3-1", kb, cache)["exercise_status"][0]["status"], "not_found"
            )

    def test_non_list_parse_yields_no_support(self):
        for payload in ({}, []):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    kb = root / "kb"
                    folder = seed_source(kb, root / "cache", "book.pdf", simple_blocks("2-13 甲"))
                    (folder / "full_content_list.json").write_text(
                        json.dumps(payload), encoding="utf-8"
                    )
                    self.assertIsNone(lookup_exercises("习题2-13", kb, root / "cache"))


class CacheInvalidationTests(unittest.TestCase):
    def test_mtime_key_selects_stale_or_fresh_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            folder = seed_source(kb, cache, "book.pdf", simple_blocks("2-13 球面"))
            content = folder / "full_content_list.json"
            os.utime(content, ns=(T1, T1))
            self.assertEqual(
                lookup_exercises("习题2-13", kb, cache)["exercise_status"][0]["status"], "found"
            )
            content.write_text(json.dumps(simple_blocks("2-99 球面")), encoding="utf-8")
            os.utime(content, ns=(T1, T1))
            self.assertEqual(
                lookup_exercises("习题2-13", kb, cache)["exercise_status"][0]["status"], "found"
            )
            self.assertEqual(
                lookup_exercises("习题2-99", kb, cache)["exercise_status"][0]["status"],
                "not_found",
            )
            os.utime(content, ns=(T2, T2))
            self.assertEqual(
                lookup_exercises("习题2-99", kb, cache)["exercise_status"][0]["status"], "found"
            )
            self.assertEqual(
                lookup_exercises("习题2-13", kb, cache)["exercise_status"][0]["status"],
                "not_found",
            )


class TrimmingAndOrderingTests(unittest.TestCase):
    def test_matches_truncated_to_four_per_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            for i in range(5):
                seed_source(kb, cache, f"book{i}.pdf", simple_blocks("2-13 甲"))
            result = lookup_exercises("习题2-13", kb, cache)
            self.assertEqual(result["exercise_status"][0]["status"], "ambiguous")
            self.assertEqual(result["exercise_status"][0]["matches"], 5)
            self.assertEqual(len(result["sources"]), 4)
            self.assertIn("存在 5 个候选", result["content"])

    def test_content_overflow_reports_needs_single_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            seed_source(kb, cache, "book.pdf", simple_blocks("2-13 " + "甲" * 25000))
            result = lookup_exercises("习题2-13", kb, cache)
            self.assertEqual(result["exercise_status"][0]["status"], "needs_single_query")
            self.assertEqual(result["exercise_status"][0]["matches"], 1)
            self.assertEqual(result["sources"], [])
            self.assertIn("超出本次返回长度", result["content"])

    def test_status_and_source_order_follow_query_keys_and_pages_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            seed_source(
                kb,
                cache,
                "book.pdf",
                [
                    text("第二章 磁场"),
                    text("习题"),
                    text("2-13 甲", 3),
                    text("续", 2),
                    text("2-14 乙", 1),
                ],
            )
            result = lookup_exercises("2-14 2-13", kb, cache)
            self.assertEqual([s["question"] for s in result["exercise_status"]], ["2-14", "2-13"])
            self.assertEqual([s["status"] for s in result["exercise_status"]], ["found", "found"])
            self.assertEqual([s["question_number"] for s in result["sources"]], ["2-14", "2-13"])
            self.assertEqual(result["sources"][0]["page"], "1")
            self.assertEqual(result["sources"][1]["page"], "2, 3")

    def test_source_excerpt_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb"
            cache = root / "cache"
            seed_source(
                kb,
                cache,
                "book.pdf",
                simple_blocks("2-13 " + "甲" * 300),
            )
            blocks = [
                text("第二章 磁场"),
                text("习题"),
                text("2-14 题", 4),
                {"type": "image", "image_caption": ["图2-14"], "original_page": 5},
            ]
            seed_source(kb, cache, "figures.pdf", blocks)
            first = lookup_exercises("习题2-13 2-14", kb, cache)
            second = lookup_exercises("习题2-13 2-14", kb, cache)
            by_question = {s["question_number"]: s for s in first["sources"]}
            self.assertEqual(len(by_question), 2)
            plain = by_question["2-13"]
            full_text = "2-13 " + "甲" * 300
            self.assertEqual(plain["content"], full_text[:200])
            self.assertEqual(plain["score"], 1.0)
            self.assertFalse(plain["requires_page_review"])
            self.assertEqual(plain["exercise_kind"], "习题")
            self.assertTrue(plain["chunk_id"].startswith("exercise-"))
            self.assertEqual(len(plain["chunk_id"]), len("exercise-") + 20)
            self.assertEqual(
                plain["chunk_id"],
                next(s["chunk_id"] for s in second["sources"] if s["question_number"] == "2-13"),
            )
            figured = by_question["2-14"]
            self.assertTrue(figured["requires_page_review"])
            self.assertEqual(figured["page"], "4, 5")


class BlockHelperTests(unittest.TestCase):
    def test_text_joins_lists_dedups_and_skips_blank(self):
        block = {"type": "text", "text": "A", "content": ["B", "A"], "body": "   "}
        self.assertEqual(_text(block), "A\n\nB\nA")
        self.assertEqual(_text({"type": "text", "text": "A", "content": "A"}), "A")
        self.assertEqual(_text({"type": "text"}), "")

    def test_page_prefers_original_page_and_tolerates_garbage(self):
        self.assertEqual(_page({"original_page": "7"}), 7)
        self.assertEqual(_page({"original_page": None, "page_idx": 4}), 5)
        self.assertIsNone(_page({"page_idx": "x"}))
        self.assertIsNone(_page({}))
        self.assertIsNone(_page({"original_page": None}))


class ParseCacheUnitTests(unittest.TestCase):
    def test_parsed_cache_rejects_non_list_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cl.json"
            path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            st = path.stat()
            self.assertEqual(_parsed(str(path), st.st_mtime_ns, st.st_size), ())
            path.write_text(
                json.dumps([text("第二章"), text("习题"), text("2-13 甲")]), encoding="utf-8"
            )
            os.utime(path, ns=(T1, T1))
            st = path.stat()
            exercises = _parsed(str(path), st.st_mtime_ns, st.st_size)
            self.assertEqual([(e.chapter, e.number) for e in exercises], [(2, 13)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
