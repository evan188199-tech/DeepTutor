"""Built-in reference offline dictionary provider (#961 slice 1).

``BuiltinDictionaryProvider`` is the documented reference provider from the
#961 MVP: fully offline, no permissions, a tiny bundled English headword
table with Chinese translations. It doubles as the fixture for tests and as
the template third-party dictionary providers copy.
"""

from __future__ import annotations

from deeptutor.learning_resources.contracts import (
    Definition,
    Example,
    LearningResourceProvider,
    LookupRequest,
    LookupResult,
    Phonetic,
    ProviderManifest,
    ProviderType,
    SourceAttribution,
    Translation,
)

_ENTRIES: dict[str, dict[str, list[dict[str, str | None]]]] = {
    "knowledge": {
        "definitions": [
            {
                "text": "facts, information, and skills acquired through experience or education",
                "part_of_speech": "noun",
            }
        ],
        "phonetics": [{"value": "/ˈnɒlɪdʒ/", "notation": "IPA"}],
        "examples": [{"text": "Knowledge is power.", "translation": "知识就是力量。"}],
        "translations": [{"text": "知识", "language": "zh"}],
    },
    "learn": {
        "definitions": [
            {
                "text": "to gain knowledge or skill in something by studying or practicing",
                "part_of_speech": "verb",
            }
        ],
        "phonetics": [{"value": "/lɜːn/", "notation": "IPA"}],
        "examples": [
            {
                "text": "Students learn faster when they get quick feedback.",
                "translation": "学生得到快速反馈时学得更快。",
            }
        ],
        "translations": [{"text": "学习；学会", "language": "zh"}],
    },
    "tutor": {
        "definitions": [
            {
                "text": "a private teacher who gives lessons to one student or a small group",
                "part_of_speech": "noun",
            }
        ],
        "phonetics": [{"value": "/ˈtjuːtə(r)/", "notation": "IPA"}],
        "examples": [
            {
                "text": "Her tutor helps with math every week.",
                "translation": "她的导师每周辅导她数学。",
            }
        ],
        "translations": [{"text": "导师；家庭教师", "language": "zh"}],
    },
}


class BuiltinDictionaryProvider(LearningResourceProvider):
    """Offline reference dictionary; enabled explicitly, never touches network."""

    def __init__(self) -> None:
        self._manifest = ProviderManifest(
            name="builtin-dictionary",
            type=ProviderType.DICTIONARY,
            version="1.0.0",
            languages=["en", "zh"],
            offline=True,
            permissions=[],
            description=(
                "Reference offline English dictionary bundled with DeepTutor; "
                "documents the slice-1 dictionary provider contract."
            ),
        )

    @property
    def manifest(self) -> ProviderManifest:
        return self._manifest

    def lookup(self, request: LookupRequest) -> LookupResult:
        term = request.term.strip().lower()
        entry = _ENTRIES.get(term)
        if entry is None:
            return LookupResult(
                term=request.term,
                language="en",
                found=False,
                source=SourceAttribution(provider=self._manifest.name),
            )
        return LookupResult(
            term=request.term,
            language="en",
            definitions=[Definition(**item) for item in entry["definitions"]],
            phonetics=[Phonetic(**item) for item in entry["phonetics"]],
            examples=[Example(**item) for item in entry["examples"]],
            translations=[Translation(**item) for item in entry["translations"]],
            source=SourceAttribution(
                provider=self._manifest.name,
                entry=term,
                license="DeepTutor built-in reference data",
            ),
        )


__all__ = ["BuiltinDictionaryProvider"]
