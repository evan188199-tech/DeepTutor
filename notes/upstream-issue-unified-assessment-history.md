# Upstream Issue Draft: Unified Assessment History

> File this against HKUDS/DeepTutor after refreshing gh auth.

## Title

[Feature Request]: Unify assessment history across quiz, mastery path, and immersive reading Focus-Check

## Body

### Do you need to file a feature request?

- [x] I have searched the existing feature requests and this feature request is not already filed.
- [x] I believe this is a legitimate feature request, not just a question or bug.

### Feature Request Description

#### Summary

DeepTutor currently has fragmented assessment-history persistence. Quiz answers, wrong-answer tracking, and comprehension checks each use different storage and UI surfaces. This proposal requests a **unified assessment history** so that every quiz or comprehension-check attempt flows into a single persistent store that learners can review cross-session.

#### Current State

Three separate systems exist today:

1. **Question Notebook** (`/api/v1/notebook/entries`) — the primary saved-questions store. Persists question text, options, user answer, correctness, bookmarks, categories, and AI judgment. Used by the regular QuizViewer.

2. **Wrong-Answer Note** (PR #292, merged into dev) — a dedicated `wrong_answers` SQLite table with resolved/unresolved workflow, cross-session listing, and a `/wrong-answers` page. This appears to no longer be present in the current `origin/dev` tree (possibly lost during a rebase).

3. **Immersive Reading Focus-Check** (fork-level feature, not yet upstream) — stores comprehension-check attempts in a JSON-based `focus_history` within `immersive_reading/progress.json`. Includes submitted summary/reflection, LLM score, pass/fail, feedback, strengths, and missing points — but is completely isolated from the Question Notebook and wrong-answer systems.

#### Problem

A learner who uses multiple assessment surfaces cannot review all their mistakes or track progress from one place:

- Immersive Reading Focus-Check results are siloed in per-document JSON files. No cross-book aggregation, no unified review page.
- The wrong-answer infrastructure from PR #292 appears to be missing from the current dev branch.
- The Question Notebook stores individual quiz entries but does not surface a wrong-answers-only view or provide resolved/unresolved tracking.

#### Proposed Direction

**Phase 1**: Restore the wrong-answer persistence layer (or fold it into the Question Notebook as a resolved field + filter). Ensure coverage for regular quiz and mastery path.

**Phase 2**: Add a `source` field to every assessment record (`deep_question`, `mastery_path`, `immersive_reading`) so the review UI can show provenance and filter by surface.

**Phase 3**: When Immersive Reading is contributed upstream, wire Focus-Check results into the same persistence layer with `source: immersive_reading`, document/section provenance, and the same bookmark/resolved/category semantics.

**Phase 4**: A single cross-surface review page with filters by source, document, resolved status, and score trends over time.

#### Use Case

A learner reads a technical book using Immersive Reading, takes the Focus-Check on the TOC page, scores 25/100. Later takes a regular quiz on the same topic and answers incorrectly. They should see both mistakes in one review page, with links back to the source material.

#### Additional Context

- PR #292 implemented the wrong-answer SQLite table, API, and UI. Merge commit `a3a20953` but files do not appear in current `origin/dev`.
- The Question Notebook already has `is_correct`, `user_answer`, `correct_answer`, `ai_judgment`, and bookmark/category support.

### Related Module

api, services, web, immersive_reading (when upstreamed)
