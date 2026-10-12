import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScopeEditorModal from "@/components/space/ScopeEditorModal";
import type { ImportAgent } from "@/lib/chat-import/agent-store";
import type { AgentScope, ImportSource, ScanResult, SessionRef } from "@/lib/chat-import";
import type { SessionSummary } from "@/lib/session-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "en" } }),
}));

function translate(key: string, params?: Record<string, unknown>) {
  if (!params) return key;
  return key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
    String(params[name] ?? ""),
  );
}

const fixture = vi.hoisted(() => ({
  scanDirectory: vi.fn(),
  parseSessions: vi.fn(),
  ensureReadPermission: vi.fn(),
  saveAgent: vi.fn(),
  importChatHistory: vi.fn(),
  deleteSession: vi.fn(),
}));

vi.mock("@/lib/chat-import", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/chat-import")>()),
  scanDirectory: (...args: unknown[]) => fixture.scanDirectory(...args),
  parseSessions: (...args: unknown[]) => fixture.parseSessions(...args),
}));

vi.mock("@/lib/chat-import/agent-store", async importOriginal => ({
  ...(await importOriginal<
    typeof import("@/lib/chat-import/agent-store")
  >()),
  ensureReadPermission: (...args: unknown[]) =>
    fixture.ensureReadPermission(...args),
  saveAgent: (...args: unknown[]) => fixture.saveAgent(...args),
}));

vi.mock("@/lib/session-api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  deleteSession: (...args: unknown[]) => fixture.deleteSession(...args),
}));

vi.mock("@/lib/imports-api", () => ({
  importChatHistory: (...args: unknown[]) => fixture.importChatHistory(...args),
}));

function ref(externalId: string, cwd: string, date: string): SessionRef {
  return {
    externalId,
    provisionalTitle: `${externalId} title`,
    cwd,
    date,
    lastModified: Date.parse("2026-01-02T10:00:00Z"),
    sizeBytes: 64,
    handle: {} as FileSystemFileHandle,
  };
}

const alphaRefs = [ref("s1", "/repo/a", "2026-01-02"), ref("s2", "/repo/a", "2026-01-03")];
const betaRefs = [ref("s3", "/repo/b", "2026-01-03")];

function projectScan(): ScanResult {
  return {
    source: "claude_code",
    handle: { name: "claude2" } as unknown as FileSystemDirectoryHandle,
    projects: [
      { cwd: "/repo/a", label: "Alpha", sessions: alphaRefs },
      { cwd: "/repo/b", label: "Beta", sessions: betaRefs },
    ],
  };
}

function codexScan(): ScanResult {
  return {
    source: "codex",
    handle: { name: "codex" } as unknown as FileSystemDirectoryHandle,
    projects: [
      { cwd: "/repo/a", label: "/repo/a", sessions: [ref("c1", "/repo/a", "2026-01-02")] },
      { cwd: "/repo/b", label: "/repo/b", sessions: [ref("c2", "/repo/b", "2026-01-03")] },
    ],
  };
}

function makeAgent(
  scope: AgentScope,
  source: ImportSource = "claude_code",
): ImportAgent {
  return {
    id: "agent-1",
    name: "Work agent",
    source,
    folderName: source,
    handle: { name: source } as unknown as FileSystemDirectoryHandle,
    scope,
    createdAt: 0,
    lastSyncAt: 0,
  };
}

function ownedSession(id: string, cwd: string, source: ImportSource = "claude_code") {
  return {
    id,
    session_id: id,
    title: id,
    created_at: Date.parse("2026-01-02T08:00:00Z") / 1000,
    updated_at: Date.parse("2026-01-02T08:00:00Z") / 1000,
    message_count: 1,
    last_message: "",
    preferences: { import: { source, source_cwd: cwd, agent_id: "agent-1" } },
  } as SessionSummary;
}

function renderModal(agent: ImportAgent, ownedSessions: SessionSummary[] = []) {
  return render(
    <ScopeEditorModal
      agent={agent}
      ownedSessions={ownedSessions}
      onClose={onClose}
      onSaved={onSaved}
    />,
  );
}

const onClose = vi.fn();
const onSaved = vi.fn();

async function renderReady(agent: ImportAgent, ownedSessions: SessionSummary[] = []) {
  fixture.ensureReadPermission.mockResolvedValue(true);
  fixture.scanDirectory.mockResolvedValue(projectScan());
  renderModal(agent, ownedSessions);
  await screen.findByText("Alpha");
  expect(screen.getByText("Beta")).toBeTruthy();
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Save scope" }) as HTMLButtonElement;
}

describe("ScopeEditorModal", () => {
  beforeEach(() => {
    onClose.mockClear();
    onSaved.mockClear();
    fixture.scanDirectory.mockReset();
    fixture.parseSessions.mockReset();
    fixture.ensureReadPermission.mockReset();
    fixture.saveAgent.mockReset();
    fixture.importChatHistory.mockReset();
    fixture.deleteSession.mockReset();
    fixture.saveAgent.mockResolvedValue(undefined);
    fixture.importChatHistory.mockResolvedValue(undefined);
    fixture.deleteSession.mockResolvedValue(undefined);
    fixture.parseSessions.mockImplementation(
      async (_source: ImportSource, refs: SessionRef[]) =>
        refs.map(r => ({ external_id: r.externalId, title: r.provisionalTitle, source_cwd: r.cwd, messages: [] })),
    );
  });

  it("keeps the save button disabled while the folder is being read", async () => {
    fixture.ensureReadPermission.mockReturnValue(new Promise(() => {}));
    renderModal(makeAgent({ kind: "all" }));
    expect(await screen.findByText("Reading your folder…")).toBeTruthy();
    expect(saveButton()).toBeDisabled();
    expect(screen.queryByText("Alpha")).toBeNull();
  });

  it("shows the error state when read permission is denied", async () => {
    fixture.ensureReadPermission.mockResolvedValue(false);
    renderModal(makeAgent({ kind: "all" }));
    expect(await screen.findByText("Couldn't read this folder")).toBeTruthy();
    expect(saveButton()).toBeDisabled();
    expect(fixture.scanDirectory).not.toHaveBeenCalled();
  });

  it("shows the error state when the folder scan fails", async () => {
    fixture.ensureReadPermission.mockResolvedValue(true);
    fixture.scanDirectory.mockRejectedValue(new Error("unreadable"));
    renderModal(makeAgent({ kind: "all" }));
    expect(await screen.findByText("Couldn't read this folder")).toBeTruthy();
    expect(saveButton()).toBeDisabled();
  });

  it("backfills the initial selection from the saved project scope", async () => {
    await renderReady(makeAgent({ kind: "projects", cwds: ["/repo/a"] }));
    expect(screen.getByText("2 projects · 3 conversations")).toBeTruthy();
    const alphaCard = screen.getByText("Alpha").closest(".overflow-hidden") as HTMLElement;
    const betaCard = screen.getByText("Beta").closest(".overflow-hidden") as HTMLElement;
    expect(within(alphaCard).getByRole("button", { name: "Select" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(betaCard).getByRole("button", { name: "Select" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("preselects every group for a legacy unrestricted scope", async () => {
    await renderReady(makeAgent({ kind: "all" }));
    const alphaCard = screen.getByText("Alpha").closest(".overflow-hidden") as HTMLElement;
    const betaCard = screen.getByText("Beta").closest(".overflow-hidden") as HTMLElement;
    expect(within(alphaCard).getByRole("button", { name: "Select" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(betaCard).getByRole("button", { name: "Select" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("saves the edited project scope, re-importing only the remaining unit's sessions", async () => {
    await renderReady(makeAgent({ kind: "projects", cwds: ["/repo/a", "/repo/b"] }));
    fireEvent.click(
      within(screen.getByText("Beta").closest(".overflow-hidden") as HTMLElement).getByRole(
        "button",
        { name: "Select" },
      ),
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(fixture.parseSessions).toHaveBeenCalledWith("claude_code", alphaRefs);
    expect(fixture.importChatHistory).toHaveBeenCalledTimes(1);
    const [source, normalized, agentRef] = fixture.importChatHistory.mock.calls[0];
    expect(source).toBe("claude_code");
    expect(normalized.map((s: { external_id: string }) => s.external_id)).toEqual(["s1", "s2"]);
    expect(agentRef).toEqual({ id: "agent-1", name: "Work agent" });
    expect(fixture.saveAgent).toHaveBeenCalledTimes(1);
    const savedAgent = fixture.saveAgent.mock.calls[0][0] as ImportAgent;
    expect(savedAgent.scope).toEqual({ kind: "projects", cwds: ["/repo/a"] });
    expect(savedAgent.lastSyncAt).toBeGreaterThan(0);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("saves a day-based scope for a codex source without changes", async () => {
    fixture.ensureReadPermission.mockResolvedValue(true);
    fixture.scanDirectory.mockResolvedValue(codexScan());
    renderModal(makeAgent({ kind: "dates", days: ["2026-01-02"] }, "codex"));
    await screen.findByText("2 days · 2 conversations");
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const savedAgent = fixture.saveAgent.mock.calls[0][0] as ImportAgent;
    expect(savedAgent.scope).toEqual({ kind: "dates", days: ["2026-01-02"] });
  });

  it("asks before deleting out-of-scope conversations and keeps them when cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderReady(makeAgent({ kind: "projects", cwds: ["/repo/a", "/repo/b"] }), [
      ownedSession("own-b", "/repo/b"),
      ownedSession("own-c", "/repo/c"),
    ]);
    fireEvent.click(
      within(screen.getByText("Beta").closest(".overflow-hidden") as HTMLElement).getByRole(
        "button",
        { name: "Select" },
      ),
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toContain("2 conversations are no longer in scope");
    expect(fixture.deleteSession).not.toHaveBeenCalled();
    const savedAgent = fixture.saveAgent.mock.calls[0][0] as ImportAgent;
    expect(savedAgent.scope).toEqual({ kind: "projects", cwds: ["/repo/a"] });
  });

  it("deletes confirmed out-of-scope conversations before persisting the scope", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderReady(makeAgent({ kind: "projects", cwds: ["/repo/a", "/repo/b"] }), [
      ownedSession("own-b", "/repo/b"),
      ownedSession("own-c", "/repo/c"),
    ]);
    fireEvent.click(
      within(screen.getByText("Beta").closest(".overflow-hidden") as HTMLElement).getByRole(
        "button",
        { name: "Select" },
      ),
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(fixture.saveAgent).toHaveBeenCalledTimes(1));
    expect(
      fixture.deleteSession.mock.calls.map(([id]) => id).sort(),
    ).toEqual(["own-b", "own-c"]);
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("shows the error state, keeps the dialog open, and skips saving when the import fails", async () => {
    fixture.importChatHistory.mockRejectedValue(new Error("offline"));
    await renderReady(makeAgent({ kind: "all" }));
    fireEvent.click(saveButton());
    expect(await screen.findByText("Saving…")).toBeTruthy();
    expect(await screen.findByText("Couldn't read this folder")).toBeTruthy();
    expect(saveButton()).toBeDisabled();
    expect(fixture.saveAgent).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cancel closes the modal without persisting anything", async () => {
    await renderReady(makeAgent({ kind: "all" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(fixture.saveAgent).not.toHaveBeenCalled();
    expect(fixture.importChatHistory).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
