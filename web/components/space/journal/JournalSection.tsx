"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Inbox,
  ListChecks,
  Loader2,
  MessageSquareText,
  RotateCcw,
  ScrollText,
  Target,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  fetchLearningJournal,
  type LearningJournalSnapshot,
} from "@/lib/journal-api";

/**
 * Learning Space → Learning Journal (#1407).
 *
 * A read-only mirror of the journal the tutor carries across sessions:
 * mission, last-session handoff, and the confirmed records (newest first).
 * Editing stays in conversation via the tutor's learning_update tool — the
 * panel reflects what the next turn would actually be injected with, so it
 * must never become a second editing path.
 */

function formatStamp(iso: string, language: string): string {
  if (!iso) return "";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  try {
    return new Intl.DateTimeFormat(language || "en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(parsed);
  } catch {
    return "";
  }
}

function Field({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </dt>
      <dd className="text-[13.5px] leading-relaxed text-[var(--foreground)]">
        {value}
      </dd>
    </div>
  );
}

function CardShell({
  icon: Icon,
  title,
  meta,
  children,
}: {
  icon: typeof Target;
  title: string;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--muted)] text-[var(--muted-foreground)]">
          <Icon size={14} strokeWidth={1.8} />
        </span>
        <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
          {title}
        </h2>
        {meta && (
          <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
            {meta}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

export default function JournalSection() {
  const { t, i18n } = useTranslation();
  const [snapshot, setSnapshot] = useState<LearningJournalSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setSnapshot(await fetchLearningJournal());
    } catch {
      setError("load-failed");
      setSnapshot(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchLearningJournal()
      .then(data => {
        if (!cancelled) setSnapshot(data);
      })
      .catch(() => {
        if (!cancelled) setError("load-failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="space-y-3">
        <SpaceSectionHeader
          icon={ScrollText}
          title={t("Learning Journal")}
          description={t(
            "See the mission and last-session handoff your tutor carries across sessions. Read-only — update it by talking to the tutor.",
          )}
        />
        <div className="flex min-h-[300px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)] text-center">
          <AlertTriangle size={18} className="text-[var(--muted-foreground)]" />
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("Couldn't load the journal.")}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/30"
          >
            <RotateCcw size={13} strokeWidth={1.8} />
            {t("Retry")}
          </button>
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Loader2 size={20} className="animate-spin text-[var(--muted-foreground)]" />
        <span className="sr-only">{t("Loading…")}</span>
      </div>
    );
  }

  if (snapshot.is_empty) {
    return (
      <div className="space-y-3">
        <SpaceSectionHeader
          icon={ScrollText}
          title={t("Learning Journal")}
          description={t(
            "See the mission and last-session handoff your tutor carries across sessions. Read-only — update it by talking to the tutor.",
          )}
        />
        <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
            <Inbox size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No mission yet")}
          </p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
            {t(
              "Your tutor has no mission for you yet — ask it to set one in a chat.",
            )}
          </p>
        </div>
      </div>
    );
  }

  const { mission, last_session: lastSession } = snapshot;
  const recordsNewestFirst = [...snapshot.records].reverse();
  const missionStamp = formatStamp(mission.updated_at, i18n.language);
  const sessionStamp = formatStamp(lastSession.updated_at, i18n.language);

  return (
    <div className="space-y-3">
      <SpaceSectionHeader
        icon={ScrollText}
        title={t("Learning Journal")}
        description={t(
          "See the mission and last-session handoff your tutor carries across sessions. Read-only — update it by talking to the tutor.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {t("Read-only")}
          </span>
        }
      />

      <CardShell icon={Target} title={t("Mission")} meta={missionStamp}>
        <dl className="grid gap-3 sm:grid-cols-2">
          {mission.topic && <Field label={t("Topic")} value={mission.topic} />}
          {mission.level && <Field label={t("Level")} value={mission.level} />}
          {mission.why && <Field label={t("Why")} value={mission.why} />}
        </dl>
      </CardShell>

      <CardShell
        icon={MessageSquareText}
        title={t("Last session")}
        meta={sessionStamp}
      >
        <dl className="grid gap-3 sm:grid-cols-2">
          {lastSession.summary && (
            <Field label={t("Summary")} value={lastSession.summary} />
          )}
          {lastSession.next_focus && (
            <Field label={t("Next focus")} value={lastSession.next_focus} />
          )}
        </dl>
      </CardShell>

      <CardShell icon={ListChecks} title={t("Confirmed records")}>
        {recordsNewestFirst.length === 0 ? (
          <p className="text-[13px] text-[var(--muted-foreground)]">
            {t("No confirmed records yet.")}
          </p>
        ) : (
          <ol className="space-y-2.5">
            {recordsNewestFirst.map(record => (
              <li
                key={record.id}
                className="rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/40 px-3 py-2.5"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[13px] font-medium text-[var(--foreground)]">
                    {record.title || record.insight}
                  </p>
                  <time
                    dateTime={record.created_at || undefined}
                    className="shrink-0 text-[11px] text-[var(--muted-foreground)]"
                  >
                    {formatStamp(record.created_at, i18n.language)}
                  </time>
                </div>
                {record.title && record.insight && (
                  <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                    {record.insight}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </CardShell>
    </div>
  );
}
