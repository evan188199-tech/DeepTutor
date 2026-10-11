import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MessageItem } from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";
import type {
  MapKnowledgePoint,
  MapModule,
  MasteryTopic,
  ObjectiveStatus,
} from "@/lib/learning-api";
import type { MasteryMode } from "@/lib/mastery-mode";

import { MasteryStudy } from "@/components/space/learning/MasteryStudy";

initI18n("en");

const mocks = vi.hoisted(() => ({
  session: {
    topic: null as MasteryTopic | null,
    topicError: null as string | null,
    knowledgeBases: [] as string[],
    sessionError: null as string | null,
    sessionLoading: false,
    sessionMode: "study" as MasteryMode,
  },
  adapterState: {
    messages: [] as MessageItem[],
    isStreaming: false,
    selectedBranches: {},
    activeCapability: null as string | null,
    language: "en",
    sessionId: null as string | null,
    lastTurnFailed: false,
  },
  sendMessage: vi.fn(),
  setAdapterMode: vi.fn(),
  resendLastMessage: vi.fn(),
  askHint: vi.fn(),
  setModeApi: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("@/hooks/useMasteryStudySession", () => ({
  useMasteryStudySession: () => mocks.session,
}));

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: mocks.adapterState,
    sendMessage: mocks.sendMessage,
    submitUserReply: vi.fn(),
    regenerateLastMessage: vi.fn(),
    deleteTurn: vi.fn(),
    editMessage: vi.fn(),
    switchBranch: vi.fn(),
    loadMessageTrace: () => Promise.resolve(),
    releaseMessageTrace: vi.fn(),
    setMasterySessionMode: mocks.setAdapterMode,
    resendLastMessage: mocks.resendLastMessage,
  }),
}));

vi.mock("@/features/chat/messages", () => ({
  ChatMessageList: (props: Record<string, unknown>) => (
    <div data-testid="chat-message-list">
      <button
        data-testid="msg-answer"
        onClick={() =>
          (
            props.onAnswerMasteryQuestion as (answer: {
              questionId: string;
              text: string;
            }) => boolean
          )({ questionId: "q-1", text: "  my explanation  " })
        }
      />
      <button
        data-testid="msg-skip"
        onClick={() =>
          (
            props.onSkipMasteryQuestion as (questionId: string) => boolean
          )("q-9")
        }
      />
      <button
        data-testid="msg-challenge"
        onClick={() =>
          (
            props.onChallengeMasteryQuestion as (questionId: string) => boolean
          )("q-5")
        }
      />
      <button
        data-testid="msg-resend"
        onClick={() =>
          (props.onResendLastTurn as (() => void) | undefined)?.()
        }
      />
      <span data-testid="msg-can-resend">
        {String(props.canResendLastTurn)}
      </span>
    </div>
  ),
}));

vi.mock("@/components/chat/home/LazySessionViewerPanel", () => ({
  default: (props: { open?: boolean }) => (
    <div data-testid="viewer-panel" data-open={String(Boolean(props.open))} />
  ),
}));

vi.mock("@/components/chat/home/ChatViewerBridges", () => ({
  ChatViewerBridges: () => null,
}));

vi.mock("@/components/chat/home/TurnNavigator", () => ({
  TurnNavigator: () => null,
}));

vi.mock("@/components/chat/home/SessionActivityPanel", () => ({
  buildSessionActivity: () => [],
}));

vi.mock("@/components/notebook/SaveToNotebookModal", () => ({
  default: (props: { open?: boolean }) =>
    props.open ? <div data-testid="save-modal" /> : null,
}));

vi.mock("@/components/space/learning/MasteryComposer", () => ({
  MasteryComposer: (props: Record<string, unknown>) => (
    <div
      data-testid="composer"
      data-placeholder={String(props.placeholder ?? "")}
      data-hint={String(props.askHint ?? "")}
      data-disabled={String(props.disabled)}
    />
  ),
}));

vi.mock("@/components/space/learning/LevelUpCelebration", () => ({
  LevelUpCelebration: () => <div data-testid="level-up" />,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children?: ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/learning-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchMasteryAskHint: mocks.askHint,
  setMasterySessionMode: mocks.setModeApi,
}));

vi.mock("@/lib/notifications", () => ({ notify: mocks.notify }));

function point(
  id: string,
  name: string,
  status: ObjectiveStatus,
): MapKnowledgePoint {
  return {
    id,
    name,
    type: "concept",
    prerequisite_ids: [],
    topic_source_ids: [],
    status,
    mastery: status === "mastered" ? 1 : 0.4,
    mastery_source: "",
    override_note: "",
  };
}

function moduleOf(
  id: string,
  name: string,
  points: MapKnowledgePoint[],
): MapModule {
  return {
    id,
    name,
    objective: "",
    order: 0,
    mastered: points.filter((item) => item.status === "mastered").length,
    total: points.length,
    knowledge_points: points,
  };
}

function topic(overrides: Partial<MasteryTopic> = {}): MasteryTopic {
  return {
    path_id: "path-1",
    name: "Linear Algebra Basics",
    metadata: {
      path_id: "path-1",
      goal: "learn the basics",
      description: "",
      emoji: "",
      map_seed: 0,
      status: "active",
      created_at: 0,
      updated_at: 0,
    },
    sources: [],
    path_revision: 1,
    next: {
      action: "study",
      knowledge_point_id: "kp-2",
      knowledge_point_name: "Eigenvectors",
      knowledge_point_type: "concept",
      status: "learning",
      gate: "qualitative",
      mastery: 0.4,
      threshold: 1,
      reason: "",
      forgetting_risk: 0.1,
      pending_prompt: "",
      session_id: "",
    },
    map: {
      name: "Linear Algebra Basics",
      counts: { mastered: 1, learning: 1, new: 0, total: 2 },
      due_reviews: 0,
      complete: false,
      modules: [
        moduleOf("mod-1", "Foundations", [
          point("kp-1", "Vectors", "mastered"),
          point("kp-2", "Eigenvectors", "learning"),
        ]),
      ],
    },
    reviews: [],
    learner_profile: null,
    session_count: 0,
    updated_at: 0,
    ...overrides,
  };
}

function userMessage(content: string): MessageItem {
  return { id: "m-1", role: "user", content } as unknown as MessageItem;
}

function renderStudy() {
  return render(<MasteryStudy pathId="path-1" />);
}

beforeEach(() => {
  mocks.session.topic = null;
  mocks.session.topicError = null;
  mocks.session.knowledgeBases = [];
  mocks.session.sessionError = null;
  mocks.session.sessionLoading = false;
  mocks.session.sessionMode = "study";
  mocks.adapterState.messages = [];
  mocks.adapterState.isStreaming = false;
  mocks.adapterState.selectedBranches = {};
  mocks.adapterState.activeCapability = null;
  mocks.adapterState.sessionId = null;
  mocks.adapterState.lastTurnFailed = false;
  mocks.askHint.mockReset();
  mocks.askHint.mockResolvedValue("");
  mocks.setModeApi.mockReset();
  mocks.setModeApi.mockResolvedValue({ status: "ok" });
  localStorage.clear();
  sessionStorage.clear();
});

describe("MasteryStudy screen", () => {
  it("shows only a spinner while the topic is still resolving", () => {
    const { container } = renderStudy();

    expect(container.querySelector(".animate-spin")).toBeTruthy();
    expect(
      screen.queryByText("This learning map could not be found"),
    ).toBeNull();
  });

  it("maps a missing topic to the not-found screen with a way back", () => {
    mocks.session.topicError = "Path removed";

    renderStudy();

    expect(
      screen.getByText("This learning map could not be found"),
    ).toBeInTheDocument();
    expect(screen.getByText("Path removed")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to topics" }),
    ).toBeInTheDocument();
  });

  it("renders the header with topic, waypoint, progress counts and mode switch", () => {
    mocks.session.topic = topic();

    renderStudy();

    expect(
      screen.getByRole("heading", { name: "Linear Algebra Basics" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Eigenvectors").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1/2").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("group", { name: "Conversation mode" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Study" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("button", { name: "Save to Notebook" }),
    ).toBeDisabled();
  });

  it("offers the study starters and sends the chosen one", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();

    renderStudy();

    expect(screen.getByText("Next up")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Eigenvectors" }),
    ).toBeInTheDocument();
    const starter = screen.getByRole("button", {
      name: "Start with a quick check of what I already know",
    });
    await user.click(starter);
    expect(mocks.sendMessage).toHaveBeenCalledWith(
      "Start with a quick check of what I already know",
    );
  });

  it("prefills the composer placeholder with the current waypoint", () => {
    mocks.session.topic = topic();

    renderStudy();

    expect(
      screen.getByTestId("composer").getAttribute("data-placeholder"),
    ).toContain("Eigenvectors");
  });

  it("opens a review sitting with its note, empty state and the due-first opening", () => {
    mocks.session.topic = topic();
    mocks.session.sessionMode = "review";

    renderStudy();

    expect(
      screen.getByText(
        "This mode re-tests what you have already learned. It will not teach anything new.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Start here")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Go back over what you know" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Review what is due today" }),
    ).toBeInTheDocument();
    expect(mocks.sendMessage).toHaveBeenCalledWith(
      "Let's review what I have already learned.",
    );
  });

  it("marks a finished outline and links on to a study session", () => {
    mocks.session.topic = topic();
    mocks.session.sessionMode = "outline";
    mocks.adapterState.messages = [userMessage("design the outline")];

    renderStudy();

    expect(
      screen.getByText(
        "Nothing is being taught yet — this mode agrees on what you will learn.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your outline is ready — 2 knowledge points"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Start learning/ }),
    ).toHaveAttribute("href", expect.stringContaining("session"));
    expect(screen.getByTestId("chat-message-list")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save to Notebook" }),
    ).toBeEnabled();
  });

  it("routes question answers, skips and challenges into the tutor turn", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();
    mocks.adapterState.messages = [userMessage("design the outline")];

    renderStudy();

    await user.click(screen.getByTestId("msg-answer"));
    expect(mocks.sendMessage).toHaveBeenCalledWith("my explanation", undefined, undefined, undefined, undefined, {
      masteryAnswer: { question_id: "q-1", text: "my explanation" },
    });

    await user.click(screen.getByTestId("msg-skip"));
    expect(mocks.sendMessage).toHaveBeenCalledWith(
      "Let's skip this question.",
      undefined,
      undefined,
      undefined,
      undefined,
      { masterySkip: { question_id: "q-9" } },
    );

    await user.click(screen.getByTestId("msg-challenge"));
    const challenge = mocks.sendMessage.mock.calls.find(
      (call) => String(call[0]).indexOf("Please review assessment") === 0,
    );
    expect(challenge?.[0]).toContain("q-5");
  });

  it("refuses to send while a turn is still running", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();
    mocks.adapterState.messages = [userMessage("design the outline")];
    mocks.adapterState.isStreaming = true;

    renderStudy();

    await user.click(screen.getByTestId("msg-answer"));
    expect(mocks.sendMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Study" })).toBeDisabled();
  });

  it("keeps a sessionless mode change local so the first turn carries it", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();

    renderStudy();

    await user.click(screen.getByRole("button", { name: "Review" }));
    expect(mocks.setAdapterMode).toHaveBeenCalledWith("review");
    expect(mocks.setModeApi).not.toHaveBeenCalled();
  });

  it("records a mode change on the existing session", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();
    mocks.adapterState.sessionId = "sess-1";

    renderStudy();

    await user.click(screen.getByRole("button", { name: "Outline" }));
    await waitFor(() =>
      expect(mocks.setAdapterMode).toHaveBeenCalledWith("outline"),
    );
    expect(mocks.setModeApi).toHaveBeenCalledWith(
      "path-1",
      "sess-1",
      "outline",
    );
  });

  it("notifies when the mode could not be changed", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();
    mocks.adapterState.sessionId = "sess-1";
    mocks.setModeApi.mockRejectedValueOnce(new Error("mode refused"));

    renderStudy();

    await user.click(screen.getByRole("button", { name: "Outline" }));
    await waitFor(() =>
      expect(mocks.notify).toHaveBeenCalledWith("mode refused", {
        tone: "error",
      }),
    );
    expect(mocks.setAdapterMode).not.toHaveBeenCalledWith("outline");
  });

  it("asks for the next-question hint once the session exists", async () => {
    mocks.session.topic = topic();
    mocks.adapterState.sessionId = "sess-1";
    mocks.askHint.mockResolvedValue("Try linking determinants to invertibility");

    renderStudy();

    await waitFor(() =>
      expect(mocks.askHint).toHaveBeenCalledWith("path-1", "sess-1"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("composer").getAttribute("data-hint")).toBe(
        "Try linking determinants to invertibility",
      ),
    );
  });

  it("celebrates the first refetch that crosses a point into mastered", () => {
    mocks.session.topic = topic();

    const view = renderStudy();
    expect(screen.queryByTestId("level-up")).toBeNull();

    mocks.session.topic = topic({
      map: {
        name: "Linear Algebra Basics",
        counts: { mastered: 2, learning: 0, new: 0, total: 2 },
        due_reviews: 0,
        complete: true,
        modules: [
          moduleOf("mod-1", "Foundations", [
            point("kp-1", "Vectors", "mastered"),
            point("kp-2", "Eigenvectors", "mastered"),
          ]),
        ],
      },
    });
    view.rerender(<MasteryStudy pathId="path-1" />);

    expect(screen.getByTestId("level-up")).toBeInTheDocument();
  });

  it("toggles the outline rail and remembers the choice", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();

    renderStudy();

    expect(screen.getByRole("navigation", { name: "Outline" })).toHaveTextContent(
      "Foundations",
    );
    await user.click(screen.getByRole("button", { name: "Hide outline" }));
    expect(
      screen.getByRole("button", { name: "Show outline" }),
    ).toBeInTheDocument();
  });

  it("opens and closes the session viewer from the header", async () => {
    const user = userEvent.setup();
    mocks.session.topic = topic();

    renderStudy();

    const activity = screen.getByRole("button", { name: "Activity" });
    expect(activity).toHaveAttribute("aria-pressed", "false");
    await user.click(activity);
    expect(screen.getByTestId("viewer-panel")).toHaveAttribute(
      "data-open",
      "true",
    );
    expect(activity).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the reopening state and disables the composer while the session loads", () => {
    mocks.session.topic = topic();
    mocks.session.sessionLoading = true;

    renderStudy();

    expect(screen.getByText("Reopening this session…")).toBeInTheDocument();
    expect(screen.getByTestId("composer")).toHaveAttribute(
      "data-disabled",
      "true",
    );
  });

  it("explains a session that did not open and offers a new one", () => {
    mocks.session.topic = topic();
    mocks.session.sessionError = "Session backend refused";

    renderStudy();

    expect(screen.getByText("The session did not open")).toBeInTheDocument();
    expect(screen.getByText("Session backend refused")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Start a new session" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("composer")).toBeNull();
  });
});
