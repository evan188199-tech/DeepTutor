"""Unit coverage for the bounded practice import parsers."""

from __future__ import annotations

import io
import json
import zipfile

from openpyxl import Workbook
import pytest

from deeptutor.services.practice.importing import (
    MAX_BYTES,
    MAX_ROWS,
    normalize_question,
    parse_rows,
    preview,
)


def xlsx_bytes(rows: list[list]) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_json_array_rows_are_numbered_from_one():
    rows = parse_rows(json.dumps([{"question": "Q1"}, {"question": "Q2"}]).encode(), "q.json")
    assert [number for number, _ in rows] == [1, 2]
    assert rows[1][1] == {"question": "Q2"}


def test_json_needs_an_array_of_objects():
    for data in (b'{"question": "Q"}', b'[["Q"]]', b"null"):
        with pytest.raises(ValueError, match="JSON"):
            parse_rows(data, "q.json")


def test_json_bom_is_stripped():
    rows = parse_rows(b"\xef\xbb\xbf" + json.dumps([{"question": "Q"}]).encode(), "q.json")
    assert rows[0][1]["question"] == "Q"


def test_json_row_limit_is_enforced():
    with pytest.raises(ValueError, match="500"):
        parse_rows(json.dumps([{"question": "Q"}] * (MAX_ROWS + 1)).encode(), "q.json")


def test_oversized_and_empty_payloads_are_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        parse_rows(b"", "q.json")
    with pytest.raises(ValueError, match="5 MB"):
        parse_rows(b"0" * (MAX_BYTES + 1), "q.json")
    with pytest.raises(ValueError, match="Supported formats"):
        parse_rows(b"x", "q.pdf")


def test_csv_decodes_bom_and_gb18030_files():
    bom = parse_rows("﻿question,answer\nQ,A\n".encode("utf-8"), "q.csv")
    assert bom[0][1] == {"question": "Q", "answer": "A"}
    chinese = parse_rows("题目,答案\n1+1,2\n".encode("gb18030"), "q.csv")
    assert chinese[0][1] == {"题目": "1+1", "答案": "2"}


def test_csv_duplicate_headers_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        parse_rows(b"question,Question\nQ,A\n", "q.csv")


def test_csv_blank_rows_are_skipped_and_data_rows_numbered_from_two():
    rows = parse_rows(b"question,answer\nQ,A\n\n\nQ2,B\n", "q.csv")
    assert [number for number, _ in rows] == [2, 5]


def test_csv_column_and_row_limits_are_enforced():
    wide = b"question,answer," + b",".join([b"c"] * 63) + b"\nQ,A," + b",".join([b"x"] * 63) + b"\n"
    with pytest.raises(ValueError, match="64 columns"):
        parse_rows(wide, "q.csv")
    many = b"question,answer\n" + b"Q,A\n" * (MAX_ROWS + 1)
    with pytest.raises(ValueError, match="500"):
        parse_rows(many, "q.csv")


def test_corrupt_workbook_raises_bad_zip_file():
    with pytest.raises(zipfile.BadZipFile):
        parse_rows(b"not a workbook", "q.xlsx")


def test_workbook_with_too_many_parts_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(2001):
            archive.writestr(f"xl/part{index}.xml", "<x/>")
    with pytest.raises(ValueError, match="too many parts"):
        parse_rows(buffer.getvalue(), "q.xlsx")


def test_xlsx_formulas_are_rejected_and_values_round_trip():
    with pytest.raises(ValueError, match="formulas"):
        parse_rows(xlsx_bytes([["question", "answer"], ["=1+1", "2"]]), "q.xlsx")
    rows = parse_rows(xlsx_bytes([["question", "answer"], ["Q", "2"]]), "q.xlsx")
    assert rows == [(2, {"question": "Q", "answer": "2"})]


def test_xlsx_without_data_rows_is_empty():
    assert parse_rows(xlsx_bytes([["question", "answer"]]), "q.xlsx") == []
    with pytest.raises(ValueError, match="no questions"):
        preview(xlsx_bytes([["question", "answer"]]), "q.xlsx")


def test_question_and_answer_are_required():
    for row in ({"answer": "A"}, {"question": "Q"}, {}):
        with pytest.raises(ValueError, match="required"):
            normalize_question(row)


def test_chinese_aliases_and_type_synonyms_resolve():
    row = normalize_question(
        {
            "题干": "2+2=?",
            "题型": "单选题",
            "A": "3",
            "B": "4",
            "答案": "B",
            "解析": "算术",
            "难度": "易",
        }
    )
    assert row["question"] == "2+2=?"
    assert row["question_type"] == "single_choice"
    assert row["options"] == {"A": "3", "B": "4"}
    assert row["correct_answer"] == "B"
    assert row["explanation"] == "算术"
    assert row["difficulty"] == "易"


def test_options_accept_json_strings_lists_and_dicts():
    listed = normalize_question({"question": "Q", "options": ["x", "y"], "answer": "A"})
    assert listed["options"] == {"A": "x", "B": "y"}
    assert listed["question_type"] == "single_choice"
    dumped = normalize_question(
        {"question": "Q", "options": json.dumps({"A": "x", "B": "y"}), "answer": "A"}
    )
    assert dumped["options"] == {"A": "x", "B": "y"}
    with pytest.raises(json.JSONDecodeError):
        normalize_question({"question": "Q", "options": "{bad", "answer": "A"})


def test_option_count_is_capped_at_ten():
    options = {chr(65 + i): str(i) for i in range(11)}
    with pytest.raises(ValueError, match="10 named choices"):
        normalize_question({"question": "Q", "options": options, "answer": "A"})


def test_true_false_answers_are_normalized_to_t_or_f():
    true_row = normalize_question({"question": "Q", "题型": "判断", "answer": "正确"})
    assert true_row["question_type"] == "true_false"
    assert true_row["options"] == {"T": "True", "F": "False"}
    assert true_row["correct_answer"] == "T"
    assert (
        normalize_question({"question": "Q", "question_type": "true_false", "answer": "0"})[
            "correct_answer"
        ]
        == "F"
    )
    with pytest.raises(ValueError, match="true or false"):
        normalize_question({"question": "Q", "question_type": "判断题", "answer": "maybe"})


def test_choice_answers_must_name_existing_option_keys():
    base = {"question": "Q", "question_type": "single_choice", "options": {"A": "3", "B": "4"}}
    assert normalize_question({**base, "answer": "4"})["correct_answer"] == "B"
    multi = {"question": "Q", "question_type": "多选题", "options": {"A": "1", "B": "2", "C": "3"}}
    assert normalize_question({**multi, "answer": "CA"})["correct_answer"] == "A,C"
    assert normalize_question({**multi, "answer": "a,c"})["correct_answer"] == "A,C"
    with pytest.raises(ValueError, match="existing option keys"):
        normalize_question({**base, "answer": "Z"})
    with pytest.raises(ValueError, match="existing option keys"):
        normalize_question({**base, "answer": "A,B"})
    with pytest.raises(ValueError, match="two options"):
        normalize_question(
            {"question": "Q", "question_type": "单选", "options": {"A": "1"}, "answer": "A"}
        )


def test_missing_type_defaults_from_options():
    assert (
        normalize_question({"question": "Q", "answer": "anything"})["question_type"]
        == "short_answer"
    )
    with pytest.raises(ValueError, match="Unknown question type"):
        normalize_question({"question": "Q", "question_type": "quantum", "answer": "A"})


def test_tags_are_split_deduplicated_and_bounded():
    row = normalize_question({"question": "Q", "answer": "A", "tags": "数学, 复习;数学，错题"})
    assert row["tags"] == ["数学", "复习", "错题"]
    with pytest.raises(ValueError, match="20 tags"):
        normalize_question({"question": "Q", "answer": "A", "tags": [f"t{i}" for i in range(21)]})
    with pytest.raises(ValueError, match="100 characters"):
        normalize_question({"question": "Q", "answer": "A", "tags": ["x" * 101]})


def test_question_id_hashes_only_the_identity_fields():
    base = {
        "question": "Q",
        "question_type": "single_choice",
        "options": {"A": "1", "B": "2"},
        "answer": "A",
    }
    tagged = normalize_question({**base, "tags": "数学"})
    plain = normalize_question(base)
    other = normalize_question({**base, "question": "Q2"})
    assert tagged["question_id"] == plain["question_id"]
    assert tagged["question_id"].startswith("import:")
    assert other["question_id"] != plain["question_id"]


def test_preview_reports_row_errors_alongside_valid_questions():
    result = preview(b"question,answer\nQ,A\n\nR,\n", "q.csv")
    assert [row["question"] for row in result["questions"]] == ["Q"]
    assert result["errors"] == [{"row": 4, "message": "Question and correct answer are required"}]
