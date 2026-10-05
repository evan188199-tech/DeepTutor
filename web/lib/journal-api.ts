import { apiFetch, apiUrl } from "@/lib/api";

// ── Learning journal (read-only overview, /space/journal) ──
//
// The journal is the tutor's cross-session state (mission / last-session
// handoff / confirmed records), written only from conversation via the
// learning_update tool and stored per workspace under learning_journal/.
// These types mirror the backend response of GET /api/learning-journal.

export interface LearningJournalMission {
  topic: string;
  why: string;
  level: string;
  updated_at: string;
}

export interface LearningJournalSession {
  summary: string;
  next_focus: string;
  updated_at: string;
}

export interface LearningJournalRecord {
  id: string;
  title: string;
  insight: string;
  created_at: string;
}

export interface LearningJournalSnapshot {
  version: number;
  updated_at: string;
  mission: LearningJournalMission;
  last_session: LearningJournalSession;
  records: LearningJournalRecord[];
  is_empty: boolean;
}

export async function fetchLearningJournal(): Promise<LearningJournalSnapshot> {
  const response = await apiFetch(apiUrl("/api/learning-journal"), {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return (await response.json()) as LearningJournalSnapshot;
}
