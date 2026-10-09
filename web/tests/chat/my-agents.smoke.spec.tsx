import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { initI18n } from "@/i18n/init";
import { epochMsToISODate, SOURCE_LABEL } from "@/lib/chat-import";
import type { ImportAgent } from "@/lib/chat-import/agent-store";
import type { SessionSummary } from "@/lib/session-api";

initI18n("en");

/**
 * Smoke coverage for the My Agents space section and its chat reference
 * picker (web-test-gaps-20261007 zero list — neither file was imported by
 * any test before this spec).
 *
 * Both components mount the real grouping/attribution logic (readImportMeta,
 * assignSessionsToAgents, filterRefsByScope) and mock only the API boundary
 * (imports/session APIs, the IndexedDB agent registry) plus heavy leaf
 * surfaces (SessionList, ImportWizard, ScopeEditorModal, PickerShell), so a
 * regression in grouping, filtering, selection or confirm callbacks fails
 * here before it reaches a user.
 */

const fixtures = vi.hoisted(() => ({
  routerPush: vi.fn(),
  setActiveSessionId: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: fixtures.routerPush, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    activeSessionId: null,
    setActiveSessionId: fixtures.setActiveSessionId,
  }),
}));

vi.mock("@/lib/imports-api", () => ({
  listImportedSessions: vi.fn(async () => []),
  importChatHistory: vi.fn(async () => ({ imported: 0, skipped: 0, sessions: [] })),
}));

vi.mock("@/lib/session-api", () => ({
  deleteSession: vi.fn(async () => undefined),
  updateSessionTitle: vi.fn(async () => undefined),
  getSession: vi.fn(async () => ({ messages: [] })),
}));

vi.mock("@/lib/chat-import/agent-store", () => ({
  getAgents: vi.fn(async () => []),
  saveAgent: vi.fn(async () => undefined),
  deleteAgent: vi.fn(async () => undefined),
  ensureReadPermission: vi.fn(async () => true),
}));

vi.mock("@/lib/chat-import", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/chat-import")>();
  return {
    ...actual,
    scanDirectory: vi.fn(),
    parseSessions: vi.fn(),
  };
});

vi.mock("@/components/SessionList", () => ({
  default: (props: {
    sessions: SessionSummary[];
    onSelect: (sessionId: string) => void;
    onRename: (sessionId: string, title: string) => void;
    onDelete: (sessionId: string) => void;
  }) => (
    <div data-testid="session-list" data-count={props.sessions.length}>
      {props.sessions.map(session => {
        const id = session.session_id || session.id;
        return (
          <div key={id} data-testid={`session-row-${id}`}>
            <button type="button" onClick={() => props.onSelect(id)}>
              Open {session.title}
            </button>
            <button
              type="button"
              onClick={() => props.onRename(id, `Renamed ${session.title}`)}
            >
              Rename {session.title}
            </button>
            <button type="button" onClick={() => props.onDelete(id)}>
              Delete {session.title}
            </button>
          </div>
        );
      })}
    </div>
  ),
}));

vi.mock("@/components/space/ImportWizard", () => ({
  default: ({ onImported }: { onImported: () => void }) => (
    <div data-testid="import-wizard">
      <button type="button" onClick={onImported}>Finish import</button>
    </div>
  ),
}));

vi.mock("@/components/space/ScopeEditorModal", () => ({
  default: ({
    agent,
    ownedSessions,
  }: {
    agent: ImportAgent;
    ownedSessions: unknown[];
  }) => (
    <div
      data-testid="scope-editor"
      data-agent-id={agent.id}
      data-owned={ownedSessions.length}
    />
  ),
}));

vi.mock("@/components/common/PickerShell", () => ({
  default: ({
    open,
    children,
  }: {
    open: boolean;
    children: ReactNode;
  }) => (open ? <div role="dialog">{children}</div> : null),
}));

import MyAgentsSection from "@/components/space/MyAgentsSection";
import MyAgentsPicker from "@/components/chat/MyAgentsPicker";
import {
  deleteSession,
  getSession,
  updateSessionTitle,
} from "@/lib/session-api";
import { importChatHistory, listImportedSessions } from "@/lib/imports-api";
import {
  deleteAgent,
  ensureReadPermission,
  getAgents,
  saveAgent,
} from "@/lib/chat-import/agent-store";
import { parseSessions, scanDirectory } from "@/lib/chat-import";

const AGENT: ImportAgent = {
  id: "agent-1",
  name: "Refactor crew",
  source: "claude_code",
  folderName: ".claude",
  handle: {} as unknown as FileSystemDirectoryHandle,
  scope: { kind: "all" },
  createdAt: 1_000_000,
  lastSyncAt: 0,
};

const CODEX_DAY_MS = Date.UTC(2026, 8, 28, 3, 0, 0);
const codexDayKey = epochMsToISODate(CODEX_DAY_MS);

function sessionFixture(
  id: string,
  overrides: Partial<SessionSummary> & { import?: Record<string, unknown> },
): SessionSummary {
  const { import: importMeta, ...rest } = overrides;
  return {
    id,
    session_id: id,
    title: "",
    created_at: CODEX_DAY_MS / 1000,
    updated_at: CODEX_DAY_MS / 1000,
    message_count: 4,
    last_message: "",
    ...(importMeta
      ? {
          preferences: { import: importMeta } as unknown as SessionSummary["preferences"],
        }
      : {}),
    ...rest,
  };
}

function standardSessions(): SessionSummary[] {
  return [
    sessionFixture("cs-1", {
      title: "New conversation",
      last_message: "Photosynthesis converts light into sugar.",
      updated_at: CODEX_DAY_MS / 1000 - 1_800,
      import: { source: "claude_code", source_cwd: "/repo/web", agent_id: "agent-1" },
    }),
    sessionFixture("cs-2", {
      title: "Quantum tunneling",
      last_message: "Tunneling happens through barriers.",
      updated_at: CODEX_DAY_MS / 1000 - 3_600,
      import: { source: "claude_code", source_cwd: "/repo/web", agent_id: "agent-1" },
    }),
    sessionFixture("cx-1", {
      title: "Codex refactor plan",
      last_message: "Plan the codex refactor.",
      import: { source: "codex", source_cwd: "" },
    }),
    sessionFixture("cx-2", {
      title: "Codex follow-up",
      last_message: "Follow up on the codex plan.",
      import: { source: "codex", source_cwd: "" },
    }),
  ];
}

describe("MyAgentsSection smoke", () => {
  beforeEach(() => {
    vi.mocked(listImportedSessions).mockResolvedValue(standardSessions());
    vi.mocked(getAgents).mockResolvedValue([AGENT]);
    // restoreMocks wipes module-mock implementations between tests, so the
    // happy-path permission grant is (re)installed here.
    vi.mocked(ensureReadPermission).mockResolvedValue(true);
  });

  it("renders the empty state and opens the import wizard from it", async () => {
    vi.mocked(listImportedSessions).mockResolvedValue([]);
    vi.mocked(getAgents).mockResolvedValue([]);
    const view = render(<MyAgentsSection />);

    expect(
      await screen.findByRole("heading", { name: "No agents yet" }),
    ).toBeInTheDocument();
    // With no cards the header action is hidden; the empty state carries the
    // single "Import conversations" affordance.
    expect(
      screen.getAllByRole("button", { name: "Import conversations" }),
    ).toHaveLength(1);
    expect(screen.queryByTestId("session-list")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Import conversations" }));
    expect(screen.getByTestId("import-wizard")).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByTestId("import-wizard")).getByRole("button", {
        name: "Finish import",
      }),
    );
    await waitFor(() =>
      expect(listImportedSessions).toHaveBeenCalledTimes(2),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("import-wizard")).toBeNull(),
    );
    view.unmount();
  });

  it("renders agent and ungrouped cards from real attribution grouping", async () => {
    const view = render(<MyAgentsSection />);

    // The agent card reflects its owned sessions via the real attribution map.
    expect(await screen.findByText("Refactor crew")).toBeInTheDocument();
    expect(
      screen.getByText(`${SOURCE_LABEL.claude_code} · All conversations · 2 conversations`),
    ).toBeInTheDocument();
    expect(screen.getByText("Not synced yet")).toBeInTheDocument();

    // Sessions without a matching agent land in the source bucket; the
    // source name is the card title, the subtitle carries the Ungrouped tag.
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Ungrouped · 2 conversations")).toBeInTheDocument();

    // The selected card (first by registry order) feeds the session list.
    await waitFor(() =>
      expect(screen.getByTestId("session-list")).toHaveAttribute("data-count", "2"),
    );
    expect(screen.getByTestId("session-row-cs-1")).toBeInTheDocument();
    expect(screen.getByTestId("session-row-cs-2")).toBeInTheDocument();
    view.unmount();
  });

  it("routes to a conversation and filters the visible list by search", async () => {
    const view = render(<MyAgentsSection />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open New conversation" }),
    );
    expect(fixtures.setActiveSessionId).toHaveBeenCalledWith("cs-1");
    expect(fixtures.routerPush).toHaveBeenCalledWith("/chat/cs-1");

    fireEvent.change(
      screen.getByPlaceholderText("Search conversations..."),
      { target: { value: "photosynthesis" } },
    );
    await waitFor(() =>
      expect(screen.getByTestId("session-list")).toHaveAttribute("data-count", "1"),
    );
    expect(screen.getByTestId("session-row-cs-1")).toBeInTheDocument();
    expect(screen.queryByTestId("session-row-cs-2")).toBeNull();

    fireEvent.change(
      screen.getByPlaceholderText("Search conversations..."),
      { target: { value: "no-such-thing" } },
    );
    await waitFor(() =>
      expect(screen.getByTestId("session-list")).toHaveAttribute("data-count", "0"),
    );
    view.unmount();
  });

  it("deletes a session only after the confirm dialog is accepted", async () => {
    const view = render(<MyAgentsSection />);
    await screen.findByTestId("session-row-cs-1");

    vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete New conversation" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledTimes(1));
    expect(deleteSession).not.toHaveBeenCalled();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete New conversation" }));
    await waitFor(() => expect(deleteSession).toHaveBeenCalledWith("cs-1"));
    await waitFor(() =>
      expect(screen.getByTestId("session-list")).toHaveAttribute("data-count", "1"),
    );
    expect(screen.queryByTestId("session-row-cs-1")).toBeNull();
    view.unmount();
  });

  it("renames a session through the list callback and reloads", async () => {
    const view = render(<MyAgentsSection />);
    await screen.findByTestId("session-row-cs-1");

    fireEvent.click(
      screen.getByRole("button", { name: "Rename New conversation" }),
    );
    await waitFor(() =>
      expect(updateSessionTitle).toHaveBeenCalledWith(
        "cs-1",
        "Renamed New conversation",
      ),
    );
    await waitFor(() =>
      expect(listImportedSessions).toHaveBeenCalledTimes(2),
    );
    view.unmount();
  });

  it("renames an agent through the card menu and keeps Escape from saving", async () => {
    const view = render(<MyAgentsSection />);
    await screen.findByText("Refactor crew");

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));

    // Scoped by value: the section's search input is also a textbox.
    const input = screen.getByDisplayValue("Refactor crew");
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "  Refactor crew v2  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(saveAgent).toHaveBeenCalledWith(
        expect.objectContaining({ id: "agent-1", name: "Refactor crew v2" }),
      ),
    );
    // The rename re-syncs the card list.
    await waitFor(() => expect(listImportedSessions).toHaveBeenCalledTimes(2));

    // Escape cancels the second rename without touching the registry.
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    fireEvent.keyDown(screen.getByDisplayValue("Refactor crew"), {
      key: "Escape",
    });
    await waitFor(() =>
      expect(screen.queryByDisplayValue("Refactor crew")).toBeNull(),
    );
    expect(saveAgent).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("opens the scope editor for the selected agent", async () => {
    const view = render(<MyAgentsSection />);
    await screen.findByText("Refactor crew");

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit scope" }));

    const editor = screen.getByTestId("scope-editor");
    expect(editor).toHaveAttribute("data-agent-id", "agent-1");
    expect(editor).toHaveAttribute("data-owned", "2");
    view.unmount();
  });

  it("deletes an agent plus its owned sessions after confirmation", async () => {
    const view = render(<MyAgentsSection />);
    await screen.findByText("Refactor crew");

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete agent" }));

    await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith("agent-1"));
    await waitFor(() => expect(deleteSession).toHaveBeenCalledWith("cs-1"));
    expect(deleteSession).toHaveBeenCalledWith("cs-2");
    await waitFor(() => expect(listImportedSessions).toHaveBeenCalledTimes(2));
    view.unmount();
  });

  it("surfaces the refresh-failure note when the handle permission is gone", async () => {
    vi.mocked(ensureReadPermission).mockResolvedValue(false);
    const view = render(<MyAgentsSection />);
    await screen.findByText("Refactor crew");

    fireEvent.click(screen.getByRole("button", { name: "Refresh history" }));
    expect(
      await screen.findByText("Refresh failed — try re-adding the agent."),
    ).toBeInTheDocument();
    expect(scanDirectory).not.toHaveBeenCalled();
    view.unmount();
  });

  it("re-syncs an agent and reports the newly imported count", async () => {
    vi.mocked(scanDirectory).mockResolvedValue({
      source: "claude_code",
      handle: AGENT.handle,
      projects: [
        { cwd: "/repo/web", label: "", sessions: [] },
      ],
    } as unknown as Awaited<ReturnType<typeof scanDirectory>>);
    vi.mocked(parseSessions).mockResolvedValue([
      { external_id: "n-1" },
      { external_id: "n-2" },
    ] as unknown as Awaited<ReturnType<typeof parseSessions>>);
    vi.mocked(importChatHistory).mockResolvedValue({
      imported: 2,
      skipped: 0,
      sessions: [],
    });

    const view = render(<MyAgentsSection />);
    await screen.findByText("Refactor crew");

    fireEvent.click(screen.getByRole("button", { name: "Refresh history" }));
    await waitFor(() =>
      expect(importChatHistory).toHaveBeenCalledWith(
        "claude_code",
        expect.anything(),
        { id: "agent-1", name: "Refactor crew" },
      ),
    );
    expect(saveAgent).toHaveBeenCalledWith(
      expect.objectContaining({ id: "agent-1", lastSyncAt: expect.any(Number) }),
    );
    expect(
      await screen.findByText("Added 2 new conversations"),
    ).toBeInTheDocument();
    // The reload after import refreshes the session list with force=true.
    expect(listImportedSessions).toHaveBeenNthCalledWith(2, 200, 0, { force: true });
    view.unmount();
  });
});

describe("MyAgentsPicker smoke", () => {
  const onApply = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    vi.mocked(listImportedSessions).mockResolvedValue(standardSessions());
    vi.mocked(getAgents).mockResolvedValue([AGENT]);
    onApply.mockClear();
    onClose.mockClear();
  });

  function renderPicker(open = true) {
    return render(
      <MyAgentsPicker open={open} onApply={onApply} onClose={onClose} />,
    );
  }

  function dayToggleName(): string {
    return new Date(`${codexDayKey}T00:00:00`).toLocaleDateString("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
      weekday: "short",
    });
  }

  /** Expand the Claude Code project group so its rows mount. */
  async function openProjectGroup() {
    await screen.findByRole("button", { name: /Refactor crew\s*2/ });
    fireEvent.click(screen.getByRole("button", { name: "web" }));
    await screen.findByText("New chat");
  }

  it("renders the dialog shell and recovers from a failed load", async () => {
    vi.mocked(listImportedSessions).mockRejectedValue(new Error("offline"));
    const view = renderPicker();

    expect(
      await screen.findByText("No imported conversations found."),
    ).toBeInTheDocument();
    // No agent chips survived the failed load; the apply action stays locked.
    expect(screen.queryByRole("button", { name: /Refactor crew\s*2/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Use Selected (0)" })).toBeDisabled();
    expect(onClose).not.toHaveBeenCalled();
    view.unmount();
  });

  it("groups conversations by agent chip, project and day", async () => {
    const view = renderPicker();

    // Chips: every owner with at least one conversation, "All" first.
    expect(
      await screen.findByRole("button", { name: /Refactor crew\s*2/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Codex\s*2/ }),
    ).toBeInTheDocument();

    // Claude Code rows group under the project label; Codex under the day.
    fireEvent.click(screen.getByRole("button", { name: "web" }));
    expect(screen.getByText("New chat")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: dayToggleName() }));
    expect(screen.getByText("Codex refactor plan")).toBeInTheDocument();
    expect(screen.getByText("Codex follow-up")).toBeInTheDocument();
    expect(screen.getAllByText("4 messages")).toHaveLength(4);

    // Switching to the agent chip drops the ungrouped groups.
    fireEvent.click(screen.getByRole("button", { name: /Refactor crew\s*2/ }));
    expect(screen.queryByText("Codex refactor plan")).toBeNull();
    expect(screen.getByRole("button", { name: "web" })).toBeInTheDocument();
    view.unmount();
  });

  it("filters rows by title and last message, and shows the empty text on no match", async () => {
    const view = renderPicker();
    await screen.findByRole("button", { name: /Refactor crew\s*2/ });

    // Searching reveals collapsed groups, so matches are always visible.
    fireEvent.change(
      screen.getByPlaceholderText(
        "Search conversations by title or last message",
      ),
      { target: { value: "photosynthesis" } },
    );
    expect(screen.getByText("New chat")).toBeInTheDocument();
    expect(screen.queryByText("Quantum tunneling")).toBeNull();

    // The last message participates in the filter too.
    fireEvent.change(
      screen.getByPlaceholderText(
        "Search conversations by title or last message",
      ),
      { target: { value: "tunneling happens" } },
    );
    expect(screen.getByText("Quantum tunneling")).toBeInTheDocument();
    expect(screen.queryByText("New chat")).toBeNull();

    fireEvent.change(
      screen.getByPlaceholderText(
        "Search conversations by title or last message",
      ),
      { target: { value: "zzz-no-match" } },
    );
    expect(
      screen.getByText("No imported conversations found."),
    ).toBeInTheDocument();
    view.unmount();
  });

  it("toggles rows and whole groups and clears the selection", async () => {
    const view = renderPicker();
    await openProjectGroup();

    const apply = screen.getByRole("button", { name: "Use Selected (0)" });
    expect(apply).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
    expect(screen.getByText("1 conversation selected")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Use Selected (1)" }),
    ).toBeEnabled();

    // Selecting the whole Codex day adds both of its rows.
    const dayHeader = screen
      .getByRole("button", { name: dayToggleName() })
      .closest("div");
    fireEvent.click(
      within(dayHeader as HTMLElement).getByRole("button", { name: "Select" }),
    );
    expect(screen.getByText("3 conversations selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("0 conversations selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use Selected (0)" })).toBeDisabled();
    view.unmount();
  });

  it("applies the selection with mapped titles and closes", async () => {
    const view = renderPicker();
    await openProjectGroup();

    // The backend sentinel "New conversation" is delivered as "New chat".
    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use Selected (1)" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith([
      { sessionId: "cs-1", title: "New chat" },
    ]);
    expect(onClose).toHaveBeenCalledTimes(1);

    // Reopening resets transient selection state.
    view.rerender(
      <MyAgentsPicker open={false} onApply={onApply} onClose={onClose} />,
    );
    view.rerender(
      <MyAgentsPicker open onApply={onApply} onClose={onClose} />,
    );
    await screen.findByRole("button", { name: /Refactor crew\s*2/ });
    expect(screen.getByText("0 conversations selected")).toBeInTheDocument();
    view.unmount();
  });

  it("previews a conversation, selects from the preview, and returns", async () => {
    vi.mocked(getSession).mockResolvedValue({
      messages: [
        { id: 1, role: "user", content: "Hello world" },
        { id: 2, role: "system", content: "hidden scaffold" },
      ],
    } as unknown as Awaited<ReturnType<typeof getSession>>);
    const view = renderPicker();
    await openProjectGroup();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(getSession).toHaveBeenCalledWith("cs-1");
    expect(await screen.findByText("Hello world")).toBeInTheDocument();
    expect(screen.queryByText("hidden scaffold")).toBeNull();
    expect(screen.getByText("You")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(screen.getByText("1 conversation selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Selected" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      screen.getByPlaceholderText(
        "Search conversations by title or last message",
      ),
    ).toBeInTheDocument();
    view.unmount();
  });

  it("shows the no-readable-messages state when preview fails to load", async () => {
    vi.mocked(getSession).mockRejectedValue(new Error("gone"));
    const view = renderPicker();
    await openProjectGroup();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(
      await screen.findByText(
        "This conversation has no readable messages.",
      ),
    ).toBeInTheDocument();
    view.unmount();
  });

  it("does not load anything while closed", () => {
    const view = renderPicker(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listImportedSessions).not.toHaveBeenCalled();
    expect(getAgents).not.toHaveBeenCalled();
    view.unmount();
  });
});
