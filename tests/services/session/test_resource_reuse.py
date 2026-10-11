from deeptutor.services.session.turns.resource_reuse import apply_resource_reuse


def test_one_turn_choices_are_used_without_persisting():
    payload = {
        "knowledge_bases": ["book", "agent"],
        "persona": "tutor",
        "skills": ["math"],
        "mcp": ["search"],
    }
    preferences = dict(payload)
    apply_resource_reuse(
        preferences, {"persona": False, "skills": False, "mcp": False}, ["agent", "unselected"]
    )
    assert preferences == {"knowledge_bases": ["agent"], "persona": "", "skills": [], "mcp": []}
    assert payload["knowledge_bases"] == ["book", "agent"]
    assert payload["skills"] == ["math"]


def test_legacy_and_repeated_choices_stay_unchanged():
    for reuse in (None, {}, {"persona": True, "skills": True, "mcp": True}):
        preferences = {
            "knowledge_bases": ["book"],
            "persona": "tutor",
            "skills": ["math"],
            "mcp": ["search"],
        }
        expected = dict(preferences)
        apply_resource_reuse(preferences, reuse, None)
        assert preferences == expected


def test_repeat_application_is_idempotent():
    preferences = {
        "knowledge_bases": ["book", "agent"],
        "persona": "tutor",
        "skills": ["math"],
        "mcp": ["search"],
    }
    for _ in range(3):
        apply_resource_reuse(
            preferences, {"persona": False, "skills": False, "mcp": False}, ["agent"]
        )
    assert preferences == {
        "knowledge_bases": ["agent"],
        "persona": "",
        "skills": [],
        "mcp": [],
    }


def test_non_dict_reuse_leaves_preferences_untouched():
    preferences = {
        "knowledge_bases": ["book"],
        "persona": "tutor",
        "skills": ["math"],
        "mcp": ["search"],
    }
    for reuse in ([], "persona", 0, True):
        candidate = dict(preferences)
        apply_resource_reuse(candidate, reuse, ["book"])
        assert candidate == preferences


def test_non_string_persistent_kb_names_are_ignored():
    preferences = {"knowledge_bases": ["agent", "orphan", None, 7]}
    apply_resource_reuse(preferences, {"mcp": False}, ["agent", None, 7, b"kb"])
    assert preferences["knowledge_bases"] == ["agent"]


def test_missing_kb_key_is_materialized_as_empty_list():
    preferences = {"persona": "tutor"}
    apply_resource_reuse(preferences, {}, ["agent"])
    assert preferences["knowledge_bases"] == []
    assert preferences["persona"] == "tutor"


def test_absent_kinds_are_not_created():
    preferences = {"knowledge_bases": []}
    apply_resource_reuse(preferences, {"persona": False, "skills": False, "mcp": False}, None)
    assert preferences == {"knowledge_bases": []}


def test_falsy_but_not_false_reuse_values_do_not_release():
    preferences = {"persona": "tutor", "skills": ["math"], "mcp": ["search"]}
    apply_resource_reuse(preferences, {"persona": None, "skills": 0, "mcp": ""}, None)
    assert preferences == {"persona": "tutor", "skills": ["math"], "mcp": ["search"]}
