# PR: fix(mastery): keep quiz prompts from citing option letters

## Summary

- PR #1692 shuffles the options of every choice question before the learner sees the card, so the label the model assigns at send time (`A`/`B`/`C`…) is not the label the learner answers by. Any wording in `question` or `explanation` that names an option letter can contradict the rendered card.
- This PR adds one sentence to the en/zh `mastery_loop.yaml` prompts: the option order you send is shuffled before the learner sees the card, so never reference an option letter in `question` or `explanation` — reason about the answer's content, not its position.
- Prompt-only change (+2/−2 across two yaml files). No Python code, no grading or registration behavior touched.

## Root cause

Not a code bug — a prompt/UX consistency gap opened by the shuffle in #1692: the model composes `question`/`explanation` using the labels it assigned, but the card re-renders options in a fresh order, so "the correct answer is A" is wrong on the learner's card whenever the shuffle moves the correct body to another label.

## Changes

- `deeptutor/capabilities/mastery/prompts/en/mastery_loop.yaml` (+1/−1): extends the memory/procedure bullet with the shuffle notice and the never-cite-a-letter rule.
- `deeptutor/capabilities/mastery/prompts/zh/mastery_loop.yaml` (+1/−1): same rule in Chinese, same 2-space indent preserved.

Scope note: this PR originally also carried an order-independence fix for the flaky `test_repair_question_tool_voids_wrong_key_from_question_bank` (intermittent `Python Tests (Python 3.12)` red on #1692). That fix has already landed inside #1692 as commit `cb0037626`, so it is deliberately dropped here to avoid duplicating/conflicting with the same hunk.

## Tests

All run on this branch, based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `/Users/Shared/DeepTutor/.venv/bin/pytest deeptutor/learning/tests -q` → **610 passed** × 3 rounds (4.50s / 3.67s / 3.42s)
- `/Users/Shared/DeepTutor/.venv/bin/pytest tests/capabilities -q -k mastery` → **84 passed, 304 deselected** (the 5 choice-shuffle tests live on #1692's branch, not on `dev`)
- Prompt packs load through the real `PromptManager` (`module_name=mastery`, `agent_name=mastery_loop`) for en and zh, with the new rule present in the loaded text
- `ruff check .` → All checks passed; `ruff format --check .` → 1920 files already formatted
- `python3 scripts/check_architecture.py` → Architecture boundaries: OK; `python3 scripts/check_repo_hygiene.py` → passed

Known unrelated CI blocker (affects every open PR right now, including #1692's latest run): `tests/services/test_codebuddy_credentials.py::test_load_credentials_parses_session` asserts a session with hardcoded `expiresAt = 1791055241000` (2026-10-03 ~15:40 UTC) is not expired. It passed CI at 10:34 UTC on Oct 3, failed everywhere after the timestamp passed, and fails locally on a clean `dev` checkout — a time-bomb fixture, not a regression of this PR.

## Related issue

Related to #1692 (option shuffle, for #1691). Most meaningful once #1692 lands; merging this first would have the prompt describe a shuffle `dev` does not perform yet.
