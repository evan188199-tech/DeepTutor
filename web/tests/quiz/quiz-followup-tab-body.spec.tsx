import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  FollowupThreadState,
  QuizFollowupTabContext,
} from "@/context/QuizFollowupContext";
import type { QuizQuestion } from "@/lib/quiz-types";
import { getSession } from "@/lib/session-api";

const translations = vi.hoisted(() => ({ t: vi.fn((key: string) => key) }));
vi.mock("react-i18next", () => ({ useTranslation: () => translations }));

const tab = vi.hoisted(() => ({
  controller: {
    hydrateThread: vi.fn(),
    sendMessage: vi.fn(),
    submitAskUserReply: vi.fn(),
  },
  threads: {} as Record<string, FollowupThreadState>,
  segmentsOverride: null as Array<Record<string, unknown>> | null,
}));

vi.mock("@/context/QuizFollowupContext", () => ({
  useQuizFollowupController: () => tab.controller,
  useFollowupThread: (key: string) =>
    tab.threads[key] ?? {
      isOpen: false,
      input: "",
      isStreaming: false,
      currentStage: "",
      sessionId: null,
      activeTurnId: null,
      messages: [],
      error: null,
    },
}));

vi.mock("@/components/quiz/FollowupChatComposer", () => ({
  default: () => <div data-testid="followup-composer" />,
}));

vi.mock("@/components/common/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <>{content}</>,
}));

vi.mock("@/components/chat/home/AskUserOptions", () => ({
  AskUserOptions: ({
    onSubmit,
  }: {
    onSubmit: (reply: { text?: string }) => void;
  }) => (
    <button type="button" onClick={() => onSubmit({ text: "picked" })}>
      ask-user-card
    </button>
  ),
  extractMessageSegments: (_events: unknown, content: string) =>
    tab.segmentsOverride ??
    (content ? [{ kind: "text", text: content, key: "text-0" }] : []),
  leadingTraceEvents: () => [],
}));

vi.mock("@/features/chat/trace", () => ({
  TraceFlow: () => <div data-testid="trace-flow" />,
  StreamingStatus: ({
    content,
    isStreaming,
  }: {
    content: string;
    isStreaming: boolean;
  }) => (
    <div data-testid="streaming-status" data-streaming={String(isStreaming)}>
      {content}
    </div>
  ),
}));

vi.mock("@/hooks/useSmoothStreamText", () => ({
  useSmoothStreamText: (text: string) => text,
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => `ROOT${path}`,
}));

vi.mock("@/lib/session-api", () => ({
  getSession: vi.fn(),
}));

import QuizFollowupTabBody from "@/components/quiz/QuizFollowupTabBody";

const QUESTION = {
  question_id: "q1",
  question: "What is 2+2?",
  question_type: "multiple_choice",
  options: { A: "3", B: "4" },
  correct_answer: "B",
  explanation: "",
} as unknown as QuizQuestion;

const CODING_QUESTION = {
  question_id: "q2",
  question: "Print the sum.",
  question_type: "coding",
  correct_answer: "",
  explanation: "",
} as unknown as QuizQuestion;

function makeThread(
  overrides: Partial<FollowupThreadState> = {},
): FollowupThreadState {
  return {
    isOpen: false,
    input: "",
    isStreaming: false,
    currentStage: "",
    sessionId: null,
    activeTurnId: null,
    messages: [],
    error: null,
    ...overrides,
  };
}

function makeContext(
  overrides: Partial<QuizFollowupTabContext> = {},
): QuizFollowupTabContext {
  return {
    questionKey: "q1",
    question: QUESTION,
    userAnswer: "B",
    isCorrect: true,
    answerImages: [],
    aiJudgment: "",
    parentQuizSessionId: null,
    notebookEntryId: null,
    followupSessionId: null,
    language: "en",
    tabLabel: "Q1 follow-up",
    ...overrides,
  };
}

function renderTab(context: QuizFollowupTabContext = makeContext()) {
  return render(<QuizFollowupTabBody context={context} />);
}

beforeEach(() => {
  tab.threads = {};
  tab.segmentsOverride = null;
  vi.mocked(getSession).mockReset();
  vi.mocked(getSession).mockResolvedValue({ messages: [] } as never);
});

describe("QuizFollowupTabBody", () => {
  it("mounts with quiz header, pinned question, answer card and empty-thread prompt", () => {
    renderTab();
    expect(screen.getByText("Q1 follow-up")).toBeInTheDocument();
    expect(screen.getByText(/Follow-up Chat · multiple_choice/)).toBeInTheDocument();
    expect(screen.getByText("Question")).toBeInTheDocument();
    expect(screen.getByText("What is 2+2?")).toBeInTheDocument();
    expect(screen.getByText("Your Answer")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("AI Judgment")).toBeNull();
    expect(
      screen.getByText(
        "Ask anything about this question, your answer, or the AI judgment.",
      ),
    ).toBeInTheDocument();
    expect(getSession).not.toHaveBeenCalled();
  });

  it("switches to tutor chrome for a selection-tutor context", () => {
    renderTab(
      makeContext({
        tutorSelection: {
          selectedText: "some passage",
        } as QuizFollowupTabContext["tutorSelection"],
      }),
    );
    expect(screen.getByText("Little Tutor")).toBeInTheDocument();
    expect(screen.getByText("Ask about selected text")).toBeInTheDocument();
    expect(screen.getByText("Selected text")).toBeInTheDocument();
    expect(screen.getByText("Ask anything about the selected text.")).toBeInTheDocument();
    expect(screen.queryByText("Your Answer")).toBeNull();
    expect(screen.queryByText("Q1 follow-up")).toBeNull();
  });

  it("renders the message queue: user bubbles, assistant body, filtered system rows and the error banner", () => {
    tab.threads.q1 = makeThread({
      messages: [
        { role: "system", content: "sys-only" },
        { role: "user", content: "why?" },
        { role: "assistant", content: "because", events: [] },
      ],
      error: "stream broke",
    });
    renderTab();
    expect(screen.getByText("why?")).toBeInTheDocument();
    expect(screen.getByTestId("streaming-status")).toHaveTextContent("because");
    expect(screen.queryByText("sys-only")).toBeNull();
    expect(screen.getByText("stream broke")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Ask anything about this question, your answer, or the AI judgment.",
      ),
    ).toBeNull();
  });

  it("marks only the last assistant message as streaming", () => {
    tab.threads.q1 = makeThread({
      isStreaming: true,
      messages: [
        { role: "assistant", content: "first", events: [] },
        { role: "assistant", content: "second", events: [] },
      ],
    });
    renderTab();
    const statuses = screen.getAllByTestId("streaming-status");
    expect(statuses).toHaveLength(2);
    expect(statuses[0]).toHaveAttribute("data-streaming", "false");
    expect(statuses[0]).toHaveTextContent("first");
    expect(statuses[1]).toHaveAttribute("data-streaming", "true");
    expect(statuses[1]).toHaveTextContent("second");
  });

  it("wires an inline ask_user card to controller.submitAskUserReply", async () => {
    const user = userEvent.setup();
    const events = [{ type: "tool_result" }];
    tab.segmentsOverride = [
      { kind: "ask_user", key: "ask-0", data: { prompt: "pick" } },
    ];
    tab.threads.q1 = makeThread({
      messages: [{ role: "assistant", content: "", events: events as never }],
    });
    renderTab();
    await user.click(screen.getByRole("button", { name: "ask-user-card" }));
    expect(tab.controller.submitAskUserReply).toHaveBeenCalledTimes(1);
    expect(tab.controller.submitAskUserReply).toHaveBeenCalledWith("q1", {
      text: "picked",
    });
  });

  it("hydrates prior history from followupSessionId on mount", async () => {
    const detail = {
      messages: [
        { role: "user", content: "hi", events: [] },
        {
          role: "assistant",
          content: "ho",
          events: [{ type: "stage_start", stage: "s" }],
        },
      ],
    };
    vi.mocked(getSession).mockResolvedValue(detail as never);
    renderTab(makeContext({ followupSessionId: "sess-42" }));
    await waitFor(() => expect(getSession).toHaveBeenCalledWith("sess-42"));
    expect(tab.controller.hydrateThread).toHaveBeenCalledTimes(1);
    expect(tab.controller.hydrateThread).toHaveBeenCalledWith(
      "q1",
      "sess-42",
      [
        { role: "user", content: "hi", events: [] },
        {
          role: "assistant",
          content: "ho",
          events: [{ type: "stage_start", stage: "s" }],
        },
      ],
    );
  });

  it("leaves the thread empty when history hydration fails", async () => {
    vi.mocked(getSession).mockRejectedValue(new Error("offline"));
    renderTab(makeContext({ followupSessionId: "sess-42" }));
    await waitFor(() => expect(getSession).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(
        "Ask anything about this question, your answer, or the AI judgment.",
      ),
    ).toBeInTheDocument();
    expect(tab.controller.hydrateThread).not.toHaveBeenCalled();
  });

  it("skips hydration when the in-memory thread already holds a session", () => {
    tab.threads.q1 = makeThread({ sessionId: "sess-live" });
    renderTab(makeContext({ followupSessionId: "sess-42" }));
    expect(getSession).not.toHaveBeenCalled();
    expect(tab.controller.hydrateThread).not.toHaveBeenCalled();
  });

  it("renders answer images: relative urls resolved, previews preferred, bare filenames as fallback", () => {
    renderTab(
      makeContext({
        userAnswer: "",
        answerImages: [
          {
            id: "i1",
            base64: null,
            url: "/att/a.png",
            filename: "a.png",
            mime: "image/png",
            previewUrl: null,
          },
          {
            id: "i2",
            base64: null,
            url: "/att/b.png",
            filename: "b.png",
            mime: "image/png",
            previewUrl: "/blob/preview",
          },
          {
            id: "i3",
            base64: null,
            url: null,
            filename: "c.png",
            mime: "image/png",
            previewUrl: null,
          },
        ],
      }),
    );
    expect(screen.getByAltText("a.png")).toHaveAttribute("src", "ROOT/att/a.png");
    expect(screen.getByAltText("b.png")).toHaveAttribute("src", "/blob/preview");
    expect(screen.getByText("c.png")).toBeInTheDocument();
    expect(screen.queryByAltText("c.png")).toBeNull();
  });

  it("shows the no-answer placeholder only without answer or images", () => {
    renderTab(makeContext({ userAnswer: "" }));
    expect(screen.getByText("No answer recorded.")).toBeInTheDocument();
  });

  it("fences a bare coding answer and shows the AI judgment card", () => {
    renderTab(
      makeContext({
        question: CODING_QUESTION,
        userAnswer: "print(1)",
        aiJudgment: "Solid reasoning.",
      }),
    );
    expect(
      screen.getByText(
        (_, element) =>
          element?.textContent === "```python\nprint(1)\n```" &&
          element.children.length === 0,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("AI Judgment")).toBeInTheDocument();
    expect(screen.getByText("Solid reasoning.")).toBeInTheDocument();
  });
});
