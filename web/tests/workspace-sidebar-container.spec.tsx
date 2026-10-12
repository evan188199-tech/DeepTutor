import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import type { SessionSummary } from "@/lib/session-api";

const h = vi.hoisted(() => {
  const adapter = {
    newSession: vi.fn(),
    configureSession: vi.fn(),
    cancelStreamingTurn: vi.fn(),
    selectedSessionId: null as string | null,
    sessionStatuses: {} as Record<string, {
      sessionId: string;
      status: string;
      activeTurnId: string | null;
      updatedAt: number;
    }>,
    sidebarRefreshToken: 0,
  };
  return {
    adapter,
    shellProps: [] as Record<string, unknown>[],
    busListeners: [] as Array<() => void>,
    probe: {
      selectId: "s1",
      renameId: "s1",
      deleteId: "s1",
      organizeId: "s1",
      patch: {} as Record<string, unknown>,
    },
    push: vi.fn(),
    navigateTask: vi.fn(),
    selectWorkspace: vi.fn(),
    listAllSessions: vi.fn(),
    listCourses: vi.fn(),
    fetchMasteryTopicIndex: vi.fn(),
    fetchReadingCollectionIndex: vi.fn(),
    deleteSession: vi.fn(),
    updateSessionTitle: vi.fn(),
    updateSessionOrganization: vi.fn(),
    reconcileUnread: vi.fn(),
  };
});

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => h.adapter,
}));

vi.mock("@/lib/session-api", () => ({
  sessionWorkspaceId: (session?: { content_workspace_id?: string; preferences?: { workspace_id?: string | null } }) =>
    session?.content_workspace_id ?? session?.preferences?.workspace_id ?? "",
  listAllSessions: h.listAllSessions,
  deleteSession: h.deleteSession,
  updateSessionTitle: h.updateSessionTitle,
  updateSessionOrganization: h.updateSessionOrganization,
}));

vi.mock("@/lib/courses-api", () => ({ listCourses: h.listCourses }));
vi.mock("@/lib/learning-api", () => ({ fetchMasteryTopicIndex: h.fetchMasteryTopicIndex }));
vi.mock("@/lib/reading-workspace-api", () => ({ fetchReadingCollectionIndex: h.fetchReadingCollectionIndex }));
vi.mock("@/lib/workspace-scope", () => ({ navigateTask: h.navigateTask, selectWorkspace: h.selectWorkspace }));
vi.mock("@/lib/workspaces-api", () => ({
  workspaceChatHref: (workspaceId: string) => `/chat?dt_workspace=${workspaceId}`,
}));
vi.mock("@/lib/session-unread", () => ({ reconcileUnread: h.reconcileUnread }));
vi.mock("@/lib/session-events", () => ({
  subscribeSessionChanges: (listener: () => void) => {
    h.busListeners.push(listener);
    return () => {};
  },
  notifySessionsChanged: () => {},
}));
vi.mock("@/lib/mastery-session", () => ({
  sessionRoute: (session: { session_id: string }) => `/route/${session.session_id}`,
  readingWorkspaceIdOf: (session: {
    preferences?: { workspace_mode?: string; reading_workspace_id?: string };
  }) =>
    session.preferences?.workspace_mode === "immersive_reading"
      ? String(session.preferences.reading_workspace_id || "")
      : "",
}));
vi.mock("@/lib/learning-routes", () => ({
  readingCollectionRoute: (workspaceId: string, contentWorkspaceId = "") =>
    `/reading/${workspaceId}/${contentWorkspaceId}`,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: h.push }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/auth/ProfileLink", () => ({ ProfileLink: () => <button type="button">footer-profile</button> }));
vi.mock("@/components/auth/AdminLink", () => ({ AdminLink: () => <button type="button">footer-admin</button> }));
vi.mock("@/components/auth/LogoutButton", () => ({ LogoutButton: () => <button type="button">footer-logout</button> }));
vi.mock("@/components/sidebar/SidebarShell", () => ({
  SidebarShell: (props: Record<string, unknown>) => {
    h.shellProps.push(props);
    return (
      <div data-testid="sidebar-shell">
        <button type="button" onClick={() => (props.onNewChat as () => void)()}>probe:new-chat</button>
        <button
          type="button"
          onClick={() => (props.onSelectSession as (id: string) => void)(h.probe.selectId)}
        >
          probe:select
        </button>
        <button
          type="button"
          onClick={() => (props.onNewWorkspaceChat as (id: string) => void)("ws-9")}
        >
          probe:workspace-chat
        </button>
        <button
          type="button"
          onClick={() =>
            void (props.onRenameSession as (id: string, title: string) => Promise<void>)(
              h.probe.renameId,
              "Renamed",
            )
          }
        >
          probe:rename
        </button>
        <button
          type="button"
          onClick={() =>
            void (props.onDeleteSession as (id: string) => Promise<void>)(h.probe.deleteId)
          }
        >
          probe:delete
        </button>
        <button
          type="button"
          onClick={() =>
            void (props.onOrganizeSession as (
              id: string,
              patch: Record<string, unknown>,
            ) => Promise<void>)(h.probe.organizeId, h.probe.patch)
          }
        >
          probe:organize
        </button>
        {(props.footerSlot as (collapsed: boolean) => ReactNode)(false)}
      </div>
    );
  },
}));

function makeSession(id: string, overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id,
    session_id: id,
    title: `Title ${id}`,
    created_at: 1,
    updated_at: 1,
    message_count: 0,
    last_message: "",
    ...overrides,
  };
}

function sessionIds(props: Record<string, unknown>): string[] {
  return (props.sessions as SessionSummary[]).map((session) => session.session_id);
}

function lastProps(): Record<string, unknown> {
  return h.shellProps[h.shellProps.length - 1];
}

async function flush() {
  await act(async () => {});
}

beforeEach(() => {
  h.shellProps.length = 0;
  h.busListeners.length = 0;
  h.adapter.selectedSessionId = null;
  h.adapter.sessionStatuses = {};
  h.adapter.sidebarRefreshToken = 0;
  h.probe.selectId = "s1";
  h.probe.renameId = "s1";
  h.probe.deleteId = "s1";
  h.probe.organizeId = "s1";
  h.probe.patch = {};
  h.listAllSessions.mockResolvedValue([makeSession("s1"), makeSession("s2")]);
  h.listCourses.mockResolvedValue([{ id: "course-1", name: "Physics" }]);
  h.fetchMasteryTopicIndex.mockResolvedValue([
    { path_id: "topic-1", name: "Kinematics", emoji: "A" },
  ]);
  h.fetchReadingCollectionIndex.mockResolvedValue([
    { workspace_id: "read-ws", title: "Essays" },
  ]);
  h.deleteSession.mockResolvedValue(undefined);
  h.updateSessionTitle.mockResolvedValue({ title: "Renamed", updated_at: 42 });
  h.updateSessionOrganization.mockResolvedValue({ updated_at: 55, preferences: {} });
});

it("loads the four indexes on mount and hands them to the shell", async () => {
  render(<WorkspaceSidebar />);
  expect(h.shellProps.some((props) => props.loadingSessions === true)).toBe(true);
  await flush();
  const props = lastProps();
  expect(h.listAllSessions).toHaveBeenCalledWith({ force: true, allWorkspaces: true });
  expect(h.listCourses).toHaveBeenCalledWith({ force: true });
  expect(props.loadingSessions).toBe(false);
  expect(sessionIds(props)).toEqual(["s1", "s2"]);
  expect(props.courses).toEqual([{ id: "course-1", name: "Physics" }]);
  expect(props.masteryTopics).toEqual([{ path_id: "topic-1", name: "Kinematics", emoji: "A" }]);
  expect(props.readingCollections).toEqual([{ workspace_id: "read-ws", title: "Essays" }]);
  expect(props.activeSessionId).toBe(null);
  expect(props.workspaceRefreshToken).toBe(0);
});

it("renders the footer links through the shell slot", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  expect(screen.getByText("footer-profile")).toBeInTheDocument();
  expect(screen.getByText("footer-admin")).toBeInTheDocument();
  expect(screen.getByText("footer-logout")).toBeInTheDocument();
});

it("keeps the session list when the secondary indexes fail", async () => {
  h.listCourses.mockRejectedValue(new Error("courses down"));
  h.fetchMasteryTopicIndex.mockRejectedValue(new Error("topics down"));
  h.fetchReadingCollectionIndex.mockRejectedValue(new Error("collections down"));
  render(<WorkspaceSidebar />);
  await flush();
  const props = lastProps();
  expect(props.loadingSessions).toBe(false);
  expect(sessionIds(props)).toEqual(["s1", "s2"]);
  expect(props.courses).toEqual([]);
  expect(props.masteryTopics).toEqual([]);
  expect(props.readingCollections).toEqual([]);
  expect(console.error).not.toHaveBeenCalledWith("Failed to load sessions", expect.anything());
});

it("logs and clears loading when the session index itself fails", async () => {
  h.listAllSessions.mockRejectedValue(new Error("sessions down"));
  render(<WorkspaceSidebar />);
  await flush();
  const props = lastProps();
  expect(props.loadingSessions).toBe(false);
  expect(props.sessions).toEqual([]);
  expect(console.error).toHaveBeenCalledWith("Failed to load sessions", expect.anything());
});

it("refreshes silently on the sidebar token and on the session bus", async () => {
  const view = render(<WorkspaceSidebar />);
  await flush();
  const rendersBeforeRefresh = h.shellProps.length;

  h.listAllSessions.mockImplementationOnce(
    () => new Promise<SessionSummary[]>(() => {}),
  );
  h.adapter.sidebarRefreshToken = 1;
  view.rerender(<WorkspaceSidebar />);
  expect(h.listAllSessions).toHaveBeenCalledTimes(2);
  expect(
    h.shellProps.slice(rendersBeforeRefresh).every((props) => props.loadingSessions === false),
  ).toBe(true);

  h.listAllSessions.mockResolvedValueOnce([makeSession("s3")]);
  act(() => {
    h.busListeners[0]!();
  });
  await flush();
  expect(h.listAllSessions).toHaveBeenCalledTimes(3);
  expect(sessionIds(lastProps())).toEqual(["s3"]);
  expect(lastProps().loadingSessions).toBe(false);
});

it("starts a fresh chat without touching running turns", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:new-chat"));
  expect(h.adapter.newSession).toHaveBeenCalledWith({ workspaceId: null });
  expect(h.adapter.cancelStreamingTurn).not.toHaveBeenCalled();
  expect(h.navigateTask).toHaveBeenCalledWith("/chat", h.push);
});

it("opens a known conversation on its own route", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  h.probe.selectId = "s2";
  fireEvent.click(screen.getByText("probe:select"));
  expect(h.navigateTask).toHaveBeenCalledWith("/route/s2", h.push);
});

it("falls back to the chat path for a session it no longer knows", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  h.probe.selectId = "ghost";
  fireEvent.click(screen.getByText("probe:select"));
  expect(h.navigateTask).toHaveBeenCalledWith("/chat/ghost", h.push);
});

it("renames a conversation through the API and updates the row in place", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  h.probe.renameId = "s2";
  fireEvent.click(screen.getByText("probe:rename"));
  await flush();
  expect(h.updateSessionTitle).toHaveBeenCalledWith("s2", "Renamed", "");
  const renamed = (lastProps().sessions as SessionSummary[]).find(
    (session) => session.session_id === "s2",
  );
  expect(renamed).toMatchObject({ title: "Renamed", updated_at: 42 });
  expect(sessionIds(lastProps())).toEqual(["s1", "s2"]);
});

it("skips deletion when the reader does not confirm", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:delete"));
  await flush();
  expect(h.deleteSession).not.toHaveBeenCalled();
  expect(sessionIds(lastProps())).toEqual(["s1", "s2"]);
});

it("removes a background conversation without navigating away", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  h.adapter.selectedSessionId = "s2";
  h.probe.deleteId = "s1";
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:delete"));
  await flush();
  expect(h.deleteSession).toHaveBeenCalledWith("s1", "");
  expect(sessionIds(lastProps())).toEqual(["s2"]);
  expect(h.adapter.cancelStreamingTurn).not.toHaveBeenCalled();
  expect(h.adapter.newSession).not.toHaveBeenCalled();
  expect(h.navigateTask).not.toHaveBeenCalled();
});

it("resets the surface after deleting the conversation being read", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  h.adapter.selectedSessionId = "s1";
  h.probe.deleteId = "s1";
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:delete"));
  await flush();
  expect(h.deleteSession).toHaveBeenCalledWith("s1", "");
  expect(sessionIds(lastProps())).toEqual(["s2"]);
  expect(h.adapter.cancelStreamingTurn).toHaveBeenCalled();
  expect(h.adapter.newSession).toHaveBeenCalledWith({ workspaceId: null });
  expect(h.navigateTask).toHaveBeenCalledWith("/chat", h.push);
});

it("keeps the reader on its material after deleting its conversation", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  h.listAllSessions.mockResolvedValue([
    makeSession("r1", {
      preferences: {
        workspace_mode: "immersive_reading",
        reading_workspace_id: "read-ws",
      },
    }),
  ]);
  h.adapter.selectedSessionId = "r1";
  h.probe.deleteId = "r1";
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:delete"));
  await flush();
  expect(h.deleteSession).toHaveBeenCalledWith("r1", "");
  expect(h.navigateTask).toHaveBeenCalledWith("/reading/read-ws/", h.push);
});

it("moves a conversation to another workspace and follows the selection there", async () => {
  h.adapter.selectedSessionId = "s1";
  h.probe.organizeId = "s1";
  h.probe.patch = { workspace_id: "ws-2" };
  h.updateSessionOrganization.mockResolvedValue({
    updated_at: 55,
    preferences: { workspace_id: "ws-2" },
  });
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:organize"));
  await flush();
  expect(h.updateSessionOrganization).toHaveBeenCalledWith("s1", { workspace_id: "ws-2" }, "");
  expect(h.adapter.configureSession).toHaveBeenCalledWith({ workspaceId: "ws-2" }, "s1");
  expect(h.navigateTask).toHaveBeenCalledWith("/route/s1", h.push);
  const moved = (lastProps().sessions as SessionSummary[]).find(
    (session) => session.session_id === "s1",
  );
  expect(moved).toMatchObject({
    updated_at: 55,
    content_workspace_id: "ws-2",
    preferences: { workspace_id: "ws-2" },
  });
});

it("applies a pin without reconfiguring or navigating", async () => {
  h.probe.patch = { pinned: true };
  h.updateSessionOrganization.mockResolvedValue({
    updated_at: 66,
    preferences: { pinned: true },
  });
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:organize"));
  await flush();
  expect(h.updateSessionOrganization).toHaveBeenCalledWith("s1", { pinned: true }, "");
  expect(h.adapter.configureSession).not.toHaveBeenCalled();
  expect(h.navigateTask).not.toHaveBeenCalled();
  const pinned = (lastProps().sessions as SessionSummary[]).find(
    (session) => session.session_id === "s1",
  );
  expect(pinned).toMatchObject({ updated_at: 66, preferences: { pinned: true } });
});

it("overlays the runtime turn status onto the server rows", async () => {
  h.adapter.selectedSessionId = "s1";
  h.adapter.sessionStatuses = {
    s2: { sessionId: "s2", status: "running", activeTurnId: "turn-9", updatedAt: 1 },
  };
  render(<WorkspaceSidebar />);
  await flush();
  const props = lastProps();
  const live = (props.sessions as SessionSummary[]).find((session) => session.session_id === "s2");
  const idle = (props.sessions as SessionSummary[]).find((session) => session.session_id === "s1");
  expect(live).toMatchObject({ status: "running", active_turn_id: "turn-9" });
  expect(idle?.status).toBeUndefined();
  expect(props.liveSessionIds).toEqual(new Set(["s2"]));
  expect(h.reconcileUnread).toHaveBeenCalledWith(new Set(["s2"]), "s1");
});

it("opens a workspace chat through the workspace chooser", async () => {
  render(<WorkspaceSidebar />);
  await flush();
  fireEvent.click(screen.getByText("probe:workspace-chat"));
  expect(h.selectWorkspace).toHaveBeenCalledWith("ws-9", "/chat?dt_workspace=ws-9");
});
