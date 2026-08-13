# Reading time sync between DeepTutor web and Apple Books

**Status:** Rejected (revisit if Apple opens a write API)
**Date:** 2026-08-12

## Goal

Accumulate DeepTutor web reading minutes *into* Apple Books' "Today's reading
time" / reading goal, so a single Apple-side counter reflects all reading.

## Conclusion

**Not feasible. Apple exposes no API to write reading time into Apple Books.**

- Sign in with Apple / Apple ID login grants identity (name, email, sub) only —
  no Apple Books data scope is attached.
- Apple Books reading time lives in a private sandbox SQLite and is synced via
  a per-app CloudKit container that third parties cannot read or write.
- Editing the private DB directly (e.g. `ZBCASSETREADINGSESSION`) is a brittle
  hack: schema changes per OS release, no integrity guarantees, and the web
  sandbox cannot touch local files anyway.
- A read-only aggregation panel (pull Apple Books sessions out, show them in
  DeepTutor) was considered but rejected: it is a one-way compromise that does
  not satisfy the original "sync back into Apple Books" goal.

## Mature industry practice

There is no universal "reading-time hub." Platforms record time in isolated
silos (Apple Books, Kindle, WeRead each keep their own). The common pattern is:

1. **Self-record first.** Track reading time in the app you control and store
   it locally — this is the prerequisite for any export.
2. **Aggregate to an open, self-owned destination** for cross-device views:
   calendar (Google Calendar / iCloud), Notion / Feishu Base, Google Sheets, or
   time trackers (Toggl). Readwise popularized this aggregation model.
3. **Wait for an open API before chasing a closed target.** Apple Books has
   been closed for over a decade with no signal of opening; do not bet on it.

## Revisit trigger

If Apple ever ships a public reading-time write API (Books, HealthKit, or a
Shortcuts action that sets minutes), reopen this decision. Until then, keep
DeepTutor's own recording self-contained and exportable to open platforms.
