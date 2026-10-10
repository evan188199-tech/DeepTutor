import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  FollowupThreadState,
  QuizFollowupTabContext,
} from "@/context/QuizFollowupContext";
import type { QuizQuestion } from "@/lib/quiz-types";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import { buildQuizFollowupConfig } from "@/lib/quiz-types";
import { buildSelectionTutorConfig } from "@/lib/selection-tutor";

const translations = vi.hoisted(() => ({ t: vi.fn((key: string) => key) }));
vi.mock("react-i18next", () => ({ useTranslation: () => translations }));

const fx = vi.hoisted(() => ({
  controller: {
    sendMessage: vi.fn(),
    submitAskUserReply: vi.fn(),
  },
  thread: null as FollowupThreadState | null,
  pendingAskUser: false,
  submission: null as Record<string, unknown> | null,
  lastProps: null as Record<string, unknown> | null,
}));

vi.mock("@/context/QuizFollowupContext", () => ({
  useQuizFollowupController: () => fx.controller,
  useFollowupThread: () =>
    fx.thread ?? {
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

vi.mock("@/lib/ask-user-state", () => ({
  hasPendingAskUser: vi.fn(() => fx.pendingAskUser),
}));

vi.mock("@/lib/quiz-types", () => ({
  buildQuizFollowupConfig: vi.fn(() => ({ marker: "quiz-config" })),
}));

vi.mock("@/lib/selection-tutor", () => ({
  buildSelectionTutorConfig: vi.fn(() => ({ marker: "tutor-config" })),
}));

vi.mock("@/components/chat/home/StandaloneComposer", () => ({
  default: (props: {
    onSubmit: (submission: Record<string, unknown>) => void;
    onCancelStreaming: () => void;
    isStreaming: boolean;
    awaitingUserReply?: boolean;
    hasMessages: boolean;
    inputPlaceholder?: string;
  }) => {
    fx.lastProps = props as unknown as Record<string, unknown>;
    return (
      <div>
        <div data-testid="flags">{`streaming=${props.isStreaming} awaiting=${props.awaitingUserReply} hasMessages=${props.hasMessages}`}</div>
        <div data-testid="placeholder">{props.inputPlaceholder}</div>
        <button
          type="button"
          onClick={() => {
            if (fx.submission) props.onSubmit(fx.submission);
          }}
        >
          submit
        </button>
        <button type="button" onClick={() => props.onCancelStreaming()}>
          cancel
        </button>
      </div>
    );
  },
}));

import FollowupChatComposer from "@/components/quiz/FollowupChatComposer";

const QUESTION = {
  question_id: "q1",
  question: "What is 2+2?",
  question_type: "multiple_choice",
  options: { A: "3", B: "4" },
  correct_answer: "B",
  explanation: "",
} as unknown as QuizQuestion;

const ANSWER_IMAGES = [
  { id: "i1", base64: "QjY0", url: null, filename: "a.png", mime: "image/png" },
  {
    id: "i2",
    base64: null,
    url: "/att/b.png",
    filename: "b.png",
    mime: "image/png",
  },
  { id: "i3", base64: null, url: null, filename: "c.png", mime: "image/png" },
] as QuizFollowupTabContext["answerImages"];

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
    aiJudgment: "judged",
    parentQuizSessionId: null,
    notebookEntryId: null,
    followupSessionId: null,
    language: "en",
    tabLabel: "Q1 follow-up",
    ...overrides,
  };
}

function submission(overrides: Record<string, unknown> = {}) {
  return {
    content: "explain please",
    attachments: [{ type: "doc", filename: "d.pdf" }],
    knowledgeBases: ["kb1"],
    notebookReferences: [{ notebook_id: "n1", record_ids: ["r1"] }],
    historyReferences: ["h1"],
    bookReferences: [{ book_id: "b1", page_ids: ["p1"] }],
    questionNotebookReferences: [7],
    memoryReferences: [],
    persona: null,
    llmSelection: null,
    ...overrides,
  };
}

async function clickSubmit() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "submit" }));
}

beforeEach(() => {
  fx.thread = null;
  fx.pendingAskUser = false;
  fx.submission = submission();
  fx.lastProps = null;
});

describe("FollowupChatComposer", () => {
  it("routes a first send through the controller with quiz config and answer-image attachments", async () => {
    fx.thread = makeThread();
    fx.submission = submission({
      memoryReferences: [{ file_id: "m1" }],
      persona: "Mentor",
      llmSelection: { provider: "p", model: "m" },
    });
    render(
      <FollowupChatComposer
        context={makeContext({ answerImages: ANSWER_IMAGES })}
      />,
    );
    await clickSubmit();
    expect(fx.controller.sendMessage).toHaveBeenCalledTimes(1);
    expect(fx.controller.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        questionKey: "q1",
        content: "explain please",
        attachments: [
          {
            type: "image",
            base64: "QjY0",
            filename: "a.png",
            mime_type: "image/png",
          },
          {
            type: "image",
            url: "/att/b.png",
            filename: "b.png",
            mime_type: "image/png",
          },
          { type: "doc", filename: "d.pdf" },
        ],
        knowledgeBases: ["kb1"],
        notebookReferences: [{ notebook_id: "n1", record_ids: ["r1"] }],
        historyReferences: ["h1"],
        bookReferences: [{ book_id: "b1", page_ids: ["p1"] }],
        questionNotebookReferences: [7],
        persona: "Mentor",
        llmSelection: { provider: "p", model: "m" },
        language: "en",
      }),
    );
    expect(buildQuizFollowupConfig).toHaveBeenCalledTimes(1);
    expect(buildQuizFollowupConfig).toHaveBeenCalledWith(
      QUESTION,
      "B",
      true,
      null,
      { userAnswerImageFilenames: ["a.png", "b.png", "c.png"], aiJudgment: "judged" },
    );
    const input = fx.controller.sendMessage.mock.calls[0][0];
    expect(input.config).toEqual({
      marker: "quiz-config",
      memory_references: [{ file_id: "m1" }],
    });
  });

  it("omits memory_references from config when the submission carries none", async () => {
    fx.thread = makeThread({ messages: [{ role: "user", content: "earlier" }] });
    render(<FollowupChatComposer context={makeContext()} />);
    await clickSubmit();
    const input = fx.controller.sendMessage.mock.calls[0][0];
    expect(input.config).toEqual({ marker: "quiz-config" });
    expect("memory_references" in input.config).toBe(false);
  });

  it("routes a pending ask_user turn to submitAskUserReply instead of sendMessage", async () => {
    const lastEvents = [{ type: "tool_result" }];
    fx.pendingAskUser = true;
    fx.thread = makeThread({
      isStreaming: true,
      messages: [{ role: "assistant", content: "", events: lastEvents as never }],
    });
    fx.submission = submission({ content: " my answer " });
    render(<FollowupChatComposer context={makeContext()} />);
    await clickSubmit();
    expect(hasPendingAskUser).toHaveBeenCalledWith(lastEvents);
    expect(fx.controller.submitAskUserReply).toHaveBeenCalledTimes(1);
    expect(fx.controller.submitAskUserReply).toHaveBeenCalledWith("q1", {
      text: " my answer ",
    });
    expect(fx.controller.sendMessage).not.toHaveBeenCalled();

    fx.submission = submission({ content: "   " });
    await clickSubmit();
    expect(fx.controller.submitAskUserReply).toHaveBeenCalledTimes(1);
    expect(fx.controller.sendMessage).not.toHaveBeenCalled();
  });

  it("drops sends while the thread is streaming and not awaiting a reply", async () => {
    fx.thread = makeThread({ isStreaming: true });
    render(<FollowupChatComposer context={makeContext()} />);
    await clickSubmit();
    expect(fx.controller.sendMessage).not.toHaveBeenCalled();
    expect(fx.controller.submitAskUserReply).not.toHaveBeenCalled();
  });

  it("rides answer images along only on the send that opens the thread", async () => {
    fx.thread = makeThread({
      sessionId: "sess-1",
      messages: [{ role: "user", content: "earlier" }],
    });
    render(
      <FollowupChatComposer
        context={makeContext({ answerImages: ANSWER_IMAGES })}
      />,
    );
    await clickSubmit();
    const input = fx.controller.sendMessage.mock.calls[0][0];
    expect(input.attachments).toEqual([{ type: "doc", filename: "d.pdf" }]);
  });

  it("builds the config from tutorSelection for selection-tutor threads", async () => {
    const tutorSelection = {
      selectedText: "some passage",
    } as QuizFollowupTabContext["tutorSelection"];
    fx.thread = makeThread();
    render(<FollowupChatComposer context={makeContext({ tutorSelection })} />);
    await clickSubmit();
    expect(buildQuizFollowupConfig).not.toHaveBeenCalled();
    expect(buildSelectionTutorConfig).toHaveBeenCalledTimes(1);
    expect(buildSelectionTutorConfig).toHaveBeenCalledWith(tutorSelection);
    const input = fx.controller.sendMessage.mock.calls[0][0];
    expect(input.config).toEqual({ marker: "tutor-config" });
  });

  it("forwards thread flags and the placeholder to the composer surface", async () => {
    fx.thread = makeThread({
      isStreaming: true,
      messages: [{ role: "system", content: "sys" }],
    });
    fx.pendingAskUser = true;
    render(<FollowupChatComposer context={makeContext()} />);
    expect(screen.getByTestId("flags")).toHaveTextContent(
      "streaming=true awaiting=true hasMessages=false",
    );
    expect(screen.getByTestId("placeholder")).toHaveTextContent(
      "Ask anything about this question, your answer, or the AI judgment.",
    );
    await clickSubmit();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "cancel" }));
    expect(fx.controller.sendMessage).not.toHaveBeenCalled();
  });

  it("reports hasMessages once a non-system message exists", () => {
    fx.thread = makeThread({
      messages: [
        { role: "system", content: "sys" },
        { role: "user", content: "hello" },
      ],
    });
    render(<FollowupChatComposer context={makeContext()} />);
    expect(screen.getByTestId("flags")).toHaveTextContent(
      "streaming=false awaiting=false hasMessages=true",
    );
  });
});
