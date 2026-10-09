import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { Component, useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  QuizFollowupProvider,
  useAllFollowupThreads,
  useFollowupThread,
  useQuizFollowupController,
  type FollowupThreadState,
  type QuizFollowupController,
  type QuizFollowupTabContext,
} from "@/context/QuizFollowupContext";
import { updateNotebookEntry } from "@/lib/notebook-api";
import type { StreamEvent } from "@/features/chat/model/protocol";
import type { QuizQuestion } from "@/lib/quiz-types";

interface MockClient {
  connected: boolean;
  connectCount: number;
  onEvent: (event: StreamEvent) => void;
  send: ReturnType<typeof vi.fn>;
  sendAwaitingAck: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  connect: () => void;
}

const clientInstances = vi.hoisted(
  () =>
    [] as Array<{
      connected: boolean;
      connectCount: number;
      onEvent: (event: unknown) => void;
      send: ReturnType<typeof vi.fn>;
      sendAwaitingAck: ReturnType<typeof vi.fn>;
      disconnect: ReturnType<typeof vi.fn>;
      connect: () => void;
    }>,
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/notebook-api", () => ({
  updateNotebookEntry: vi.fn(),
}));

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => {
  class MockUnifiedTurnClient {
    connected = false;
    connectCount = 0;
    onEvent: (event: unknown) => void;
    send = vi.fn();
    sendAwaitingAck = vi.fn().mockResolvedValue(true);
    disconnect = vi.fn();
    constructor(onEvent: (event: unknown) => void) {
      this.onEvent = onEvent;
      clientInstances.push(this);
    }
    connect() {
      this.connected = true;
      this.connectCount += 1;
    }
  }
  return { UnifiedTurnClient: MockUnifiedTurnClient };
});

const KEY = "q1";
const ENTRY_ID = 42;

const QUESTION = {
  question_id: KEY,
  question: "Which?",
  question_type: "multiple_choice",
  options: { A: "one", B: "two" },
  correct_answer: "B",
  explanation: "",
} as unknown as QuizQuestion;

function Harness({ questionKey }: { questionKey: string }) {
  const controller = useQuizFollowupController();
  const thread = useFollowupThread(questionKey);
  const allThreads = useAllFollowupThreads();
  useEffect(() => {
    harness.current = { controller, thread, allThreads };
  });
  return null;
}

const harness: {
  current: {
    controller: QuizFollowupController;
    thread: FollowupThreadState;
    allThreads: Record<string, FollowupThreadState>;
  } | null;
} = { current: null };

type HarnessView = {
  readonly controller: QuizFollowupController;
  readonly thread: FollowupThreadState;
  readonly allThreads: Record<string, FollowupThreadState>;
};

function renderProvider(questionKey = KEY): HarnessView {
  harness.current = null;
  render(
    <QuizFollowupProvider>
      <Harness questionKey={questionKey} />
    </QuizFollowupProvider>,
  );
  return {
    get controller() {
      return harness.current!.controller;
    },
    get thread() {
      return harness.current!.thread;
    },
    get allThreads() {
      return harness.current!.allThreads;
    },
  };
}

function lastClient(): MockClient {
  expect(clientInstances.length).toBeGreaterThan(0);
  return clientInstances[clientInstances.length - 1];
}

function emit(client: MockClient, event: StreamEvent) {
  act(() => {
    client.onEvent(event);
  });
}

function tabContext(
  overrides: Partial<QuizFollowupTabContext> = {},
): QuizFollowupTabContext {
  return {
    questionKey: KEY,
    question: QUESTION,
    userAnswer: "B",
    isCorrect: true,
    answerImages: [],
    aiJudgment: "",
    parentQuizSessionId: null,
    notebookEntryId: ENTRY_ID,
    followupSessionId: null,
    language: "en",
    tabLabel: "Q1 follow-up",
    ...overrides,
  };
}

class Boundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return <div data-testid="caught">{this.state.error.message}</div>;
    }
    return this.props.children;
  }
}

function BareHookConsumer() {
  useQuizFollowupController();
  return null;
}

beforeEach(() => {
  clientInstances.length = 0;
});

describe("QuizFollowupContext provider", () => {
  describe("initialization", () => {
    it("exposes an empty thread snapshot and an empty thread record", () => {
      const h = renderProvider();

      expect(h.thread).toEqual({
        isOpen: false,
        input: "",
        isStreaming: false,
        currentStage: "",
        sessionId: null,
        activeTurnId: null,
        messages: [],
        error: null,
      });
      expect(h.allThreads).toEqual({});
      expect(h.controller.getThread("never-touched")).toEqual(h.thread);
      expect(h.controller.getAllThreads()).toEqual({});
    });

    it("throws a helpful error when the controller hook runs outside the provider", () => {
      render(
        <Boundary>
          <BareHookConsumer />
        </Boundary>,
      );
      expect(screen.getByTestId("caught")).toHaveTextContent(
        "useQuizFollowupController must be used inside a QuizFollowupProvider",
      );
    });

    it("creates an unknown thread entry from the empty defaults when patched", () => {
      const h = renderProvider();

      act(() => {
        h.controller.updateThread("fresh-key", (prev) => ({
          ...prev,
          input: "draft",
        }));
      });

      const created = h.controller.getThread("fresh-key");
      expect(created.input).toBe("draft");
      expect(created.isOpen).toBe(false);
      expect(created.messages).toEqual([]);
      expect(created.sessionId).toBeNull();
      expect(created.error).toBeNull();
    });
  });

  describe("followup queue add / remove / dedup", () => {
    it("appends the user turn, opens the thread and forwards start_turn once", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "  explain B  ",
          attachments: [],
        });
      });

      expect(h.thread.isOpen).toBe(true);
      expect(h.thread.isStreaming).toBe(true);
      expect(h.thread.input).toBe("");
      expect(h.thread.error).toBeNull();
      expect(h.thread.messages).toEqual([
        { role: "user", content: "explain B" },
      ]);
      expect(clientInstances).toHaveLength(1);
      const client = lastClient();
      expect(client.connected).toBe(true);
      expect(client.send).toHaveBeenCalledTimes(1);
      const sent = client.send.mock.calls[0][0] as Record<string, unknown>;
      expect(sent.type).toBe("start_turn");
      expect(sent.content).toBe("explain B");
      expect(sent.capability).toBe("chat");
      expect(sent.session_id).toBeNull();
    });

    it("accepts an attachments-only turn with blank text", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "   ",
          attachments: [{ type: "image", base64: "abc" }],
        });
      });

      expect(h.thread.messages).toEqual([{ role: "user", content: "" }]);
      expect(h.thread.isStreaming).toBe(true);
      expect(lastClient().send).toHaveBeenCalledTimes(1);
    });

    it("ignores blank turns with no attachments instead of queueing phantoms", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "   ",
          attachments: [],
        });
      });

      expect(h.allThreads).toEqual({});
      expect(h.controller.getAllThreads()).toEqual({});
      expect(clientInstances).toHaveLength(0);
    });

    it("does not queue a duplicate user turn while one is streaming", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "first",
          attachments: [],
        });
      });
      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "second",
          attachments: [],
        });
      });

      expect(h.thread.messages).toEqual([{ role: "user", content: "first" }]);
      expect(lastClient().send).toHaveBeenCalledTimes(1);
    });

    it("disposes the runner on done so the next turn gets a fresh client", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "turn one",
          attachments: [],
        });
      });
      const first = lastClient();
      emit(first, {
        type: "done",
        content: "",
        source: "",
        stage: "",
        metadata: {},
        timestamp: 1,
      } as unknown as StreamEvent);

      expect(h.thread.isStreaming).toBe(false);
      expect(h.thread.currentStage).toBe("");
      expect(h.thread.activeTurnId).toBeNull();
      expect(first.disconnect).toHaveBeenCalledTimes(1);

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "turn two",
          attachments: [],
        });
      });
      expect(clientInstances).toHaveLength(2);
      expect(clientInstances[1].connected).toBe(true);
      expect(clientInstances[1].send).toHaveBeenCalledTimes(1);
    });
  });

  describe("persistence recovery", () => {
    it("records the session id and persists it onto the notebook entry", async () => {
      const h = renderProvider();

      act(() => {
        h.controller.openFollowupTab(tabContext());
      });
      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "why?",
          attachments: [],
        });
      });
      emit(lastClient(), {
        type: "session",
        content: "",
        source: "",
        stage: "",
        metadata: { session_id: "sess-9", turn_id: "turn-9" },
        timestamp: 1,
      } as unknown as StreamEvent);

      expect(h.thread.sessionId).toBe("sess-9");
      expect(h.thread.activeTurnId).toBe("turn-9");
      await waitFor(() => {
        expect(updateNotebookEntry).toHaveBeenCalledWith(ENTRY_ID, {
          followup_session_id: "sess-9",
        });
      });
    });

    it("hydrates a fresh thread from the persisted snapshot and normalizes events", () => {
      const h = renderProvider();

      act(() => {
        h.controller.hydrateThread(KEY, "sess-old", [
          { role: "user", content: "q" },
          { role: "assistant", content: "a" },
        ]);
      });

      expect(h.thread.sessionId).toBe("sess-old");
      expect(h.thread.messages).toEqual([
        { role: "user", content: "q", events: [] },
        { role: "assistant", content: "a", events: [] },
      ]);
    });

    it("never overwrites a live thread with a stale snapshot", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "live turn",
          attachments: [],
        });
      });
      act(() => {
        h.controller.hydrateThread(KEY, "sess-stale", [
          { role: "user", content: "stale" },
        ]);
      });

      expect(h.thread.sessionId).toBeNull();
      expect(h.thread.messages).toEqual([
        { role: "user", content: "live turn" },
      ]);
    });
  });

  describe("malformed input tolerance", () => {
    it("ignores session events without any session id", () => {
      const h = renderProvider();

      act(() => {
        h.controller.openFollowupTab(tabContext());
      });
      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "hello",
          attachments: [],
        });
      });
      emit(lastClient(), {
        type: "session",
        content: "",
        source: "",
        stage: "",
        metadata: {},
        timestamp: 1,
      } as unknown as StreamEvent);

      expect(h.thread.sessionId).toBeNull();
      expect(updateNotebookEntry).not.toHaveBeenCalled();
    });

    it("drops malformed config fields and forwards safe defaults", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "hi",
          attachments: [],
          config: {
            followup_question_context: "not-an-object",
            selection_tutor_context: 7,
            consult_partner_id: 123,
            partner_discussion_group_id: false,
            subagent_consult_budget: "lots",
            auto_route: "yes",
          },
        });
      });

      const sent = lastClient().send.mock.calls[0][0] as Record<
        string,
        unknown
      >;
      expect(sent.type).toBe("start_turn");
      expect(sent).not.toHaveProperty("followup_question_context");
      expect(sent).not.toHaveProperty("selection_tutor_context");
      expect(sent).not.toHaveProperty("consult_partner_id");
      expect(sent).not.toHaveProperty("partner_discussion_group_id");
      expect(sent).not.toHaveProperty("subagent_consult_budget");
      expect(sent).not.toHaveProperty("auto_route");
      expect(sent).not.toHaveProperty("config");
      expect(sent.persona).toBe("");
      expect(sent.llm_selection).toBeNull();
    });

    it("keeps the previous error when an error event carries empty content", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "go",
          attachments: [],
        });
      });
      const client = lastClient();
      emit(client, {
        type: "stage_start",
        content: "",
        source: "",
        stage: "thinking",
        metadata: {},
        timestamp: 1,
      } as unknown as StreamEvent);
      expect(h.thread.currentStage).toBe("thinking");
      act(() => {
        h.controller.updateThread(KEY, (prev) => ({
          ...prev,
          error: "boom",
        }));
      });
      emit(client, {
        type: "error",
        content: "",
        source: "",
        stage: "",
        metadata: {},
        timestamp: 2,
      } as unknown as StreamEvent);

      expect(h.thread.error).toBe("boom");
      emit(client, {
        type: "stage_end",
        content: "",
        source: "",
        stage: "thinking",
        metadata: {},
        timestamp: 3,
      } as unknown as StreamEvent);
      expect(h.thread.currentStage).toBe("");
      expect(h.thread.isStreaming).toBe(true);
    });

    it("halts streaming when an error event is marked turn terminal", () => {
      const h = renderProvider();

      act(() => {
        h.controller.sendMessage({
          questionKey: KEY,
          content: "go",
          attachments: [],
        });
      });
      emit(lastClient(), {
        type: "error",
        content: "failed",
        source: "",
        stage: "",
        metadata: { turn_terminal: true },
        timestamp: 1,
      } as unknown as StreamEvent);

      expect(h.thread.error).toBe("failed");
      expect(h.thread.isStreaming).toBe(false);
      expect(h.thread.currentStage).toBe("");
      expect(h.thread.activeTurnId).toBeNull();
    });
  });
});
