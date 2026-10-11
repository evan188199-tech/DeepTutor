import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LearningJournalPanel from "@/components/space/LearningJournalPanel";
import SpaceDashboard, { DASHBOARD_GROUPS } from "@/components/space/SpaceDashboard";
import { getLearningJournal, type LearningJournal } from "@/lib/learning-journal-api";
import { apiFetch } from "@/shared/api/client";
import { useCapabilityFilter } from "@/features/capabilities/useCapabilityCatalog";
import { SPACE_MCP_SURFACE, loadMcpSurface } from "@/components/mcp/surface";
import { getCliApps } from "@/lib/cli-apps-api";
import { listSessions } from "@/lib/session-api";
import { listNotebooks, listNotebookEntries } from "@/lib/notebook-api";
import { listPersonas } from "@/lib/personas-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { listSkills } from "@/lib/skills-api";

const route = vi.hoisted(() => ({ workspace: "a" }));
const locale = vi.hoisted(() => ({ wrap: false, language: "en" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams({ dt_workspace: route.workspace }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (locale.wrap ? `⟦${key}⟧` : key),
    i18n: { language: locale.language },
  }),
}));
vi.mock("@/lib/learning-journal-api", () => ({ getLearningJournal: vi.fn() }));
vi.mock("@/shared/api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/features/capabilities/useCapabilityCatalog", () => ({ useCapabilityFilter: vi.fn() }));
vi.mock("@/components/mcp/surface", () => ({ SPACE_MCP_SURFACE: "space", loadMcpSurface: vi.fn() }));
vi.mock("@/lib/cli-apps-api", () => ({ getCliApps: vi.fn() }));
vi.mock("@/lib/session-api", () => ({ listSessions: vi.fn() }));
vi.mock("@/lib/notebook-api", () => ({ listNotebooks: vi.fn(), listNotebookEntries: vi.fn() }));
vi.mock("@/lib/personas-api", () => ({ listPersonas: vi.fn() }));
vi.mock("@/features/knowledge/api/catalog", () => ({ listKnowledgeBases: vi.fn() }));
vi.mock("@/lib/skills-api", () => ({ listSkills: vi.fn() }));

const { getLearningJournal: realGetLearningJournal } =
  await vi.importActual<typeof import("@/lib/learning-journal-api")>("@/lib/learning-journal-api");
const empty: LearningJournal = {
  version: 1, updated_at: "", injected_context: "",
  mission: { topic: "", why: "", level: "", updated_at: "" },
  last_session: { summary: "", next_focus: "", updated_at: "" }, records: [],
};

function aJournal(patch: Partial<Omit<LearningJournal, "mission" | "last_session">> & {
  mission?: Partial<LearningJournal["mission"]>;
  last_session?: Partial<LearningJournal["last_session"]>;
}): LearningJournal {
  return {
    ...empty,
    ...patch,
    mission: { ...empty.mission, ...patch.mission },
    last_session: { ...empty.last_session, ...patch.last_session },
    records: patch.records ?? [],
  };
}

function asResult<T>(value: unknown): T {
  return value as T;
}

beforeEach(() => { vi.clearAllMocks(); route.workspace = "a"; });
beforeEach(() => {
  locale.wrap = false;
  locale.language = "en";
  window.history.replaceState(null, "", "/");
});
describe("Learning journal overview", () => {
  it("shows the mission, handoff and newest-first records without editing controls", async () => {
    vi.mocked(getLearningJournal).mockResolvedValue({ ...empty,
      mission: { ...empty.mission, topic: "Signals", why: "Exam", level: "Beginner" },
      last_session: { ...empty.last_session, summary: "Sampling", next_focus: "Aliasing" },
      records: [{ id: "new", title: "Newer", insight: "Second", created_at: "" }, { id: "old", title: "Older", insight: "First", created_at: "" }],
    });
    render(<LearningJournalPanel />);
    await screen.findByText("Signals");
    expect(screen.getByText("Sampling")).toBeInTheDocument();
    expect(screen.getByText("Aliasing")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((el) => el.textContent)).toEqual(["NewerSecond", "OlderFirst"]);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
  it("explains an empty journal and retries failed reads", async () => {
    vi.mocked(getLearningJournal).mockRejectedValueOnce(new Error("409")).mockResolvedValue(empty);
    render(<LearningJournalPanel />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Your tutor has no mission for you yet. Ask it to set one in conversation.");
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("does not display an old workspace response after switching", async () => {
    let resolve!: (journal: LearningJournal) => void;
    vi.mocked(getLearningJournal).mockImplementationOnce(() => new Promise((done) => { resolve = done; })).mockResolvedValue(empty);
    const view = render(<LearningJournalPanel />);
    route.workspace = "b";
    view.rerender(<LearningJournalPanel />);
    await screen.findByText("No session handoff yet.");
    resolve({ ...empty, mission: { ...empty.mission, topic: "Old workspace secret" } });
    await waitFor(() => expect(screen.queryByText("Old workspace secret")).toBeNull());
  });
});

describe("Learning journal loading and failure branches", () => {
  it("shows a loading status until the journal resolves and aborts the in-flight read on unmount", () => {
    const seen: AbortSignal[] = [];
    vi.mocked(getLearningJournal).mockImplementationOnce((signal?: AbortSignal) => {
      seen.push(signal as AbortSignal);
      return new Promise<LearningJournal>(() => {});
    });
    const view = render(<LearningJournalPanel />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading...");
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(vi.mocked(getLearningJournal)).toHaveBeenCalledWith(expect.any(AbortSignal));
    view.unmount();
    expect(seen[0]?.aborted).toBe(true);
  });
  it("issues a fresh read when refresh is clicked while the first read is still loading", async () => {
    vi.mocked(getLearningJournal)
      .mockImplementationOnce(() => new Promise<LearningJournal>(() => {}))
      .mockResolvedValueOnce(aJournal({ mission: { topic: "Signals" } }));
    render(<LearningJournalPanel />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Signals");
    expect(screen.queryByRole("status")).toBeNull();
    expect(vi.mocked(getLearningJournal)).toHaveBeenCalledTimes(2);
  });
  it("replaces displayed journal content with the failure alert and restores content after a successful refresh", async () => {
    vi.mocked(getLearningJournal)
      .mockResolvedValueOnce(aJournal({ mission: { topic: "Signals" }, records: [{ id: "r1", title: "Nyquist", insight: "Twice", created_at: "" }] }))
      .mockRejectedValueOnce(new Error("Learning journal request failed: 500"))
      .mockResolvedValueOnce(aJournal({ mission: { topic: "Loop" } }));
    render(<LearningJournalPanel />);
    await screen.findByText("Signals");
    expect(screen.getByText("Nyquist")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not read the learning journal. Its original data is preserved. Try refreshing.");
    expect(screen.queryByText("Signals")).toBeNull();
    expect(screen.queryByText("Nyquist")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Loop");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(vi.mocked(getLearningJournal)).toHaveBeenCalledTimes(3);
  });
});

describe("Learning journal empty-state branches", () => {
  it("keeps handoff and records visible while the mission is empty", async () => {
    vi.mocked(getLearningJournal).mockResolvedValueOnce(aJournal({
      last_session: { summary: "Sampling", next_focus: "", updated_at: "" },
      records: [{ id: "r1", title: "Nyquist", insight: "Twice bandwidth", created_at: "" }],
    }));
    const { container } = render(<LearningJournalPanel />);
    await screen.findByText("Your tutor has no mission for you yet. Ask it to set one in conversation.");
    const mission = screen.getByRole("region", { name: "Current mission" });
    expect(within(mission).queryByText(/Level/)).toBeNull();
    expect(within(mission).queryByText("Sampling")).toBeNull();
    expect(screen.getByText("Sampling")).toBeInTheDocument();
    expect(screen.getByText("Nyquist")).toBeInTheDocument();
    expect(container.querySelector("time")).toBeNull();
  });
  it("announces the empty handoff and records placeholders next to a present mission", async () => {
    vi.mocked(getLearningJournal).mockResolvedValueOnce(aJournal({ mission: { topic: "Signals" } }));
    const { container } = render(<LearningJournalPanel />);
    await screen.findByText("Signals");
    expect(screen.getByText("No session handoff yet.")).toBeInTheDocument();
    expect(screen.getByText("No confirmed learning records yet.")).toBeInTheDocument();
    const handoff = screen.getByRole("region", { name: "Last-session handoff" });
    expect(within(handoff).queryByText(/Next focus/)).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(container.querySelector("time")).toBeNull();
  });
});

describe("Learning journal locale keys", () => {
  it("renders every static string as a translation key and leaves journal data untouched", async () => {
    locale.wrap = true;
    vi.mocked(getLearningJournal).mockResolvedValueOnce(aJournal({
      mission: { topic: "Signals", why: "Exam", level: "Beginner", updated_at: "2026-10-11T08:00:00Z" },
      last_session: { summary: "Sampling", next_focus: "Aliasing", updated_at: "2026-10-10T08:00:00Z" },
      records: [{ id: "r1", title: "Nyquist", insight: "Twice bandwidth", created_at: "2026-10-09T08:00:00Z" }],
    }));
    render(<LearningJournalPanel />);
    await screen.findByText("Signals");
    expect(screen.getByText("⟦Learning journal⟧")).toBeInTheDocument();
    expect(screen.getByText("⟦Your tutor's mission, handoff and confirmed learning records.⟧")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "⟦Refresh⟧" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "⟦Current mission⟧" })).toHaveTextContent("⟦Level⟧: Beginner");
    expect(screen.getByRole("region", { name: "⟦Last-session handoff⟧" })).toHaveTextContent("⟦Next focus⟧: Aliasing");
    expect(screen.getByRole("region", { name: "⟦Confirmed learning records⟧" })).toBeInTheDocument();
    expect(screen.queryByText("⟦Signals⟧")).toBeNull();
    expect(screen.queryByText("⟦Nyquist⟧")).toBeNull();
    expect(screen.getByText("2026-10-11T08:00:00Z")).toBeInTheDocument();
    expect(screen.getByText("2026-10-09T08:00:00Z")).toBeInTheDocument();
  });
  it("routes the loading status and the failure alert through translation keys", async () => {
    locale.wrap = true;
    vi.mocked(getLearningJournal).mockImplementationOnce(() => new Promise<LearningJournal>(() => {}));
    const view = render(<LearningJournalPanel />);
    expect(screen.getByRole("status")).toHaveTextContent("⟦Loading...⟧");
    view.unmount();
    vi.mocked(getLearningJournal).mockRejectedValueOnce(new Error("boom"));
    render(<LearningJournalPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("⟦Could not read the learning journal. Its original data is preserved. Try refreshing.⟧");
  });
});

describe("Learning journal dashboard entry", () => {
  it("links the journal tile to the workspace-scoped journal page while other tiles stay unscoped", async () => {
    vi.mocked(useCapabilityFilter).mockReturnValue(() => true);
    vi.mocked(listSessions).mockResolvedValue(asResult([1, 2, 3]));
    vi.mocked(listNotebooks).mockResolvedValue(asResult([1]));
    vi.mocked(listNotebookEntries).mockResolvedValue(asResult({ total: 7 }));
    vi.mocked(listKnowledgeBases).mockResolvedValue(asResult([1, 2, 3, 4]));
    vi.mocked(listPersonas).mockResolvedValue(asResult([1, 2]));
    vi.mocked(listSkills).mockResolvedValue(asResult([1]));
    vi.mocked(loadMcpSurface).mockResolvedValue(asResult({ servers: {} }));
    vi.mocked(getCliApps).mockResolvedValue(asResult({ apps: [{ granted: true, enabled: true }] }));
    window.history.replaceState(null, "", "/space?dt_workspace=a");
    const view = render(<SpaceDashboard />);
    await screen.findByText("3");
    const journalTile = screen.getByRole("link", { name: /Learning journal/ });
    expect(journalTile).toHaveAttribute("href", "/space/journal?dt_workspace=a");
    expect(screen.getByRole("link", { name: /Chat History/ })).toHaveAttribute("href", "/space/chat-history");
    expect(within(journalTile).queryByText(/conversations/)).toBeNull();
    expect(journalTile.querySelector("[class*='animate-pulse']")).toBeNull();
    expect(journalTile.textContent).not.toMatch(/\d/);
    expect(screen.getByText("7")).toBeInTheDocument();
    locale.language = "zh-CN";
    view.rerender(<SpaceDashboard />);
    expect(screen.getByRole("link", { name: /学习日志/ })).toHaveAttribute("href", "/space/journal?dt_workspace=a");
    const journalItem = DASHBOARD_GROUPS.flatMap((group) => group.items).find((item) => item.key === "journal");
    expect(journalItem?.href).toBe("/space/journal");
    expect(journalItem?.load).toBeUndefined();
  });
  it("keeps the journal entry when capabilities are unavailable or a count endpoint fails", async () => {
    vi.mocked(useCapabilityFilter).mockReturnValue(() => false);
    vi.mocked(listSessions).mockResolvedValue(asResult([1, 2, 3]));
    vi.mocked(listNotebooks).mockResolvedValue(asResult([1]));
    vi.mocked(listNotebookEntries).mockResolvedValue(asResult({ total: 7 }));
    vi.mocked(listKnowledgeBases).mockResolvedValue(asResult([1, 2, 3, 4]));
    vi.mocked(listPersonas).mockResolvedValue(asResult([1, 2]));
    vi.mocked(listSkills).mockRejectedValueOnce(new Error("503"));
    vi.mocked(loadMcpSurface).mockResolvedValue(asResult({ servers: {} }));
    vi.mocked(getCliApps).mockResolvedValue(asResult({ apps: [{ granted: true, enabled: true }] }));
    window.history.replaceState(null, "", "/space?dt_workspace=a");
    render(<SpaceDashboard />);
    await screen.findByText("3");
    expect(screen.getByRole("link", { name: /Learning journal/ })).toHaveAttribute("href", "/space/journal?dt_workspace=a");
    expect(screen.queryByRole("link", { name: /Whisper/ })).toBeNull();
    const skillsTile = screen.getByRole("link", { name: /Skills/ });
    expect(skillsTile.querySelector("[class*='animate-pulse']")).not.toBeNull();
    expect(skillsTile.textContent).not.toMatch(/\d/);
  });
});

describe("learning-journal api client", () => {
  it("sends a no-store scoped request and returns the parsed journal", async () => {
    const payload = aJournal({ mission: { topic: "Signals" } });
    const controller = new AbortController();
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(realGetLearningJournal(controller.signal)).resolves.toEqual(payload);
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/api/learning-journal", { cache: "no-store", signal: controller.signal });
  });
  it("maps a non-ok response to a descriptive error instead of parsing the body", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response("{}", { status: 503 }));
    await expect(realGetLearningJournal()).rejects.toThrow("Learning journal request failed: 503");
  });
});
