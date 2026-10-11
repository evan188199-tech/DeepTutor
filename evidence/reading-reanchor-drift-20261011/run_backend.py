"""Offline drift fixture for the reading selector re-anchor path.

Exercises the real ``ReadingStore.ingest_units`` -> ``_reanchor_annotations``
pipeline against a matrix of document-drift scenarios (title edits, paragraph
insert/delete, word edits, duplicates, unit moves/removal, legacy rows,
stale context compounding, case and unicode normalisation). No server, no
network: every scenario runs against a throwaway store root.

Run with the project virtualenv:

    /Users/Shared/DeepTutor/.venv/bin/python run_backend.py --out backend_results.json

Read-only with respect to the repository source: the store writes only inside
a TemporaryDirectory.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from deeptutor.reading.models import (  # noqa: E402
    Annotation,
    TextPositionSelector,
    TextQuoteSelector,
)
from deeptutor.reading.store import (  # noqa: E402
    ReadingStore,
    _normalise_selector_text,
)

MATERIAL_ID = "abcdef0123456789"
CONTEXT = 10

BASE_UNITS = [
    "# Alpha Theory\n\nThe quick brown fox jumps over the lazy dog.\n\n"
    "A closing paragraph discusses energy budgets in cells.",
    "# Beta Practice\n\nMitochondria convert glucose into ATP via oxidative "
    "phosphorylation.\n\nThe summary section repeats key claims for revision.",
    "# Gamma Review\n\nFinal remarks collect the threads of the argument.",
]


def quote_selectors_for(text: str, phrase: str, *, with_context: bool = True) -> tuple:
    start = text.index(phrase)
    end = start + len(phrase)
    if not with_context:
        return (TextQuoteSelector(exact=phrase),)
    return (
        TextQuoteSelector(
            exact=phrase,
            prefix=text[max(0, start - CONTEXT) : start],
            suffix=text[end : end + CONTEXT],
        ),
        TextPositionSelector(start=start, end=end),
    )


def save_mark(store: ReadingStore, aid: str, locator: int, phrase: str, *, with_context: bool = True) -> None:
    text = store.unit_text(MATERIAL_ID, locator)
    store.save_annotation(
        MATERIAL_ID,
        Annotation(
            annotation_id=aid,
            locator=locator,
            quote=phrase,
            selectors=quote_selectors_for(text, phrase, with_context=with_context),
        ),
    )


def save_legacy(store: ReadingStore, aid: str, locator: int, phrase: str) -> None:
    store.save_annotation(
        MATERIAL_ID,
        Annotation(annotation_id=aid, locator=locator, quote=phrase),
    )


def save_position_only(store: ReadingStore, aid: str, locator: int, phrase: str) -> None:
    text = store.unit_text(MATERIAL_ID, locator)
    start = text.index(phrase)
    store.save_annotation(
        MATERIAL_ID,
        Annotation(
            annotation_id=aid,
            locator=locator,
            quote=phrase,
            selectors=(TextPositionSelector(start=start, end=start + len(phrase)),),
        ),
    )


def describe_rows(store: ReadingStore) -> dict:
    manifest = store.manifest(MATERIAL_ID)
    rows = {}
    for row in store.annotations(MATERIAL_ID):
        quote_sel = next(
            (s for s in row.selectors if isinstance(s, TextQuoteSelector)), None
        )
        pos_sel = next(
            (s for s in row.selectors if isinstance(s, TextPositionSelector)), None
        )
        entry = {
            "resolution": row.resolution,
            "locator": row.locator,
            "material_revision": row.material_revision,
            "locator_in_range": row.locator <= manifest.unit_count,
            "quote": row.quote,
            "has_quote_selector": quote_sel is not None,
            "has_position_selector": pos_sel is not None,
        }
        unit_text = (
            store.unit_text(MATERIAL_ID, row.locator)
            if row.locator <= manifest.unit_count
            else None
        )
        if quote_sel is not None and pos_sel is not None and unit_text is not None:
            entry["position_in_range"] = pos_sel.end <= len(unit_text)
            if entry["position_in_range"]:
                span_text = unit_text[pos_sel.start : pos_sel.end]
                entry["position_matches_quote"] = (
                    _normalise_selector_text(span_text)
                    == _normalise_selector_text(quote_sel.exact)
                )
                entry["partial_word_anchor"] = bool(
                    (pos_sel.start > 0 and unit_text[pos_sel.start - 1].isalnum())
                    or (pos_sel.end < len(unit_text) and unit_text[pos_sel.end].isalnum())
                )
                preceding = _normalise_selector_text(unit_text[: pos_sel.start])
                following = _normalise_selector_text(unit_text[pos_sel.end :])
            else:
                entry["position_matches_quote"] = False
                entry["partial_word_anchor"] = None
                entry["stored_prefix_stale"] = None
                entry["stored_suffix_stale"] = None
                preceding = following = ""
            entry["stored_prefix_stale"] = bool(
                quote_sel.prefix
                and not preceding.endswith(_normalise_selector_text(quote_sel.prefix))
            )
            entry["stored_suffix_stale"] = bool(
                quote_sel.suffix
                and not following.startswith(_normalise_selector_text(quote_sel.suffix))
            )
        rows[row.annotation_id] = entry
    return {
        "revision": manifest.revision,
        "unit_count": manifest.unit_count,
        "annotations": rows,
    }


SCENARIOS: list[tuple[str, callable]] = []


def scenario(name):
    def register(fn):
        SCENARIOS.append((name, fn))
        return fn

    return register


@scenario("control_unchanged")
def scenario_control():
    def build(store):
        save_mark(store, "a_title", 1, "Alpha Theory")
        save_mark(store, "a_mid", 1, "quick brown fox")

    return {"build": build, "steps": [list(BASE_UNITS)]}


@scenario("whitespace_reflow")
def scenario_whitespace():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nThe quick  brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("title_edited")
def scenario_title():
    def build(store):
        save_mark(store, "a_title", 1, "Alpha Theory")
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory (Revised)\n\nThe quick brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("paragraph_inserted_before")
def scenario_insert():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nA brand new opening paragraph appears here first.\n\n"
        "The quick brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("paragraph_deleted")
def scenario_delete():
    def build(store):
        save_mark(store, "a_end", 1, "energy budgets in cells")
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nThe quick brown fox jumps over the lazy dog.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("word_replaced")
def scenario_word_replaced():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nThe swift brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("word_extended")
def scenario_word_extended():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nThe quick brown foxes jump over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("duplicate_same_unit")
def scenario_duplicate_same_unit():
    def build(store):
        save_mark(store, "a_ctx", 1, "quick brown fox", with_context=True)
        save_mark(store, "a_noctx", 1, "quick brown fox", with_context=False)

    drifted = [
        "# Alpha Theory\n\nThe quick brown fox jumps over the lazy dog.\n\n"
        "Recall that the quick brown fox jumps over the lazy dog again.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("duplicate_across_units")
def scenario_duplicate_cross():
    def build(store):
        save_mark(store, "a_u2", 2, "The summary section repeats key claims for revision.")

    drifted = [
        "# Alpha Theory\n\nThe quick brown fox jumps over the lazy dog.\n\n"
        "The summary section repeats key claims for revision.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("sentence_moved_across_units")
def scenario_moved():
    def build(store):
        save_mark(
            store, "a_u2", 2,
            "Mitochondria convert glucose into ATP via oxidative phosphorylation.",
        )

    drifted = [
        BASE_UNITS[0],
        "# Beta Practice\n\nThe summary section repeats key claims for revision.",
        "# Gamma Review\n\nMitochondria convert glucose into ATP via oxidative "
        "phosphorylation.\n\nFinal remarks collect the threads of the argument.",
    ]
    return {"build": build, "steps": [drifted]}


@scenario("unit_removed")
def scenario_unit_removed():
    def build(store):
        save_mark(store, "a_gamma", 3, "Final remarks collect the threads")
        save_legacy(store, "a_legacy_u3", 3, "Final remarks collect the threads")
        save_position_only(store, "a_posonly_u3", 3, "Final remarks collect the threads")

    drifted = [BASE_UNITS[0], BASE_UNITS[1]]
    return {"build": build, "steps": [drifted]}


@scenario("legacy_quote_only_survives")
def scenario_legacy():
    def build(store):
        save_legacy(store, "a_legacy", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nIntro added. The quick brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("stale_context_compound")
def scenario_stale_context():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    step1 = [
        "# Alpha Theory\n\nA long new introduction now stands before the passage. "
        "The quick brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    step2 = [
        "# Alpha Theory\n\nA long new introduction now stands before the passage. "
        "The quick brown fox jumps over the lazy dog.\n\n"
        "Repeat: the quick brown fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [step1, step2]}


@scenario("case_change")
def scenario_case():
    def build(store):
        save_mark(store, "a_mid", 1, "quick brown fox")

    drifted = [
        "# Alpha Theory\n\nThe Quick Brown Fox jumps over the lazy dog.\n\n"
        "A closing paragraph discusses energy budgets in cells.",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    return {"build": build, "steps": [drifted]}


@scenario("unicode_nfd_drift")
def scenario_unicode():
    phrase_nfc = unicodedata.normalize("NFC", "café résumé")
    tail = "A closing paragraph discusses energy budgets in cells."
    base = [
        f"# Alpha Theory\n\nNotes on {phrase_nfc} in the corpus.\n\n{tail}",
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]
    drifted = [
        "# Alpha Theory\n\nNotes on "
        + unicodedata.normalize("NFD", phrase_nfc)
        + " in the corpus.\n\n" + tail,
        BASE_UNITS[1],
        BASE_UNITS[2],
    ]

    def build(store):
        save_mark(store, "a_nfc", 1, phrase_nfc)

    return {"build": build, "steps": [drifted], "base": base}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="backend_results.json")
    args = parser.parse_args()

    out = []
    for name, fn in SCENARIOS:
        with tempfile.TemporaryDirectory() as td:
            store = ReadingStore(root=Path(td))
            spec = fn()
            store.ingest_units(
                MATERIAL_ID,
                filename="base.md",
                units=list(spec.get("base", BASE_UNITS)),
                source_type="url_snapshot",
            )
            build = spec.get("build")
            if build is not None:
                build(store)
            states = [{"step": "base", **describe_rows(store)}]
            for i, units in enumerate(spec["steps"], start=1):
                store.ingest_units(
                    MATERIAL_ID,
                    filename=f"drift-{i}.md",
                    units=list(units),
                    source_type="url_snapshot",
                )
                states.append({"step": f"drift-{i}", **describe_rows(store)})
        out.append({"scenario": name, "states": states})

    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {args.out}: {len(out)} scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
