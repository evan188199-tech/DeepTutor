import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMasteryStudySession } from "@/hooks/useMasteryStudySession";

const mocks = vi.hoisted(() => ({
  revision: 0,
  refresh: vi.fn(),
  topic: vi.fn(),
  sessions: vi.fn(),
  replace: vi.fn(),
  newSession: vi.fn(),
  configureSession: vi.fn(),
  loadSession: vi.fn(),
  showCachedSession: vi.fn(),
  state: {
    sessionKey: "",
    sessionId: null as string | null,
    workspaceMode: null as string | null,
    masteryPathId: null as string | null,
    masterySessionMode: null as string | null,
    isStreaming: false,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock("react-i18next", () => {
  const t = (value: string) => value;
  return { useTranslation: () => ({ t }) };
});
vi.mock("@/hooks/useMasteryPathActivity", () => ({
  useMasteryPathActivity: () => ({
    events: [],
    revision: mocks.revision,
    signal: 0,
    connection: "live" as const,
    error: null,
    refresh: mocks.refresh,
  }),
}));
vi.mock("@/lib/learning-api", () => ({
  fetchMasteryTopic: mocks.topic,
  fetchMasteryTopicSessions: mocks.sessions,
}));
vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: mocks.state,
    newSession: mocks.newSession,
    configureSession: mocks.configureSession,
    loadSession: mocks.loadSession,
    showCachedSession: mocks.showCachedSession,
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function topicFixture(pathId: string, knowledgeBases: string[] = []) {
  return {
    path_id: pathId,
    name: "Cell biology",
    sources: knowledgeBases.map((source_id) => ({
      kind: "knowledge_base",
      available: true,
      source_id,
    })),
  };
}

function Harness({
  pathId,
  routeSessionId,
  courseId = "",
}: {
  pathId: string;
  routeSessionId?: string;
  courseId?: string;
}) {
  const session = useMasteryStudySession(
    pathId,
    routeSessionId,
    courseId,
    "study",
  );
  return (
    <div>
      <span data-testid="topic">
        {session.topic ? session.topic.path_id : "none"}
      </span>
      <span data-testid="topic-error">{session.topicError ?? "none"}</span>
      <span data-testid="kbs">{session.knowledgeBases.join(",")}</span>
      <span data-testid="session-error">
        {session.sessionError ?? "none"}
      </span>
      <span data-testid="loading">{String(session.sessionLoading)}</span>
      <span data-testid="mode">{session.sessionMode}</span>
    </div>
  );
}

const view = (pathId: string, routeSessionId?: string, courseId?: string) => (
  <Harness pathId={pathId} routeSessionId={routeSessionId} courseId={courseId} />
);

beforeEach(() => {
  mocks.revision = 0;
  mocks.state.sessionKey = "";
  mocks.state.sessionId = null;
  mocks.state.workspaceMode = null;
  mocks.state.masteryPathId = null;
  mocks.state.masterySessionMode = null;
  mocks.state.isStreaming = false;
  mocks.newSession.mockImplementation(() => "draft-key-1");
  mocks.showCachedSession.mockImplementation(() => false);
  mocks.topic.mockImplementation(() =>
    Promise.resolve(topicFixture("p1")),
  );
});

describe("useMasteryStudySession", () => {
  it("loads the learning map and binds it to the route", async () => {
    const pending = deferred<ReturnType<typeof topicFixture>>();
    mocks.topic.mockReturnValue(pending.promise);
    render(view("p1"));
    expect(mocks.topic).toHaveBeenCalledWith("p1", { cache: "no-store" });
    expect(screen.getByTestId("topic")).toHaveTextContent("none");
    await act(async () => pending.resolve(topicFixture("p1")));
    await waitFor(() =>
      expect(screen.getByTestId("topic")).toHaveTextContent("p1"),
    );
    expect(screen.getByTestId("topic-error")).toHaveTextContent("none");
  });

  it("a failed topic load surfaces the fallback and clears once a revision refresh succeeds", async () => {
    const failing = deferred<ReturnType<typeof topicFixture>>();
    mocks.topic.mockReturnValueOnce(failing.promise);
    const rendered = render(view("p1"));
    await act(async () => failing.reject(new Error("boom")));
    await waitFor(() =>
      expect(screen.getByTestId("topic-error")).toHaveTextContent("boom"),
    );
    expect(screen.getByTestId("topic")).toHaveTextContent("none");

    const recovered = deferred<ReturnType<typeof topicFixture>>();
    mocks.topic.mockReturnValueOnce(recovered.promise);
    mocks.revision = 7;
    rendered.rerender(view("p1"));
    expect(mocks.topic).toHaveBeenCalledTimes(2);
    await act(async () => recovered.resolve(topicFixture("p1")));
    await waitFor(() =>
      expect(screen.getByTestId("topic")).toHaveTextContent("p1"),
    );
    expect(screen.getByTestId("topic-error")).toHaveTextContent("none");
  });

  it("refreshes the activity map exactly once when a stream ends", async () => {
    mocks.topic.mockImplementation(
      () => new Promise<ReturnType<typeof topicFixture>>(() => {}),
    );
    const rendered = render(view("p1"));
    mocks.state.isStreaming = true;
    rendered.rerender(view("p1"));
    expect(mocks.refresh).not.toHaveBeenCalled();
    mocks.state.isStreaming = false;
    rendered.rerender(view("p1"));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it("a draft route opens a new session with the mastery configuration", async () => {
    const pending = deferred<ReturnType<typeof topicFixture>>();
    mocks.topic.mockReturnValue(pending.promise);
    const rendered = render(view("p1"));
    await act(async () =>
      pending.resolve(topicFixture("p1", ["kb-1"])),
    );
    await waitFor(() => expect(mocks.newSession).toHaveBeenCalledTimes(1));
    expect(mocks.newSession.mock.calls[0][0]).toMatchObject({
      workspaceMode: "mastery_path",
      capability: "mastery_path",
      masteryPathId: "p1",
      knowledgeBases: ["kb-1"],
      masterySessionMode: "study",
    });

    mocks.state.sessionKey = "draft-key-1";
    mocks.state.workspaceMode = "mastery_path";
    mocks.state.masteryPathId = "p1";
    mocks.state.masterySessionMode = "study";
    rendered.rerender(view("p1"));
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("mode")).toHaveTextContent("study");
  });

  it("only available knowledge-base sources feed the session configuration", async () => {
    const pending = deferred<unknown>();
    mocks.topic.mockReturnValue(pending.promise);
    render(view("p1"));
    await act(async () =>
      pending.resolve({
        path_id: "p1",
        sources: [
          { kind: "knowledge_base", available: true, source_id: "kb-1" },
          { kind: "knowledge_base", available: false, source_id: "kb-2" },
          { kind: "file", available: true, source_id: "doc-1" },
          { kind: "knowledge_base", available: true, source_id: "" },
        ],
      }),
    );
    await waitFor(() => expect(mocks.newSession).toHaveBeenCalledTimes(1));
    expect(mocks.newSession.mock.calls[0][0]).toMatchObject({
      knowledgeBases: ["kb-1"],
    });
    await waitFor(() =>
      expect(screen.getByTestId("kbs")).toHaveTextContent("kb-1"),
    );
  });

  it("a bound draft rewrites the URL to its session route, carrying the course", async () => {
    const pending = deferred<ReturnType<typeof topicFixture>>();
    mocks.topic.mockReturnValue(pending.promise);
    const rendered = render(view("p1"));
    await act(async () => pending.resolve(topicFixture("p1")));
    await waitFor(() => expect(mocks.newSession).toHaveBeenCalledTimes(1));
    expect(mocks.replace).not.toHaveBeenCalled();

    mocks.state.sessionId = "s9";
    mocks.state.masteryPathId = "p1";
    rendered.rerender(view("p1"));
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/learning/mastery/p1/sessions/s9",
        { scroll: false },
      ),
    );

    rendered.rerender(view("p1", undefined, "course-7"));
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/learning/mastery/p1/sessions/s9?course=course-7",
        { scroll: false },
      ),
    );
    expect(mocks.newSession).toHaveBeenCalledTimes(1);
  });

  it("an existing session route proves membership, then loads and configures", async () => {
    const topicPending = deferred<ReturnType<typeof topicFixture>>();
    const sessionsPending = deferred<Array<{ session_id: string }>>();
    mocks.topic.mockReturnValue(topicPending.promise);
    mocks.sessions.mockReturnValue(sessionsPending.promise);
    const rendered = render(view("p1", "s1"));
    await act(async () => topicPending.resolve(topicFixture("p1")));
    await waitFor(() =>
      expect(mocks.sessions).toHaveBeenCalledWith("p1", {
        cache: "no-store",
      }),
    );
    await act(async () => sessionsPending.resolve([{ session_id: "s1" }]));
    await waitFor(() => expect(mocks.loadSession).toHaveBeenCalledTimes(1));
    expect(mocks.showCachedSession).toHaveBeenCalledWith("s1");
    expect(mocks.loadSession).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ revalidate: false }),
    );
    expect(mocks.configureSession).toHaveBeenCalledWith(
      expect.objectContaining({ masteryPathId: "p1" }),
      "s1",
    );

    mocks.state.sessionId = "s1";
    mocks.state.workspaceMode = "mastery_path";
    mocks.state.masteryPathId = "p1";
    rendered.rerender(view("p1", "s1"));
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("session-error")).toHaveTextContent("none");
  });

  it("a session that belongs to a different topic is rejected with the membership error", async () => {
    const topicPending = deferred<ReturnType<typeof topicFixture>>();
    const sessionsPending = deferred<Array<{ session_id: string }>>();
    mocks.topic.mockReturnValue(topicPending.promise);
    mocks.sessions.mockReturnValue(sessionsPending.promise);
    render(view("p1", "s1"));
    await act(async () => topicPending.resolve(topicFixture("p1")));
    await act(async () => sessionsPending.resolve([{ session_id: "other" }]));
    await waitFor(() =>
      expect(screen.getByTestId("session-error")).toHaveTextContent(
        "belongs to a different topic",
      ),
    );
    expect(mocks.loadSession).not.toHaveBeenCalled();
    expect(mocks.configureSession).not.toHaveBeenCalled();
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("a failed session load surfaces the error instead of a broken screen", async () => {
    const topicPending = deferred<ReturnType<typeof topicFixture>>();
    const sessionsPending = deferred<Array<{ session_id: string }>>();
    mocks.topic.mockReturnValue(topicPending.promise);
    mocks.sessions.mockReturnValue(sessionsPending.promise);
    mocks.loadSession.mockImplementationOnce(() =>
      Promise.reject(new Error("network lost")),
    );
    render(view("p1", "s1"));
    await act(async () => topicPending.resolve(topicFixture("p1")));
    await act(async () => sessionsPending.resolve([{ session_id: "s1" }]));
    await waitFor(() =>
      expect(screen.getByTestId("session-error")).toHaveTextContent(
        "network lost",
      ),
    );
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });

  it("a cached session configures immediately and revalidates in the background", async () => {
    const topicPending = deferred<ReturnType<typeof topicFixture>>();
    const sessionsPending = deferred<Array<{ session_id: string }>>();
    mocks.topic.mockReturnValue(topicPending.promise);
    mocks.sessions.mockReturnValue(sessionsPending.promise);
    mocks.showCachedSession.mockImplementation(() => true);
    render(view("p1", "s1"));
    await act(async () => topicPending.resolve(topicFixture("p1")));
    await act(async () => sessionsPending.resolve([{ session_id: "s1" }]));
    await waitFor(() => expect(mocks.loadSession).toHaveBeenCalledTimes(1));
    expect(mocks.loadSession).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ revalidate: true }),
    );
    expect(mocks.configureSession).toHaveBeenCalledTimes(2);
    for (const call of mocks.configureSession.mock.calls) {
      expect(call[1]).toBe("s1");
    }
    expect(screen.getByTestId("session-error")).toHaveTextContent("none");
  });
});
