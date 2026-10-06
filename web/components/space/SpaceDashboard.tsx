"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useCapabilityFilter } from "@/features/capabilities/useCapabilityCatalog";
import {
  ArrowUpRight,
  BookOpen,
  Brain,
  ClipboardList,
  Ear,
  Github,
  History,
  NotebookPen,
  Plug,
  Terminal,
  UserRound,
  Wand2,
  type LucideIcon,
} from "lucide-react";

import { SPACE_MCP_SURFACE, loadMcpSurface } from "@/components/mcp/surface";
import { getCliApps } from "@/lib/cli-apps-api";
import { listSessions } from "@/lib/session-api";
import { listNotebooks, listNotebookEntries } from "@/lib/notebook-api";
import { listPersonas } from "@/lib/personas-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { listSkills } from "@/lib/skills-api";

/**
 * Learning Space dashboard — the hub of `/space`.
 *
 * Replaces the old "land directly in a section behind a side list" flow with a
 * single overview the learner enters from. Each tile is a real entry point that
 * shows a live count so the space feels inhabited, then routes into the full
 * section page (which keeps the mini-nav for lateral movement).
 */

type DashKey =
  | "knowledge"
  | "memory"
  | "chat_history"
  | "notebooks"
  | "question_bank"
  | "personas"
  | "skills"
  | "mcp"
  | "cli_apps"
  | "whisper";

interface DashboardItem {
  key: DashKey;
  href: string;
  icon: LucideIcon;
  title: string;
  blurb: string;
  /**
   * Unit shown after the live count, e.g. "168 conversations". Omitted
   * together with ``load`` for a tile that has nothing to count.
   */
  /** Locale key for the unit shown after the live count. */
  unit?: string;
  /** Icon-tile accent — full class strings so Tailwind keeps them. */
  tile: string;
  /**
   * Live count for the tile. Optional: a surface with no countable rows (an
   * ephemeral room, say) renders as title + blurb instead of showing a
   * permanently-loading number.
   */
  load?: () => Promise<number>;
  /** GitHub handle of the contributor this surface came from. */
  credit?: string;
  /**
   * Turn capability this surface needs, when it is not served by this
   * repository. The tile is withheld unless the backend registry actually
   * holds the name, so a stock install never offers a room whose capability
   * was never installed (#963).
   */
  requiresCapability?: string;
}

interface DashboardGroup {
  /** Locale key for the group heading. */
  label: string;
  items: DashboardItem[];
}

const GROUPS: DashboardGroup[] = [
  {
    label: "Conversations & Materials",
    items: [
      {
        key: "chat_history",
        href: "/space/chat-history",
        icon: History,
        title: "Chat History",
        blurb: "Review and reopen previous conversations.",
        unit: "conversations",
        tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
        load: async () => (await listSessions(200, 0, { force: true })).length,
      },
      {
        key: "notebooks",
        href: "/notebooks",
        icon: NotebookPen,
        title: "Notebooks",
        blurb: "Organize saved outputs from chat, research, Co-Writer, and more.",
        unit: "notebooks",
        tile: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
        load: async () => (await listNotebooks()).length,
      },
      {
        key: "question_bank",
        href: "/space/questions",
        icon: ClipboardList,
        title: "Question Bank",
        blurb: "Review and organize quiz questions across sessions.",
        unit: "questions",
        tile: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
        load: async () => (await listNotebookEntries({ limit: 1 })).total,
      },
      {
        key: "knowledge",
        href: "/knowledge-bases",
        icon: BookOpen,
        title: "Knowledge Center",
        blurb: "Manage knowledge bases and retrieval engines.",
        unit: "knowledge bases",
        tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
        load: async () => (await listKnowledgeBases({ library: true })).length,
      },
    ],
  },
  {
    label: "Personalization",
    items: [
      {
        key: "personas",
        href: "/space/personas",
        icon: UserRound,
        title: "Personas",
        blurb: "Behavior presets you can apply per chat turn.",
        unit: "personas",
        tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
        load: async () => (await listPersonas()).length,
      },
      {
        key: "skills",
        href: "/space/skills",
        icon: Wand2,
        title: "Skills",
        blurb: "Capability playbooks the model reads on demand.",
        unit: "skills",
        tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
        load: async () => (await listSkills()).length,
      },
      {
        key: "mcp",
        href: "/space/mcp",
        icon: Plug,
        title: "MCP Services",
        blurb: "Connect hosted MCP services and bring their tools into chat.",
        unit: "services",
        tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
        // The account's own servers only: the deployment's are shown on the page
        // but are not this reader's to count.
        load: async () =>
          Object.keys((await loadMcpSurface(SPACE_MCP_SURFACE)).servers).length,
      },
      {
        key: "cli_apps",
        href: "/space/cli-apps",
        icon: Terminal,
        title: "CLI Apps",
        blurb: "Command-line tools from the CLI-Anything catalog, callable from chat.",
        unit: "apps",
        tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
        // What this reader can actually use, not what the deployment installed:
        // an app they were not granted is visible on the page but is not theirs.
        load: async () =>
          (await getCliApps()).apps.filter(app => app.granted && app.enabled)
            .length,
      },
      {
        key: "memory",
        href: "/memory",
        icon: Brain,
        title: "Memory",
        blurb: "Review what your tutor remembers about you.",
        tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
      },
    ],
  },
  {
    label: "More Projects",
    items: [
      {
        key: "whisper",
        href: "/whisper",
        icon: Ear,
        title: "Whisper",
        blurb: "Dual-seat practice room — the supervisor whispers to the trainee only.",
        tile: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400",
        credit: "alanguan73",
        // Served by the out-of-tree psych-academy plugin, not by this repo.
        requiresCapability: "whisper_visitor",
      },
    ],
  },
];

const ALL_ITEMS = GROUPS.flatMap(g => g.items);

/**
 * The groups to render, given what the backend can actually serve.
 *
 * `isAvailable` is null while the probe is in flight: gated tiles stay hidden
 * until then, so a surface whose capability was never installed does not flash
 * into view and out again — an ungated tile is never affected. A group left
 * with no tiles is dropped along with its heading, or "More Projects" would
 * render as a title over nothing (#963).
 */
export function visibleGroups(
  groups: DashboardGroup[],
  isAvailable: ((name: string) => boolean) | null
): DashboardGroup[] {
  return groups
    .map(group => ({
      ...group,
      items: group.items.filter(
        item =>
          !item.requiresCapability ||
          (isAvailable?.(item.requiresCapability) ?? false)
      ),
    }))
    .filter(group => group.items.length > 0);
}

export { GROUPS as DASHBOARD_GROUPS };

export default function SpaceDashboard() {
  const { t } = useTranslation();

  const [counts, setCounts] = useState<Partial<Record<DashKey, number>>>({});

  const capabilityAvailable = useCapabilityFilter();
  const groups = useMemo(
    () => visibleGroups(GROUPS, capabilityAvailable),
    [capabilityAvailable]
  );

  useEffect(() => {
    let cancelled = false;
    // Each tile loads independently so one slow/failed endpoint never blanks
    // the whole dashboard.
    for (const item of ALL_ITEMS) {
      if (!item.load) continue;
      item
        .load()
        .then(n => {
          if (!cancelled) setCounts(prev => ({ ...prev, [item.key]: n }));
        })
        .catch(() => {
          /* leave undefined → tile just omits the count */
        });
    }
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <header className="mb-8">
        <h1 className="font-serif text-[24px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
          {t("Learning Space")}
        </h1>
        <p className="mt-1.5 max-w-xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t("Your conversations, agents, notebooks, and questions in one place — enter from here.")}
        </p>
      </header>

      <div className="space-y-9">
        {groups.map(group => (
          <section key={group.label}>
            <h2 className="mb-3 px-0.5 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
              {t(group.label)}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {group.items.map(item => (
                <DashboardCard
                  key={item.key}
                  item={item}
                  count={counts[item.key]}
                  t={t}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function DashboardCard({
  item,
  count,
  t,
}: {
  item: DashboardItem;
  count: number | undefined;
  t: (key: string) => string;
}) {
  const Icon = item.icon;
  const loaded = count !== undefined;
  const formatted = useMemo(
    () => (loaded ? count.toLocaleString() : ""),
    [loaded, count]
  );

  return (
    <Link
      href={item.href}
      className="group relative flex flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${item.tile}`}
        >
          <Icon size={18} strokeWidth={1.7} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14.5px] font-medium leading-tight tracking-tight text-[var(--foreground)]">
            {t(item.title)}
          </h3>
          {item.unit ? (
            <div className="mt-1 flex items-baseline gap-1.5">
              {loaded ? (
                <>
                  <span className="text-[20px] font-semibold leading-none tabular-nums text-[var(--foreground)]">
                    {formatted}
                  </span>
                  <span className="text-[12px] text-[var(--muted-foreground)]">
                    {t(item.unit)}
                  </span>
                </>
              ) : (
                <span className="my-[3px] h-3.5 w-12 animate-pulse rounded bg-[var(--muted)]" />
              )}
            </div>
          ) : null}
        </div>
        <ArrowUpRight
          size={16}
          className="shrink-0 text-[var(--muted-foreground)]/40 transition-colors group-hover:text-[var(--foreground)]"
        />
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {t(item.blurb)}
      </p>
      {item.credit ? (
        <span className="mt-2.5 inline-flex items-center gap-1 self-start text-[11px] leading-none text-[var(--muted-foreground)] opacity-60">
          <Github size={11} strokeWidth={1.8} aria-hidden />
          {item.credit}
        </span>
      ) : null}
    </Link>
  );
}
