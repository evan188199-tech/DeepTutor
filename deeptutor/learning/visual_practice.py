"""Source-bound visual questions, conservative keys and explicit assistance (#1611).

Free-form replies extend the assessment boundary along the shared
``AssessmentResult`` taxonomy (#1901): the deterministic alias/choice fast
paths stay first, detectable contradictions (negation, reversed
relationships, label misplacement) grade incorrect with a specific
diagnosis, and everything else defers to an on-demand qualitative evaluator
whose uncertainty stays ungraded instead of inventing a score.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import re
from typing import Any
import unicodedata

# Optional qualitative evaluator for free-form replies (#1901). It receives a
# compact, source-appropriate reference and answers with one of the shared
# assessment verdicts: correct / partial / incorrect / unreliable. It is only
# consulted after the deterministic fast paths — never on every answer.
SemanticEvaluator = Callable[[dict[str, Any]], "dict[str, Any] | None"]

SEMANTIC_VERDICTS = frozenset({"correct", "partial", "incorrect", "unreliable"})


def normalized_answer(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", text).rstrip(".。!！")


def _answer_in_quote(answer: str, quote: str) -> bool:
    needle = normalized_answer(answer)
    if not needle:
        return False
    if needle.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", quote) is not None
    return needle in quote


def prepare_visual(
    request: dict[str, Any],
    *,
    expected_answer: str,
    options: dict[str, str],
    attached_kbs: list[str] | None = None,
    inspected_image_hashes: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    from deeptutor.multi_user.knowledge_access import resolve_for_rag
    from deeptutor.services.rag.kb_paths import resolve_kb_dir
    from deeptutor.services.rag.source_visuals import retrieve_visual

    task = str(request.get("task") or "identification")
    if task not in {"identification", "relationship", "table_graph", "comparison"}:
        raise ValueError(
            "Visual tasks support identification, relationship, table_graph and comparison."
        )
    refs = request.get("sources")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 2:
        raise ValueError("Select one or two exact source figures/pages; comparisons require two.")
    if task == "comparison" and len(refs) != 2:
        raise ValueError("A visual comparison requires both original sources.")
    resolved = []
    source_text = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError("Each visual source must be an object.")
        kb_name = str(ref.get("kb_name") or "")
        if attached_kbs is not None and kb_name not in attached_kbs:
            raise ValueError(
                "Visual practice must use a knowledge base attached to this topic/turn."
            )
        resource = resolve_for_rag(kb_name)
        if resource is None:
            raise ValueError("The selected source knowledge base is not accessible.")
        selectors = {
            key: ref[key]
            for key in ("asset_id", "source_path", "page", "region", "source_hash", "figure")
            if ref.get(key) is not None
        }
        evidence = retrieve_visual(
            resolve_kb_dir(resource.base_dir, resource.name), kb_name, **selectors
        )
        if evidence.error or not evidence.images:
            raise ValueError(f"Cannot establish original visual evidence: {evidence.content}")
        record = evidence.images[0][0]
        resolved.append(
            {
                "kb_name": kb_name,
                "asset_id": record.get("asset_id") or "",
                "source_path": record["source_path"],
                "page": record.get("page_number"),
                "source_hash": record["source_document_id"],
                "region": record.get("region"),
                "image_url": evidence.sources[0]["visual_asset_url"],
                "url": evidence.sources[0]["url"],
                "image_sha256": sha256(evidence.images[0][1]).hexdigest(),
                "visible_answer_text": _answer_in_quote(
                    options.get(expected_answer, expected_answer),
                    normalized_answer(record.get("text", "")),
                ),
            }
        )
        source_text.append(
            "\n".join(
                str(record.get(key) or "")
                for key in ("caption", "context", "text", "page_context", "table_html", "notes")
            )
        )
    quote = str(request.get("reference_quote") or "").strip()[:3000]
    # Answer equivalences are explicit and source-specific, never fuzzy
    # substring/keyword overlap. Unknown prose is clarified, not penalized.
    correct_body = options.get(expected_answer, expected_answer)
    raw_aliases = request.get("accepted_answers") or []
    if not isinstance(raw_aliases, list) or len(raw_aliases) > 12:
        raise ValueError("accepted_answers must contain at most 12 verified equivalents.")
    aliases = list(
        dict.fromkeys(
            [correct_body, *[str(x).strip()[:200] for x in raw_aliases if str(x).strip()]]
        )
    )
    text = normalized_answer(re.sub(r"<[^>]+>", " ", "\n".join(source_text)))
    quote_normalized = normalized_answer(re.sub(r"<[^>]+>", " ", quote))
    verified = bool(
        quote_normalized
        and quote_normalized in text
        and _answer_in_quote(correct_body, quote_normalized)
        and request.get("key_status") == "verified"
    )
    cues = str(request.get("answer_cues") or "unverified")
    if cues not in {"none", "visible", "unverified"}:
        raise ValueError(
            "answer_cues must be none, visible or unverified; masking requires independently verified regions."
        )
    # Page text can reveal a table value directly. Treat it as guided reading,
    # even when the caller mistakenly declares no visible cue.
    inspected = (
        all(ref.get("image_sha256") in inspected_image_hashes for ref in resolved)
        if inspected_image_hashes is not None
        else bool(request.get("pixels_inspected"))
    )
    if not inspected:
        verified = False
        cues = "unverified"
    elif any(
        ref.get("page")
        and not ref.get("asset_id")
        and (not ref.get("region") or ref.get("visible_answer_text"))
        for ref in resolved
    ):
        cues = "visible"
    return {
        "task": task,
        "sources": resolved,
        "answer_cues": cues,
        "key_status": "verified" if verified else "unverified",
        "pixels_inspected": inspected,
        "reference_quote": quote,
        "reference_answer": correct_body,
        "hints_used": max(int(request.get("hints_used") or 0), int(cues != "none")),
    }, aliases


def public_visual(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: context[key]
        for key in (
            "task",
            "sources",
            "answer_cues",
            "key_status",
            "hints_used",
            "pixels_inspected",
        )
        if key in context
    }


def account_for_recent_assistance(context: dict[str, Any], attempts, kp_id: str) -> dict[str, Any]:
    """Use the existing retention session boundary, not a visual scheduler."""
    import time

    from deeptutor.learning.scheduler import _SAME_SESSION_DAYS

    def locations(visual):
        return {(ref.get("source_hash"), ref.get("page")) for ref in visual.get("sources", [])}

    current = locations(context)
    for attempt in reversed(attempts):
        prior = attempt.visual_context
        if (
            not attempt.voided
            and attempt.knowledge_point_id == kp_id
            and (
                prior.get("hints_used")
                or (
                    normalized_answer(prior.get("reference_quote", ""))
                    == normalized_answer(context.get("reference_quote", ""))
                    and normalized_answer(prior.get("reference_answer", ""))
                    == normalized_answer(context.get("reference_answer", ""))
                )
            )
            and prior.get("task") == context.get("task")
            and locations(prior) == current
            and time.time() - attempt.timestamp < _SAME_SESSION_DAYS * 86400
        ):
            return {
                **context,
                "hints_used": max(1, context.get("hints_used", 0)),
                "recently_assisted": True,
            }
    return context


def evaluate_visual(
    pending, answer: str, *, semantic_evaluator: SemanticEvaluator | None = None
) -> tuple[str, str]:
    """Return (result, diagnosis); uncertainty produces no mastery evidence.

    ``result`` follows the shared assessment taxonomy: ``correct`` /
    ``incorrect`` from the deterministic fast paths and detectable
    contradictions, ``partial`` only from a qualitative evaluator, and
    ``ungraded`` whenever the reply cannot be reliably assessed.
    ``semantic_evaluator`` is consulted only for free-form replies that miss
    the alias and choice fast paths, so plain answers never pay for it.
    """
    from deeptutor.multi_user.knowledge_access import resolve_for_rag
    from deeptutor.services.rag.kb_paths import resolve_kb_dir
    from deeptutor.services.rag.source_visuals import retrieve_visual

    visual = pending.visual_context
    if not visual.get("pixels_inspected"):
        return (
            "ungraded",
            "No matching source pixels were verified in the tutor's model input. Re-retrieve the original image with a vision-capable model; this attempt does not lower mastery.",
        )
    if visual.get("key_status") != "verified" or not visual.get("sources"):
        return (
            "ungraded",
            "The reference key is not independently supported by source text; clarify it before grading.",
        )
    for ref in visual.get("sources", []):
        resource = resolve_for_rag(ref["kb_name"])
        if resource is None:
            return "ungraded", "Source access is unavailable; this attempt does not lower mastery."
        selectors = {
            key: ref[key]
            for key in ("asset_id", "source_path", "page", "region", "source_hash")
            if ref.get(key) not in (None, "")
        }
        evidence = retrieve_visual(
            resolve_kb_dir(resource.base_dir, resource.name), ref["kb_name"], **selectors
        )
        if evidence.error or not evidence.images:
            return (
                "ungraded",
                "Original source evidence changed or is unavailable; clarify the source before assessment.",
            )
    normalized = normalized_answer(answer)
    aliases = {normalized_answer(alias) for alias in pending.accepted_answers}
    if normalized in aliases:
        return "correct", "Accepted source-specific equivalent terminology."
    if pending.question_type == "choice":
        from deeptutor.learning.pending import is_readable_choice_answer, resolve_choice_submission

        if not is_readable_choice_answer(answer, pending.choice_map):
            return "ungraded", "Clarify the selected answer before assessing it."
        label = resolve_choice_submission(answer, pending.choice_map)
        if label:
            return (
                "correct" if label == pending.expected_answer else "incorrect"
            ), "Compare the chosen answer with the original source evidence."
    if not normalized:
        return "ungraded", "Clarify the answer before assessing it."
    contradiction = _detect_contradiction(pending, normalized)
    if contradiction is not None:
        return "incorrect", contradiction
    if semantic_evaluator is None:
        return (
            "ungraded",
            "This wording is not a verified equivalent. Ask for clarification or "
            "repair the reference; do not infer a wrong answer from surface similarity.",
        )
    try:
        outcome = semantic_evaluator(_semantic_reference(pending, answer)) or {}
    except Exception:  # noqa: BLE001 - an evaluator failure must never invent a grade
        outcome = {}
    verdict = str(outcome.get("verdict") or "").strip().lower()
    notes = str(outcome.get("diagnosis") or "").strip()[:400]
    if verdict == "correct":
        return (
            "correct",
            notes
            or "Qualitative assessment accepted the explanation as a source-grounded equivalent.",
        )
    if verdict == "partial":
        return (
            "partial",
            notes
            or "Partially correct: part of the required relationship is there; "
            "no full mastery is awarded.",
        )
    if verdict == "incorrect":
        return "incorrect", notes or "The explanation contradicts the source-grounded reference."
    return (
        "ungraded",
        notes
        or "The qualitative assessment could not reliably evaluate this wording "
        "against the source; no mastery evidence was recorded.",
    )


def _semantic_reference(pending, answer: str) -> dict[str, Any]:
    """Compact, source-appropriate reference for an on-demand qualitative check.

    Carries what the question actually assesses — the verified reference, the
    accepted equivalents, and the source anchors — without dumping the source
    corpus into the evaluation.
    """
    visual = pending.visual_context
    return {
        "task": str(visual.get("task") or "identification"),
        "question": pending.prompt,
        "question_type": pending.question_type,
        "answer": str(answer),
        "reference_answer": str(visual.get("reference_answer") or pending.expected_answer or ""),
        "reference_quote": str(visual.get("reference_quote") or ""),
        "accepted_answers": [str(alias) for alias in pending.accepted_answers],
        "answer_cues": visual.get("answer_cues"),
        "sources": [
            {
                key: ref.get(key)
                for key in ("kb_name", "source_path", "page", "region", "source_hash")
                if ref.get(key) not in (None, "")
            }
            for ref in visual.get("sources", [])
        ],
    }


_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?。\n！？]+")
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|without|cannot|can't|can’t|isn't|isn’t|aren't|aren’t|"
    r"doesn't|doesn’t|wasn't|wasn’t|won't|won’t)\b|非|不|没|无|未"
)
_EN_STOPWORDS = frozenset(
    "the a an is are was were be been being to of and or in on at it its this "
    "that which as with there here refers refer lies lie lying sits sit sitting "
    "structure number numbered label item figure panel".split()
)
# Relation phrases whose direction changes the meaning; en first, then zh.
_RELATION_INVERSE = {
    "left of": "right of",
    "right of": "left of",
    "above": "below",
    "below": "above",
    "anterior to": "posterior to",
    "posterior to": "anterior to",
    "superior to": "inferior to",
    "inferior to": "superior to",
    "larger than": "smaller than",
    "bigger than": "smaller than",
    "smaller than": "larger than",
    "faster than": "slower than",
    "slower than": "faster than",
    "左边": "右边",
    "右边": "左边",
    "左侧": "右侧",
    "右侧": "左侧",
    "上方": "下方",
    "下方": "上方",
    "前面": "后面",
    "后面": "前面",
    "大于": "小于",
    "小于": "大于",
    "快于": "慢于",
    "慢于": "快于",
}
_ZH_POSITION_RE = re.compile(
    r"([\u4e00-\u9fff]{1,6}?)在([\u4e00-\u9fff]{1,6}?)(?:的)?"
    r"(左边|右边|左侧|右侧|上方|下方|前面|后面)"
)
_ZH_COMPARATIVE_RE = re.compile(
    r"([\u4e00-\u9fff]{1,6}?)(大于|小于|快于|慢于)([\u4e00-\u9fff]{1,6}?)"
)
_LABEL_RE = re.compile(
    r"\b(?:number|numbered|label|structure|figure|panel|item)\s*#?\s*([0-9]+)\b", re.IGNORECASE
)
_ZH_LABEL_RE = re.compile(r"第\s*([0-9]+)\s*[号个]")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.lower()) if part.strip()]


def _term_in(term: str, sentence: str) -> bool:
    if not term:
        return False
    if term.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", sentence) is not None
    return term in sentence


def _affirmed_terms(sources: list[str]) -> list[str]:
    terms: list[str] = []
    for text in sources:
        for token in _TOKEN_RE.findall(str(text).lower()):
            if token.isdigit() or (token.isascii() and (len(token) < 3 or token in _EN_STOPWORDS)):
                continue
            if token not in terms:
                terms.append(token)
    return terms


def _en_statements(text: str) -> list[tuple[str, str, str]]:
    """Extract ``(entity, relation, entity)`` from English relation phrases."""
    lowered = re.sub(r"\s+", " ", text.lower())
    statements = []
    for phrase in _RELATION_INVERSE:
        if not phrase.isascii():
            continue
        for match in re.finditer(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lowered):
            before = [
                token
                for token in _TOKEN_RE.findall(lowered[: match.start()])
                if token not in _EN_STOPWORDS and not token.isdigit()
            ]
            after = [
                token
                for token in _TOKEN_RE.findall(lowered[match.end() :])
                if token not in _EN_STOPWORDS and not token.isdigit()
            ]
            if before and after:
                statements.append((before[-1], phrase, after[0]))
    return statements


def _zh_statements(text: str) -> list[tuple[str, str, str]]:
    statements = []
    for match in _ZH_POSITION_RE.finditer(text):
        statements.append((match.group(1), match.group(3), match.group(2)))
    for match in _ZH_COMPARATIVE_RE.finditer(text):
        statements.append((match.group(1), match.group(2), match.group(3)))
    return statements


def _overlaps(left: str, right: str) -> bool:
    return left == right or left in right or right in left


def _relation_conflict(reference: str, answer: str) -> str | None:
    """Flag only provable reversals; a restatement (either order) stays clean."""
    reference_statements = _en_statements(reference) + _zh_statements(reference)
    if not reference_statements:
        return None
    answer_statements = _en_statements(answer) + _zh_statements(answer)
    for entity, phrase, other in reference_statements:
        inverse = _RELATION_INVERSE[phrase]
        for answer_entity, answer_phrase, answer_other in answer_statements:
            same = _overlaps(entity, answer_entity) and _overlaps(other, answer_other)
            swapped = _overlaps(entity, answer_other) and _overlaps(other, answer_entity)
            if not (same or swapped):
                continue
            if (same and answer_phrase == phrase) or (swapped and answer_phrase == inverse):
                continue
            return (
                "The answer reverses the source relationship: the source states "
                f"'{entity} {phrase} {other}'."
            )
    return None


def _negation_conflict(
    reference_sentences: list[str], answer_sentences: list[str], affirmed_terms: list[str]
) -> str | None:
    """The answer negates a relationship the source affirms about the target."""
    for sentence in answer_sentences:
        present = [term for term in affirmed_terms if _term_in(term, sentence)]
        if not present or not _NEGATION_RE.search(sentence):
            continue
        supporting = [
            part for part in reference_sentences if any(_term_in(term, part) for term in present)
        ]
        if supporting and not any(_NEGATION_RE.search(part) for part in supporting):
            return (
                "The answer negates what the source affirms about "
                f"'{present[0]}'; recorded as a misconception, not uncertainty."
            )
    return None


def _label_conflict(reference: str, answer: str, affirmed_terms: list[str]) -> str | None:
    """The answer pins the target to a label the source does not tie it to."""
    reference_labels = set(_LABEL_RE.findall(reference)) | set(_ZH_LABEL_RE.findall(reference))
    if len(reference_labels) != 1:
        return None
    answer_labels = set(_LABEL_RE.findall(answer)) | set(_ZH_LABEL_RE.findall(answer))
    if (
        len(answer_labels) == 1
        and not (answer_labels & reference_labels)
        and any(_term_in(term, answer) for term in affirmed_terms)
    ):
        wrong = next(iter(answer_labels))
        right = next(iter(reference_labels))
        return (
            f"The answer places the target on label {wrong}, but the source ties it "
            f"to label {right}; that is a misread figure, not an unassessable one."
        )
    return None


def _detect_contradiction(pending, normalized: str) -> str | None:
    """Deterministic, provable contradictions only; anything else defers."""
    visual = pending.visual_context
    reference_answer = str(visual.get("reference_answer") or pending.expected_answer or "")
    aliases = [str(alias) for alias in pending.accepted_answers]
    reference = " ".join([str(visual.get("reference_quote") or ""), reference_answer, *aliases])
    reference_sentences = _sentences(reference)
    answer_sentences = _sentences(normalized)
    affirmed = _affirmed_terms([reference_answer, *aliases])
    return (
        _relation_conflict(reference, normalized)
        or _negation_conflict(reference_sentences, answer_sentences, affirmed)
        or _label_conflict(reference, normalized, affirmed)
    )
