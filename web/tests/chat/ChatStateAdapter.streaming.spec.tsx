/**
 * Streaming-state coverage for `ChatStateAdapter` (coverage gap: 352 lines
 * missing / 64.9%, evidence/coverage-2026-10-02/top15-gaps.md candidate 19).
 *
 * Locks the streaming event → UI state mapping through a mock transport:
 * content deltas / stage markers / duplicate-seq dedupe / narration demotion,
 * draft→server session binding, done-time id reconciliation, terminal error
 * and connection-loss state, regenerate rollback, the send retry ladder and
 * the idle-watchdog resubscribe path. Tests only — no product code changes.
 */
import { useEffect } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";

initI18n("en");

const transport = vi.hoisted(() => {
  type WireEvent = Record<string, unknown>;
  type EventListener = (event: WireEvent) => void;

  const instances: MockTurnClient[] = [];
  /** When set, connect() leaves the client unreachable (retry-ladder tests). */
  let unreachable = false;

  class MockTurnClient {
    connected = false;
    sent: WireEvent[] = [];
    acked: WireEvent[] = [];
    resumeStates: Array<{ turnId: string | null; seq: number }> = [];
    connectCalls = 0;
    disconnectCalls = 0;

    constructor(
      private readonly onEvent: EventListener,
      private readonly onClose?: () => void,
    ) {
      instances.push(this);
    }

    connect(): void {
      this.connectCalls += 1;
      if (!unreachable) this.connected = true;
    }

    setResumeState(turnId: string | null, seq: number): void {
      this.resumeStates.push({ turnId, seq });
    }

    disconnect(): void {
      this.disconnectCalls += 1;
      this.connected = false;
    }

    send(message: WireEvent): void {
      this.sent.push(message);
    }

    sendAwaitingAck(message: WireEvent): Promise<boolean> {
      this.acked.push(message);
      return Promise.resolve(true);
    }

    /** Inject a server stream event into the adapter. */
    emit(event: WireEvent): void {
      this.onEvent(event);
    }

    /** Simulate the socket dropping without a terminal event. */
    drop(): void {
      this.connected = false;
      this.onClose?.();
    }
  }

  return {
    MockTurnClient,
    instances,
    last(): MockTurnClient {
      return instances[instances.length - 1];
    },
    setUnreachable(value: boolean): void {
      unreachable = value;
    },
    reset(): void {
      instances.length = 0;
      unreachable = false;
    },
  };
});

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: transport.MockTurnClient,
}));

const sessionApi = vi.hoisted(() => ({
  getSession: vi.fn<
    (sessionId: string) => Promise<Record<string, unknown> | undefined>
  >(),
}));

vi.mock("@/lib/session-api", () => ({
  getSession: sessionApi.getSession,
  getMessageTrace: vi.fn(async () => ({
    turn_id: null,
    total: 0,
    last_seq: 0,
    complete: true,
    next_seq: null,
    events: [],
  })),
  deleteMessage: vi.fn(async () => undefined),
  updateBranchSelection: vi.fn(async () => undefined),
  updateSessionTitle: vi.fn(async (title: string) => ({ title })),
}));

vi.mock("@/lib/notifications", () => ({
  notify: vi.fn(),
}));

import { notify } from "@/lib/notifications";

let eventSeq = 0;

function streamEvent(
  overrides: Partial<StreamEvent> & Pick<StreamEvent, "type">,
): StreamEvent {
  eventSeq += 1;
  return {
    source: "test",
    stage: "",
    content: "",
    metadata: {},
    seq: eventSeq,
    timestamp: Date.now() / 1000,
    ...overrides,
  };
}

// Reassigned on every commit by Probe: always read the latest context value
// through this module variable (a captured ctx goes stale after a dispatch).
let chat!: ReturnType<typeof useChatStateAdapter>;

function Probe() {
  const ctx = useChatStateAdapter();
  useEffect(() => {
    chat = ctx;
  });
  return null;
}

function renderAdapter(): void {
  render(
    <ChatStateAdapterProvider>
      <Probe />
    </ChatStateAdapterProvider>,
  );
}

/** Send one message and return the transport client backing the turn. */
function startTurn(
  content = "Hello there",
): InstanceType<typeof transport.MockTurnClient> {
  act(() => {
    chat.sendMessage(content);
  });
  return transport.last();
}

beforeEach(() => {
  eventSeq = 0;
});

afterEach(() => {
  transport.reset();
  vi.useRealTimers();
});

describe("ChatStateAdapter streaming state mapping", () => {
  it("maps a full turn: user bubble, placeholder, deltas, stages, dedupe, done reconcile", () => {
    renderAdapter();
    const client = startTurn();

    expect(chat.state.messages[0]).toMatchObject({
      role: "user",
      content: "Hello there",
    });
    expect(chat.state.messages[1]).toMatchObject({
      role: "assistant",
      content: "",
      rawContent: "",
    });
    expect(chat.state.isStreaming).toBe(true);
    expect(client.sent[0]).toMatchObject({
      type: "start_turn",
      content: "Hello there",
      // An unconfigured session sends null; buildStartTurnInput's "chat"
      // default only applies when the key is absent.
      capability: null,
      session_id: null,
    });

    const first = streamEvent({
      type: "content",
      content: "Hello ",
      turn_id: "t1",
    });
    act(() => {
      client.emit(first);
      client.emit(
        streamEvent({ type: "content", content: "world", turn_id: "t1" }),
      );
    });
    expect(chat.state.messages[1]).toMatchObject({
      content: "Hello world",
      rawContent: "Hello world",
    });

    act(() => {
      client.emit(
        streamEvent({ type: "stage_start", stage: "exploring", turn_id: "t1" }),
      );
    });
    expect(chat.state.currentStage).toBe("exploring");
    act(() => {
      client.emit(
        streamEvent({ type: "stage_end", stage: "exploring", turn_id: "t1" }),
      );
    });
    expect(chat.state.currentStage).toBe("");

    // A replayed event (same turn_id + seq) must not duplicate text or rows.
    const eventsBefore = chat.state.messages[1].events?.length ?? 0;
    act(() => {
      client.emit(first);
    });
    expect(chat.state.messages[1].content).toBe("Hello world");
    expect(chat.state.messages[1].events?.length).toBe(eventsBefore);

    act(() => {
      client.emit(
        streamEvent({
          type: "done",
          turn_id: "t1",
          metadata: {
            status: "completed",
            user_message_id: 101,
            assistant_message_id: 202,
          },
        }),
      );
    });
    expect(chat.state.isStreaming).toBe(false);
    // Optimistic ids are swapped for the persisted ids carried on `done`…
    expect(chat.state.messages[0].id).toBe(101);
    expect(chat.state.messages[1].id).toBe(202);
    // …and the finished message keeps a settled trace address.
    expect(chat.state.messages[1].trace?.turn_id).toBe("t1");
  });

  it("takes a retracted round back out of the answer text", () => {
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({
          type: "content",
          content: "Let me check. ",
          turn_id: "t2",
          metadata: { call_id: "c1", call_kind: "agent_loop_round" },
        }),
      );
      client.emit(
        streamEvent({
          type: "tool_call",
          turn_id: "t2",
          metadata: { call_id: "c1" },
        }),
      );
    });
    expect(chat.state.messages[1].content).toBe("Let me check. ");

    // A finish guard retracts the round: its streamed text leaves the
    // answer (and stays in the trace).
    act(() => {
      client.emit(
        streamEvent({
          type: "tool_result",
          turn_id: "t2",
          metadata: {
            trace_kind: "call_status",
            call_state: "complete",
            answer_visible: false,
            call_id: "c1",
          },
        }),
      );
    });
    expect(chat.state.messages[1].content).toBe("");

    act(() => {
      client.emit(
        streamEvent({
          type: "content",
          content: "Final answer",
          turn_id: "t2",
          metadata: { call_id: "c2", call_kind: "llm_final_response" },
        }),
      );
    });
    expect(chat.state.messages[1]).toMatchObject({
      content: "Final answer",
      rawContent: "Final answer",
    });
  });

  it("binds a draft to its server session id mid-stream and keeps streaming", () => {
    renderAdapter();
    const client = startTurn();
    expect(chat.state.sessionId).toBeNull();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-77", turn_id: "t3" }),
      );
    });
    expect(chat.state.sessionId).toBe("s-77");

    // Events after the rename land in the bound session, not a fresh draft.
    act(() => {
      client.emit(
        streamEvent({ type: "content", content: "bound", turn_id: "t3" }),
      );
    });
    expect(chat.state.messages).toHaveLength(2);
    expect(chat.state.messages[1].content).toBe("bound");
  });

  it("holds the socket for post-done meta, then disconnects after the grace window", () => {
    vi.useFakeTimers();
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-title", turn_id: "t4" }),
      );
    });
    const tokenAfterBind = chat.sidebarRefreshToken;

    act(() => {
      client.emit(
        streamEvent({
          type: "done",
          turn_id: "t4",
          metadata: {
            status: "completed",
            user_message_id: 11,
            assistant_message_id: 12,
          },
        }),
      );
    });
    expect(chat.state.isStreaming).toBe(false);
    // STREAM_END itself refreshes the sidebar once.
    expect(chat.sidebarRefreshToken).toBe(tokenAfterBind + 1);

    // The title-refresh window lands before the disconnect grace window.
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(chat.sidebarRefreshToken).toBe(tokenAfterBind + 2);
    expect(client.disconnectCalls).toBe(0);

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(client.disconnectCalls).toBe(1);
  });
});

describe("ChatStateAdapter terminal errors and connection loss", () => {
  it("marks the turn failed on a terminal error event", () => {
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-err", turn_id: "t5" }),
      );
      client.emit(
        streamEvent({
          type: "content",
          content: "partial before failure",
          turn_id: "t5",
        }),
      );
    });
    expect(chat.sessionStatuses["s-err"]).toMatchObject({ status: "running" });

    act(() => {
      client.emit(
        streamEvent({
          type: "error",
          turn_id: "t5",
          metadata: { turn_terminal: true, reason: "upstream_error" },
        }),
      );
    });
    expect(chat.state.isStreaming).toBe(false);
    // The failed session leaves the live-status map the surface watches.
    expect(chat.sessionStatuses["s-err"]).toBeUndefined();
    // The partial answer stays on screen; nothing is rolled back.
    expect(chat.state.messages[1].content).toBe("partial before failure");
    expect(vi.mocked(notify)).not.toHaveBeenCalled();
  });

  it("toasts and fails the turn when the socket drops mid-stream", () => {
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "content", content: "half an answer", turn_id: "t6" }),
      );
    });
    act(() => {
      client.drop();
    });

    expect(chat.state.isStreaming).toBe(false);
    expect(chat.state.messages[1].content).toBe("half an answer");
    // The failure is stamped onto the trailing row as a terminal error
    // event — the banner/state a surface renders for a dead turn.
    const errorEvent = (chat.state.messages[1].events ?? []).find(
      (e) => e.type === "error",
    );
    expect(errorEvent?.metadata).toMatchObject({ turn_terminal: true });
    expect(vi.mocked(notify)).toHaveBeenCalledWith(
      "Connection lost while generating. Please retry your message.",
      expect.objectContaining({ tone: "error" }),
    );
  });

  it("keeps a live turn with a pending ask_user card when the socket drops", () => {
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-ask", turn_id: "t7" }),
      );
      client.emit(
        streamEvent({
          type: "tool_result",
          turn_id: "t7",
          metadata: {
            tool_call_id: "call-1",
            tool_metadata: {
              ask_user: { questions: [{ id: "q1", prompt: "Continue?" }] },
            },
          },
        }),
      );
    });

    act(() => {
      client.drop();
    });

    // The card pauses the turn: a drop must not fail it out from under the
    // pending question, and no toast may fire.
    expect(chat.state.isStreaming).toBe(true);
    expect(vi.mocked(notify)).not.toHaveBeenCalled();
  });
});

describe("ChatStateAdapter regenerate rollback", () => {
  it("restores the popped reply when the server rejects the regenerate", () => {
    renderAdapter();
    const client = startTurn("First question");

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-regen", turn_id: "t8" }),
      );
      client.emit(
        streamEvent({
          type: "content",
          content: "First answer",
          turn_id: "t8",
        }),
      );
      client.emit(
        streamEvent({
          type: "done",
          turn_id: "t8",
          metadata: {
            status: "completed",
            user_message_id: 301,
            assistant_message_id: 302,
          },
        }),
      );
    });
    expect(chat.state.messages.map((m) => m.id)).toEqual([301, 302]);

    act(() => {
      chat.regenerateLastMessage();
    });
    expect(chat.state.isStreaming).toBe(true);
    expect(chat.state.messages[1]).toMatchObject({ role: "assistant", content: "" });
    // `done` retired the turn's runner, so the regenerate opens a fresh
    // connection instead of reusing the old socket.
    const regenClient = transport.last();
    expect(regenClient).not.toBe(client);
    expect(regenClient.sent.at(-1)).toMatchObject({
      type: "regenerate",
      session_id: "s-regen",
    });

    act(() => {
      regenClient.emit(
        streamEvent({
          type: "error",
          turn_id: "t8b",
          metadata: { turn_terminal: true, reason: "regenerate_busy" },
        }),
      );
    });
    expect(chat.state.isStreaming).toBe(false);
    // The empty placeholder is dropped and the original reply is restored.
    expect(chat.state.messages.map((m) => m.id)).toEqual([301, 302]);
    expect(chat.state.messages[1].content).toBe("First answer");
  });
});

describe("ChatStateAdapter reconnect paths", () => {
  it("retries start_turn until the socket connects", () => {
    vi.useFakeTimers();
    transport.setUnreachable(true);
    renderAdapter();
    const client = startTurn();
    expect(client.sent).toHaveLength(0);
    expect(chat.state.isStreaming).toBe(true);

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(client.sent).toHaveLength(0);

    transport.setUnreachable(false);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(client.sent).toHaveLength(1);
    expect(client.sent[0]).toMatchObject({ type: "start_turn" });
    expect(chat.state.isStreaming).toBe(true);
    expect(vi.mocked(notify)).not.toHaveBeenCalled();
  });

  it("gives up after the retry ladder and reports the outage", () => {
    vi.useFakeTimers();
    transport.setUnreachable(true);
    renderAdapter();
    const client = startTurn();

    act(() => {
      vi.advanceTimersByTime(2_500);
    });

    expect(client.sent).toHaveLength(0);
    expect(chat.state.isStreaming).toBe(false);
    // The empty placeholder is dropped and the optimistic user row is
    // flagged as an unsent submission instead of a failed reply.
    expect(chat.state.messages).toHaveLength(1);
    expect(chat.state.messages[0]).toMatchObject({
      role: "user",
      content: "Hello there",
      failedSubmission: true,
    });
    expect(vi.mocked(notify)).toHaveBeenCalledWith(
      "Couldn't reach the server. Please check your connection and retry.",
      expect.objectContaining({ tone: "error" }),
    );
  });

  it("resubscribes from the last sequence when a streaming turn goes quiet", () => {
    vi.useFakeTimers();
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-idle", turn_id: "t9" }),
      );
      client.emit(
        streamEvent({ type: "content", content: "a", turn_id: "t9" }),
      );
      client.emit(
        streamEvent({ type: "content", content: "b", turn_id: "t9" }),
      );
    });

    // Past the idle window (default 180s) the watchdog resubscribes from the
    // last received sequence instead of failing the turn. Advance one tick
    // past the window per act block: each block lets React commit the
    // watchdog's touch before the next tick reads updatedAt.
    act(() => {
      vi.advanceTimersByTime(190_000);
    });
    const resumes = client.sent.filter((m) => m.type === "resume_from");
    expect(resumes).toHaveLength(1);
    // lastSeq counts every event of the turn, including the `session` bind.
    expect(resumes[0]).toMatchObject({ turn_id: "t9", seq: 3 });
    expect(chat.state.isStreaming).toBe(true);

    // The touch after resubscribing suppresses repeat resumes on later ticks.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(client.sent.filter((m) => m.type === "resume_from")).toHaveLength(1);
  });

  it("does not resubscribe a paused ask_user turn", () => {
    vi.useFakeTimers();
    renderAdapter();
    const client = startTurn();

    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-park", turn_id: "t10" }),
      );
      client.emit(
        streamEvent({
          type: "tool_result",
          turn_id: "t10",
          metadata: {
            tool_call_id: "call-2",
            tool_metadata: {
              ask_user: { questions: [{ id: "q2", prompt: "Which one?" }] },
            },
          },
        }),
      );
    });

    act(() => {
      vi.advanceTimersByTime(200_000);
    });
    expect(client.sent.filter((m) => m.type === "resume_from")).toHaveLength(0);
    expect(chat.state.isStreaming).toBe(true);
  });

  it("subscribes to a live server turn when loading a running session", async () => {
    sessionApi.getSession.mockResolvedValue({
      id: "s-live",
      session_id: "s-live",
      title: "Live session",
      created_at: 1,
      updated_at: Math.floor(Date.now() / 1000),
      status: "running",
      messages: [
        {
          id: 21,
          session_id: "s-live",
          role: "user",
          content: "Question?",
          events: [],
          attachments: [],
        },
        {
          id: 22,
          session_id: "s-live",
          role: "assistant",
          content: "Answer!",
          events: [],
          attachments: [],
        },
      ],
      active_turns: [{ turn_id: "turn-live" }],
    });

    const api = renderAdapter();
    await act(async () => {
      await chat.loadSession("s-live");
    });

    expect(chat.state.sessionId).toBe("s-live");
    expect(chat.state.isStreaming).toBe(true);
    expect(chat.state.messages).toHaveLength(2);
    expect(chat.state.messages[1].content).toBe("Answer!");
    expect(transport.last().sent[0]).toMatchObject({
      type: "subscribe_turn",
      turn_id: "turn-live",
      after_seq: 0,
    });
  });

  it("drops a revalidation snapshot when the session went live locally", async () => {
    renderAdapter();
    const client = startTurn();
    act(() => {
      client.emit(
        streamEvent({ type: "session", session_id: "s-duel", turn_id: "t11" }),
      );
    });
    expect(chat.state.messages).toHaveLength(2);

    sessionApi.getSession.mockResolvedValue({
      id: "s-duel",
      session_id: "s-duel",
      title: "Stale snapshot",
      created_at: 1,
      updated_at: Math.floor(Date.now() / 1000),
      status: "idle",
      messages: [
        {
          id: 31,
          session_id: "s-duel",
          role: "user",
          content: "old row",
          events: [],
          attachments: [],
        },
      ],
    });

    await act(async () => {
      await chat.loadSession("s-duel", { revalidate: true });
    });

    // The streaming local state must survive the background snapshot.
    expect(chat.state.messages).toHaveLength(2);
    expect(chat.state.messages[1].role).toBe("assistant");
    expect(chat.state.isStreaming).toBe(true);
    expect(client.sent.filter((m) => m.type === "subscribe_turn")).toHaveLength(
      0,
    );
  });
});
