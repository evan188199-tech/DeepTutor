"""Contract tests for the bounded practice import parsers.

These tests exercise ``deeptutor.services.practice.importing`` as a pure
parser: files are written to ``tmp_path`` and fed in as bytes, and no
storage backend is involved (the storage boundary is mocked out by
simply not existing here).
"""

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


def write_bytes(tmp_path, name: str, payload: bytes):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def xlsx_bytes(rows: list[list]) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


# --- import parsing -------------------------------------------------------


def test_json_import_numbers_rows_from_one(tmp_path):
    payload = json.dumps([{"question": "Q1"}, {"question": "Q2"}]).encode()
    rows = parse_rows(write_bytes(tmp_path, "q.json", payload).read_bytes(), "q.json")
    assert [number for number, _ in rows] == [1, 2]
    assert rows[1][1] == {"question": "Q2"}


def test_json_strips_a_utf8_bom(tmp_path):
    payload = b"\xef\xbb\xbf" + json.dumps([{"question": "Q"}]).encode()
    rows = parse_rows(write_bytes(tmp_path, "q.json", payload).read_bytes(), "q.json")
    assert rows[0][1]["question"] == "Q"


def test_csv_decodes_bom_and_gb18030_files(tmp_path):
    bom = write_bytes(tmp_path, "bom.csv", "question,answer\nQ,A\n".encode("utf-8"))
    assert bom and parse_rows(bom.read_bytes(), "bom.csv")[0][1] == {
        "question": "Q",
        "answer": "A",
    }
    chinese = write_bytes(tmp_path, "cn.csv", "题目,答案\n1+1,2\n".encode("gb18030"))
    assert parse_rows(chinese.read_bytes(), "cn.csv")[0][1] == {"题目": "1+1", "答案": "2"}


def test_tsv_rows_split_on_tabs(tmp_path):
    path = write_bytes(tmp_path, "q.tsv", b"question\tanswer\nQ\tA\n")
    rows = parse_rows(path.read_bytes(), "q.tsv")
    assert rows == [(2, {"question": "Q", "answer": "A"})]


def test_xlsx_values_round_trip_with_lowered_headers(tmp_path):
    path = tmp_path / "q.xlsx"
    path.write_bytes(xlsx_bytes([["Question", "Answer"], ["Q", "A"]]))
    assert parse_rows(path.read_bytes(), "q.xlsx") == [(2, {"question": "Q", "answer": "A"})]


def test_short_rows_zip_against_headers_without_raising(tmp_path):
    path = write_bytes(tmp_path, "q.csv", b"question,answer\nQ\n")
    rows = parse_rows(path.read_bytes(), "q.csv")
    assert rows == [(2, {"question": "Q"})]


def test_blank_data_rows_are_skipped_and_data_rows_number_from_two(tmp_path):
    path = write_bytes(tmp_path, "q.csv", b"question,answer\nQ,A\n\n\nQ2,B\n")
    rows = parse_rows(path.read_bytes(), "q.csv")
    assert [number for number, _ in rows] == [2, 5]


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
            "我的答案": "A",
        }
    )
    assert row["question"] == "2+2=?"
    assert row["question_type"] == "single_choice"
    assert row["options"] == {"A": "3", "B": "4"}
    assert row["correct_answer"] == "B"
    assert row["explanation"] == "算术"
    assert row["difficulty"] == "易"
    assert row["user_answer"] == "A"


def test_options_accept_json_strings_lists_dicts_and_letter_columns():
    listed = normalize_question({"question": "Q", "options": ["x", "y"], "answer": "A"})
    assert listed["options"] == {"A": "x", "B": "y"}
    assert listed["question_type"] == "single_choice"
    dumped = normalize_question(
        {"question": "Q", "options": json.dumps({"A": "x", "B": "y"}), "answer": "A"}
    )
    assert dumped["options"] == {"A": "x", "B": "y"}
    letters = normalize_question({"question": "Q", "选项a": "3", "b": "4", "answer": "4"})
    assert letters["options"] == {"A": "3", "B": "4"}
    assert letters["correct_answer"] == "B"


# --- field validation rejection paths -------------------------------------


def test_empty_oversized_and_unknown_formats_are_rejected(tmp_path):
    for payload, name, match in (
        (b"", "q.json", "non-empty"),
        (b"0" * (MAX_BYTES + 1), "q.json", "5 MB"),
        (b"x", "q.pdf", "Supported formats"),
    ):
        with pytest.raises(ValueError, match=match):
            parse_rows(write_bytes(tmp_path, name, payload).read_bytes(), name)


def test_json_must_be_an_array_of_objects_within_the_row_limit(tmp_path):
    for payload in (b'{"question": "Q"}', b'[["Q"]]', b"null"):
        with pytest.raises(ValueError, match="JSON"):
            parse_rows(write_bytes(tmp_path, "q.json", payload).read_bytes(), "q.json")
    ok = json.dumps([{"question": "Q"}] * MAX_ROWS).encode()
    assert len(parse_rows(write_bytes(tmp_path, "ok.json", ok).read_bytes(), "ok.json")) == MAX_ROWS
    over = json.dumps([{"question": "Q"}] * (MAX_ROWS + 1)).encode()
    with pytest.raises(ValueError, match="500"):
        parse_rows(write_bytes(tmp_path, "over.json", over).read_bytes(), "over.json")


def test_csv_header_column_and_row_limits_are_enforced(tmp_path):
    duplicate = write_bytes(tmp_path, "dup.csv", b"question,Question\nQ,A\n")
    with pytest.raises(ValueError, match="unique"):
        parse_rows(duplicate.read_bytes(), "dup.csv")
    wide = write_bytes(
        tmp_path,
        "wide.csv",
        b"question,answer," + b",".join([b"c"] * 63) + b"\nQ,A," + b",".join([b"x"] * 63) + b"\n",
    )
    with pytest.raises(ValueError, match="64 columns"):
        parse_rows(wide.read_bytes(), "wide.csv")
    many = write_bytes(tmp_path, "many.csv", b"question,answer\n" + b"Q,A\n" * (MAX_ROWS + 1))
    with pytest.raises(ValueError, match="500"):
        parse_rows(many.read_bytes(), "many.csv")


def test_oversized_cells_are_rejected(tmp_path):
    header = write_bytes(tmp_path, "hdr.csv", b"question," + b"x" * 20001 + b"\nQ,A\n")
    with pytest.raises(ValueError, match="20,000 characters"):
        parse_rows(header.read_bytes(), "hdr.csv")
    path = write_bytes(tmp_path, "big.csv", b"question,answer\nQ," + b"x" * 20001 + b"\n")
    result = preview(path.read_bytes(), "big.csv")
    assert result["questions"] == []
    assert result["errors"] == [{"row": 2, "message": "A cell exceeds 20,000 characters"}]


def test_corrupt_workbook_surfaces_the_zip_error(tmp_path):
    path = write_bytes(tmp_path, "q.xlsx", b"not a workbook")
    with pytest.raises(zipfile.BadZipFile):
        parse_rows(path.read_bytes(), "q.xlsx")


def test_workbook_part_and_expanded_size_limits_are_rejected(tmp_path):
    bloated = io.BytesIO()
    with zipfile.ZipFile(bloated, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/heavy.xml", b"0" * (31 * 1024 * 1024))
    path = write_bytes(tmp_path, "heavy.xlsx", bloated.getvalue())
    with pytest.raises(ValueError, match="30 MB"):
        parse_rows(path.read_bytes(), "heavy.xlsx")
    many_parts = io.BytesIO()
    with zipfile.ZipFile(many_parts, "w") as archive:
        for index in range(2001):
            archive.writestr(f"xl/part{index}.xml", "<x/>")
    path = write_bytes(tmp_path, "parts.xlsx", many_parts.getvalue())
    with pytest.raises(ValueError, match="too many parts"):
        parse_rows(path.read_bytes(), "parts.xlsx")


def test_xlsx_formulas_and_column_limits_are_rejected(tmp_path):
    formula = tmp_path / "formula.xlsx"
    formula.write_bytes(xlsx_bytes([["question", "answer"], ["=1+1", "2"]]))
    with pytest.raises(ValueError, match="formulas"):
        parse_rows(formula.read_bytes(), "formula.xlsx")
    wide = tmp_path / "wide.xlsx"
    wide.write_bytes(xlsx_bytes([["question", "answer", *(f"c{i}" for i in range(63))]]))
    with pytest.raises(ValueError, match="64 columns"):
        parse_rows(wide.read_bytes(), "wide.xlsx")


def test_question_and_correct_answer_are_required():
    for row in ({"answer": "A"}, {"question": "Q"}, {}):
        with pytest.raises(ValueError, match="required"):
            normalize_question(row)


def test_unknown_question_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown question type"):
        normalize_question({"question": "Q", "question_type": "quantum", "answer": "A"})


def test_true_false_answers_must_be_boolean_like():
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


def test_choice_questions_need_two_options_and_known_answer_keys():
    base = {"question": "Q", "question_type": "single_choice", "options": {"A": "3", "B": "4"}}
    assert normalize_question({**base, "answer": "4"})["correct_answer"] == "B"
    multi = {"question": "Q", "question_type": "多选题", "options": {"A": "1", "B": "2", "C": "3"}}
    assert normalize_question({**multi, "answer": "CA"})["correct_answer"] == "A,C"
    assert normalize_question({**multi, "answer": "a,c"})["correct_answer"] == "A,C"
    with pytest.raises(ValueError, match="two options"):
        normalize_question(
            {"question": "Q", "question_type": "单选", "options": {"A": "1"}, "answer": "A"}
        )
    with pytest.raises(ValueError, match="existing option keys"):
        normalize_question({**base, "answer": "Z"})
    with pytest.raises(ValueError, match="existing option keys"):
        normalize_question({**base, "answer": "A,B"})


def test_option_count_and_malformed_option_json_are_rejected():
    with pytest.raises(ValueError, match="10 named choices"):
        normalize_question(
            {"question": "Q", "options": {chr(65 + i): str(i) for i in range(11)}, "answer": "A"}
        )
    with pytest.raises(json.JSONDecodeError):
        normalize_question({"question": "Q", "options": "{bad", "answer": "A"})


def test_tag_limits_are_enforced():
    with pytest.raises(ValueError, match="20 tags"):
        normalize_question({"question": "Q", "answer": "A", "tags": [f"t{i}" for i in range(21)]})
    with pytest.raises(ValueError, match="100 characters"):
        normalize_question({"question": "Q", "answer": "A", "tags": ["x" * 101]})


def test_tags_are_split_deduplicated_and_kept_in_order():
    row = normalize_question({"question": "Q", "answer": "A", "tags": "数学, 复习;数学，错题"})
    assert row["tags"] == ["数学", "复习", "错题"]


# --- batch partial-failure semantics --------------------------------------


def test_preview_separates_valid_questions_from_row_errors(tmp_path):
    path = write_bytes(tmp_path, "mixed.csv", b"question,answer\nQ,A\n\nR,\n")
    result = preview(path.read_bytes(), "mixed.csv")
    assert [row["question"] for row in result["questions"]] == ["Q"]
    assert result["errors"] == [{"row": 4, "message": "Question and correct answer are required"}]


def test_preview_reports_every_rejected_row_in_file_order(tmp_path):
    payload = b"question,answer,question_type\nQ1,A1,\nQ2,\nQ3,A3,quantum\nQ4,A4,\n"
    path = write_bytes(tmp_path, "mixed.csv", payload)
    result = preview(path.read_bytes(), "mixed.csv")
    assert [row["question"] for row in result["questions"]] == ["Q1", "Q4"]
    assert [error["row"] for error in result["errors"]] == [3, 4]
    assert "required" in result["errors"][0]["message"]
    assert "Unknown question type" in result["errors"][1]["message"]


def test_preview_of_a_file_where_every_row_fails_reports_only_errors(tmp_path):
    path = write_bytes(tmp_path, "bad.csv", b"question,answer\nQ,\nR,\n")
    result = preview(path.read_bytes(), "bad.csv")
    assert result["questions"] == []
    assert [error["row"] for error in result["errors"]] == [2, 3]


def test_headers_only_file_contains_no_questions(tmp_path):
    path = write_bytes(tmp_path, "empty.csv", b"question,answer\n")
    assert parse_rows(path.read_bytes(), "empty.csv") == []
    with pytest.raises(ValueError, match="no questions"):
        preview(path.read_bytes(), "empty.csv")


def test_question_identity_is_stable_and_ignores_non_identity_fields():
    base = {
        "question": "Q",
        "question_type": "single_choice",
        "options": {"A": "1", "B": "2"},
        "answer": "A",
    }
    plain = normalize_question(base)
    tagged = normalize_question({**base, "tags": "数学", "explanation": "why"})
    assert plain["question_id"].startswith("import:")
    assert tagged["question_id"] == plain["question_id"]
    assert normalize_question({**base, "question": "Q2"})["question_id"] != plain["question_id"]
