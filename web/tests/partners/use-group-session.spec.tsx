import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useGroupSession } from "@/components/partners/group/useGroupSession";
import type { Round, Seat } from "@/components/partners/group/useGroupSession";
import type { StreamEvent } from "@/features/chat/model/protocol";
import type {
  PartnerGroup,
  PartnerGroupMessage,
  PartnerInvocation,
} from "@/lib/partner-groups-api";

/**
 * Behavior tests for the Partner Group session hook.
 *
 * The wire side is fully stubbed: the browser WebSocket global is replaced
 * with a controllable fake, so frames are injected through callbacks and the
 * reconnect backoff is driven by fake timers — nothing touches a network.
 * `lib/stream` stays real on purpose: the optimistic body growth (append,
 * retraction recompute) is part of the state machine under test.
 */

const SESSION = "s1";
const NOW = "2026-10-09T08:00:00.000Z";
const WS_OPEN = 1;
const WS_CLOSED = 3;

const harness = vi.hoisted(() => ({
  historyCalls: [] as Array<{
    groupId: string;
    sessionKey: string;
    resolve: (history: never[]) => void;
    reject: (error: unknown) => void;
  }>,
}));

vi.mock("@/lib/api", () => ({
  wsUrl: (path: string) => `ws://stub.local${path}`,
}));

vi.mock("@/lib/partner-groups-api", () => ({
  getPartnerGroupHistory: (groupId: string, sessionKey: string) =>
    new Promise((resolve, reject) => {
      harness.historyCalls.push({
        groupId,
        sessionKey,
        resolve: resolve as (history: never[]) => void,
        reject,
      });
    }),
}));

function invoke<T>(fn: () => T): T {
  let value!: T;
  act(() => {
    value = fn();
  });
  return value;
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  failNextSend = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((error: unknown) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string): void {
    if (this.failNextSend) {
      this.failNextSend = false;
      throw new Error("stub send failure");
    }
    this.sent.push(payload);
  }

  close(): void {
    if (this.readyState > WS_OPEN) return;
    this.readyState = WS_CLOSED;
    this.onclose?.();
  }

  serverOpen(): void {
    act(() => {
      this.readyState = WS_OPEN;
      this.onopen?.();
    });
  }

  serverMessage(frame: unknown): void {
    act(() => {
      this.onmessage?.({ data: JSON.stringify(frame) });
    });
  }

  serverRawMessage(data: string): void {
    act(() => {
      this.onmessage?.({ data });
    });
  }

  serverError(): void {
    act(() => {
      this.onerror?.(new Error("stub socket error"));
    });
  }

  serverClose(): void {
    act(() => {
      this.close();
    });
  }

  sentFrames(): Array<Record<string, unknown>> {
    return this.sent.map((raw) => JSON.parse(raw) as Record<string, unknown>);
  }

  framesWithAction(action: string): Array<Record<string, unknown>> {
    return this.sentFrames().filter((frame) => frame.action === action);
  }
}

function makeGroup(overrides: Partial<PartnerGroup> = {}): PartnerGroup {
  return {
    group_id: "group-1",
    owner_id: "owner-1",
    name: "Panel",
    description: "",
    member_ids: ["pa", "pb", "pc"],
    members: [],
    discussion_mode: "panel_parallel",
    shared_memory: "whiteboard",
    emoji: "🧪",
    color: "#123456",
    created_at: NOW,
    updated_at: NOW,
    version: 1,
    ...overrides,
  };
}

let messageSeq = 0;

function makeMessage(
  overrides: Partial<PartnerGroupMessage> = {},
): PartnerGroupMessage {
  messageSeq += 1;
  return {
    event_id: `event-${messageSeq}`,
    turn_id: "turn-1",
    session_key: SESSION,
    role: "partner",
    content: "answer",
    author_id: "pa",
    author_name: "A",
    created_at: NOW,
    mentions: [],
    error: false,
    kind: "message",
    events: [],
    invocation_id: "",
    invocation: null,
    ...overrides,
  };
}

function makeInvocation(
  overrides: Partial<PartnerInvocation> = {},
): PartnerInvocation {
  return {
    invocation_id: "inv-x",
    group_id: "group-1",
    session_key: SESSION,
    parent_turn_id: "turn-1",
    requester_partner_id: "pa",
    requester_partner_name: "A",
    target_partner_id: "pb",
    target_partner_name: "B",
    question: "why?",
    status: "pending",
    created_at: NOW,
    updated_at: NOW,
    question_event_id: "",
    reply_event_id: "",
    error: "",
    ...overrides,
  };
}

function contentEvent(text: string, callId?: string): StreamEvent {
  return {
    type: "content",
    content: text,
    metadata: callId
      ? { call_id: callId, call_kind: "agent_loop_round" }
      : {},
    source: "partner",
    stage: "answer",
    timestamp: Date.parse(NOW),
  };
}

function retractionMarker(callId: string): StreamEvent {
  return {
    type: "stage_end",
    content: "",
    metadata: {
      trace_kind: "call_status",
      call_state: "complete",
      answer_visible: false,
      call_id: callId,
    },
    source: "capability",
    stage: "answer",
    timestamp: Date.parse(NOW),
  };
}

function renderSession(group = makeGroup(), sessionKey = SESSION) {
  return renderHook(
    (props: { group: PartnerGroup; sessionKey: string }) =>
      useGroupSession(props.group, props.sessionKey),
    { initialProps: { group, sessionKey } },
  );
}

async function resolveHistory(
  index: number,
  history: PartnerGroupMessage[],
): Promise<void> {
  await act(async () => {
    harness.historyCalls[index].resolve(history as never[]);
  });
}

function seatOf(round: Round | undefined, partnerId: string): Seat | undefined {
  return round?.seats.find((seat) => seat.partnerId === partnerId);
}

function seatIds(round: Round | undefined): string[] {
  return round ? round.seats.map((seat) => seat.partnerId) : [];
}

async function openReadySession(history: PartnerGroupMessage[] = []) {
  const rendered = renderSession();
  const socket = FakeWebSocket.instances[0];
  socket.serverOpen();
  await resolveHistory(0, history);
  return { ...rendered, socket };
}

function userFrame(
  turnId: string,
  mentions: string[],
): Record<string, unknown> {
  return {
    type: "user_message",
    message: makeMessage({
      role: "user",
      author_id: "owner-1",
      turn_id: turnId,
      mentions,
    }),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  harness.historyCalls = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("history load", () => {
  it("starts loading, lands history, then attaches once connected", async () => {
    const { result } = renderSession();
    expect(result.current.loading).toBe(true);
    expect(harness.historyCalls[0]).toMatchObject({
      groupId: "group-1",
      sessionKey: SESSION,
    });

    const socket = FakeWebSocket.instances[0];
    socket.serverOpen();
    expect(result.current.connected).toBe(true);
    // Opening before the history lands must not attach yet.
    expect(socket.framesWithAction("attach")).toHaveLength(0);

    await resolveHistory(0, [
      makeMessage({ role: "user", author_id: "owner-1", content: "hi" }),
    ]);
    expect(result.current.loading).toBe(false);
    expect(result.current.messages).toHaveLength(1);
    expect(socket.framesWithAction("attach")).toEqual([
      { action: "attach", session_key: SESSION },
    ]);
  });

  it("a history failure still finishes loading with an empty transcript", async () => {
    const { result } = renderSession();
    await act(async () => {
      harness.historyCalls[0].reject(new Error("offline"));
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBe("");
    expect(result.current.running).toBe(false);
  });

  it("switching threads retires the live turn and reloads on a fresh socket", async () => {
    const { result, rerender } = renderSession();
    const first = FakeWebSocket.instances[0];
    first.serverOpen();
    await resolveHistory(0, []);
    first.serverMessage({
      type: "user_message",
      message: makeMessage({ role: "user", author_id: "owner-1" }),
    });
    expect(result.current.running).toBe(true);

    rerender({ group: makeGroup(), sessionKey: "s2" });
    expect(result.current.running).toBe(false);
    expect(result.current.loading).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);

    FakeWebSocket.instances[1].serverOpen();
    await resolveHistory(1, []);
    expect(result.current.loading).toBe(false);
    expect(FakeWebSocket.instances[1].framesWithAction("attach")).toEqual([
      { action: "attach", session_key: "s2" },
    ]);
  });

  it("switching groups rebuilds the socket for the new group url", async () => {
    const { rerender } = renderSession();
    expect(FakeWebSocket.instances[0].url).toBe(
      `ws://stub.local/ws/partner-groups/group-1`,
    );
    rerender({ group: makeGroup({ group_id: "group-2" }), sessionKey: SESSION });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toBe(
      `ws://stub.local/ws/partner-groups/group-2`,
    );
  });

  it("roster edits keep the socket open and reach new rounds through it", async () => {
    const { result, rerender } = await openReadySession();
    const socket = FakeWebSocket.instances[0];
    rerender({
      group: makeGroup({ member_ids: ["pa", "pb", "pc", "pd"] }),
      sessionKey: SESSION,
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    socket.serverMessage({
      type: "user_message",
      message: makeMessage({
        role: "user",
        author_id: "owner-1",
        mentions: [],
      }),
    });
    const round = result.current.rounds[0];
    // No explicit mentions: the whole (updated) roster becomes the round's seats.
    expect(seatIds(round)).toEqual(["pa", "pb", "pc", "pd"]);
    expect(result.current.progress).toEqual({ done: 0, total: 4, clash: false });
  });
});

describe("panel round lifecycle", () => {
  it("a user message opens a live round with member-ordered seats", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pc", "pa"]));

    expect(result.current.running).toBe(true);
    expect(result.current.error).toBe("");
    expect(result.current.messages).toHaveLength(1);
    const round = result.current.rounds[0];
    expect(round?.live).toBe(true);
    expect(round?.turnId).toBe("turn-1");
    expect(round?.followup).toBe(false);
    // Arrival order (pc first) must not win; member order does.
    expect(seatIds(round)).toEqual(["pa", "pc"]);
    expect(round?.seats.every((seat) => seat.status === "waiting")).toBe(true);
    expect(result.current.progress).toEqual({ done: 0, total: 2, clash: false });
  });

  it("traces grow the speaker's optimistic body, non-content events do not", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.serverMessage({ type: "partner_started", partner_id: "pa" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: contentEvent("He"),
    });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: contentEvent("llo", "call-1"),
    });

    const seat = seatOf(result.current.rounds[0], "pa");
    expect(seat?.status).toBe("working");
    expect(seat?.streamed).toBe("Hello");
    expect(seat?.events).toHaveLength(2);

    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: {
        type: "thinking",
        content: "hmm",
        metadata: {},
        source: "partner",
        stage: "answer",
        timestamp: Date.parse(NOW),
      },
    });
    expect(seatOf(result.current.rounds[0], "pa")?.streamed).toBe("Hello");
  });

  it("a retraction marker recomputes the body without the retracted round", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.serverMessage({ type: "partner_started", partner_id: "pa" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: contentEvent("He"),
    });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: contentEvent("llo", "call-1"),
    });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: contentEvent("!", "call-2"),
    });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-1",
      partner_id: "pa",
      event: retractionMarker("call-1"),
    });

    expect(seatOf(result.current.rounds[0], "pa")?.streamed).toBe("He!");
  });

  it("a partner message dedupes by event id and retires the seat", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa", "pb"]));
    const final = makeMessage({ author_id: "pa", content: "final" });
    socket.serverMessage({ type: "partner_message", message: final });
    socket.serverMessage({ type: "partner_message", message: final });

    expect(result.current.messages).toHaveLength(2);
    // The live seat retired; the authoritative message took its place.
    expect(
      result.current.rounds[0]?.seats.some(
        (seat) => seat.partnerId === "pa" && !seat.message,
      ),
    ).toBe(false);
    expect(seatOf(result.current.rounds[0], "pa")?.status).toBe("done");
    expect(seatOf(result.current.rounds[0], "pa")?.message?.event_id).toBe(
      final.event_id,
    );
    expect(result.current.progress).toEqual({ done: 1, total: 2, clash: false });

    socket.serverMessage({ type: "done" });
    expect(result.current.running).toBe(false);
    expect(result.current.progress).toBeNull();
  });

  it("an error frame clears the live turn, reports, and can be dismissed", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.serverMessage({ type: "error", content: "boom" });

    expect(result.current.running).toBe(false);
    expect(result.current.error).toBe("boom");
    expect(result.current.progress).toBeNull();
    invoke(() => result.current.setError(""));
    expect(result.current.error).toBe("");
  });

  it("a cancelled frame ends the round without an error", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.serverMessage({ type: "cancelled", content: "stopped" });
    expect(result.current.running).toBe(false);
    expect(result.current.error).toBe("");
  });

  it("a malformed frame does not tear down the session", async () => {
    const { result, socket } = await openReadySession();
    expect(() => socket.serverRawMessage("not json at all")).not.toThrow();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    expect(result.current.running).toBe(true);
    expect(result.current.messages).toHaveLength(1);
  });

  it("a late joiner extends the targets and sorts after known members", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.serverMessage({ type: "partner_started", partner_id: "pd" });

    const round = result.current.rounds[0];
    expect(seatIds(round)).toEqual(["pa", "pd"]);
    expect(result.current.progress).toEqual({ done: 0, total: 2, clash: false });
  });
});

describe("follow-up rounds", () => {
  it("a partner_started with an invocation opens a follow-up round without a user message", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage({
      type: "partner_started",
      partner_id: "pb",
      invocation_id: "inv-1",
    });

    expect(result.current.running).toBe(true);
    const round = result.current.rounds[0];
    expect(round?.followup).toBe(true);
    expect(round?.turnId).toBe("live");
    expect(seatIds(round)).toEqual(["pb"]);
    expect(seatOf(round, "pb")?.status).toBe("working");

    socket.serverMessage({
      type: "partner_trace",
      turn_id: "turn-9",
      partner_id: "pb",
      event: contentEvent("reply"),
    });
    expect(result.current.rounds[0]?.turnId).toBe("turn-9");
  });

  it("persisted invocation question/reply pairs render chronologically", async () => {
    const { result } = await openReadySession([
      makeMessage({ role: "user", author_id: "owner-1", turn_id: "turn-0" }),
      makeMessage({
        author_id: "pb",
        kind: "invocation_question",
        turn_id: "t-fq",
      }),
      makeMessage({
        author_id: "pa",
        kind: "invocation_reply",
        turn_id: "t-fq",
      }),
    ]);

    const round = result.current.rounds.find((item) => item.turnId === "t-fq");
    expect(round?.followup).toBe(true);
    // Follow-ups keep arrival order: pb asked, then pa answered.
    expect(seatIds(round)).toEqual(["pb", "pa"]);
  });

  it("historical messages without follow-up kinds stay panel rounds", async () => {
    const { result } = await openReadySession([
      makeMessage({ role: "user", author_id: "owner-1", turn_id: "t-old" }),
      makeMessage({ author_id: "pc", turn_id: "t-old" }),
      makeMessage({ author_id: "pa", turn_id: "t-old" }),
    ]);

    const round = result.current.rounds.find((item) => item.turnId === "t-old");
    expect(round?.followup).toBe(false);
    // Panel rounds sort by member order, not arrival order.
    expect(seatIds(round)).toEqual(["pa", "pc"]);
  });
});

describe("seat ordering and passes", () => {
  it("second-pass speakers rank after their first-pass messages", async () => {
    const { result, socket } = await openReadySession([
      makeMessage({
        role: "user",
        author_id: "owner-1",
        turn_id: "t-deb",
        mentions: ["pa", "pb"],
      }),
      makeMessage({ author_id: "pa", turn_id: "t-deb" }),
      makeMessage({ author_id: "pb", turn_id: "t-deb" }),
      makeMessage({
        author_id: "pa",
        kind: "debate_rebuttal",
        turn_id: "t-deb",
      }),
    ]);
    socket.serverMessage({ type: "partner_started", partner_id: "pa" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "t-deb",
      partner_id: "pa",
      event: contentEvent("second pass"),
    });

    const round = result.current.rounds.find((item) => item.turnId === "t-deb");
    expect(
      round?.seats.map(
        (seat) => `${seat.partnerId}:${seat.message?.kind ?? "live"}`,
      ),
    ).toEqual(["pa:message", "pb:message", "pa:debate_rebuttal", "pa:live"]);
  });

  it("a speaker's live seat keeps its slot while another's answer lands", async () => {
    const { result, socket } = await openReadySession([
      makeMessage({
        role: "user",
        author_id: "owner-1",
        turn_id: "t-deb",
        mentions: ["pa", "pb"],
      }),
      makeMessage({ author_id: "pa", turn_id: "t-deb" }),
      makeMessage({ author_id: "pb", turn_id: "t-deb" }),
    ]);
    socket.serverMessage({ type: "partner_started", partner_id: "pa" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "t-deb",
      partner_id: "pa",
      event: contentEvent("still thinking"),
    });

    const liveRound = result.current.rounds.find(
      (item) => item.turnId === "t-deb",
    );
    expect(seatIds(liveRound)).toEqual(["pa", "pb", "pa"]);

    socket.serverMessage({
      type: "partner_message",
      message: makeMessage({
        author_id: "pb",
        kind: "debate_rebuttal",
        turn_id: "t-deb",
        content: "pb second pass",
      }),
    });
    // The still-streaming seat keeps its slot (member order wins the
    // pass-rank tie); the landed answer appears after it, not before.
    expect(
      seatIds(
        result.current.rounds.find((item) => item.turnId === "t-deb"),
      ),
    ).toEqual(["pa", "pb", "pa", "pb"]);
  });

  it("progress flags a clash once every addressed partner has answered", async () => {
    const { result, socket } = await openReadySession([
      makeMessage({
        role: "user",
        author_id: "owner-1",
        turn_id: "t2",
        mentions: ["pa", "pb"],
      }),
      makeMessage({ author_id: "pa", turn_id: "t2" }),
      makeMessage({ author_id: "pb", turn_id: "t2" }),
    ]);
    expect(result.current.progress).toBeNull();

    socket.serverMessage({ type: "partner_started", partner_id: "pa" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "t2",
      partner_id: "pa",
      event: contentEvent("again"),
    });
    socket.serverMessage({ type: "partner_started", partner_id: "pb" });
    socket.serverMessage({
      type: "partner_trace",
      turn_id: "t2",
      partner_id: "pb",
      event: contentEvent("again too"),
    });

    expect(result.current.running).toBe(true);
    expect(result.current.progress).toEqual({ done: 0, total: 2, clash: true });
  });
});

describe("invocation actions", () => {
  it("approve sends once, parks in pending, and clears on the update", async () => {
    const { result, socket } = await openReadySession();
    expect(invoke(() => result.current.actOnInvocation("inv-1", "approve"))).toBe(
      true,
    );
    expect(result.current.pendingActions.has("inv-1")).toBe(true);
    expect(socket.framesWithAction("approve_invocation")).toEqual([
      {
        action: "approve_invocation",
        invocation_id: "inv-1",
        session_key: SESSION,
      },
    ]);
    expect(
      invoke(() => result.current.actOnInvocation("inv-1", "approve")),
    ).toBe(false);

    socket.serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({ invocation_id: "inv-1", status: "approved" }),
    });
    expect(result.current.pendingActions.has("inv-1")).toBe(false);
  });

  it("a failed send reverts the pending marker and drops the connection", async () => {
    const { result, socket } = await openReadySession();
    socket.failNextSend = true;
    expect(
      invoke(() => result.current.actOnInvocation("inv-2", "reject")),
    ).toBe(false);
    expect(result.current.pendingActions.has("inv-2")).toBe(false);
    expect(result.current.connected).toBe(false);
  });

  it("askPeer auto-approves exactly its own pending invocation", async () => {
    const { result, socket } = await openReadySession();
    expect(invoke(() => result.current.askPeer("pa", "pb", "why?"))).toBe(true);
    expect(socket.framesWithAction("create_invocation")).toEqual([
      {
        action: "create_invocation",
        session_key: SESSION,
        requester_partner_id: "pa",
        target_partner_id: "pb",
        question: "why?",
      },
    ]);

    socket.serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({
        invocation_id: "inv-9",
        status: "pending",
        requester_partner_id: "pa",
        target_partner_id: "pb",
      }),
    });
    expect(socket.framesWithAction("approve_invocation")).toEqual([
      {
        action: "approve_invocation",
        invocation_id: "inv-9",
        session_key: SESSION,
      },
    ]);
    expect(result.current.pendingActions.has("inv-9")).toBe(false);

    // The auto-run is consumed: the same pair pending again needs a click.
    socket.serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({
        invocation_id: "inv-11",
        status: "pending",
        requester_partner_id: "pa",
        target_partner_id: "pb",
      }),
    });
    socket.serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({
        invocation_id: "inv-12",
        status: "pending",
        requester_partner_id: "pb",
        target_partner_id: "pc",
      }),
    });
    expect(socket.framesWithAction("approve_invocation")).toHaveLength(1);
    expect(result.current.pendingActions.has("inv-11")).toBe(false);
    expect(result.current.pendingActions.has("inv-12")).toBe(false);
  });

  it("askPeer without a connection does not arm the auto-approval", async () => {
    const { result, socket } = await openReadySession();
    socket.serverClose();
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(invoke(() => result.current.askPeer("pa", "pb", "why?"))).toBe(
      false,
    );
    // The retry landed a new socket; even a matching pending invocation on it
    // must wait for a manual approval.
    const second = FakeWebSocket.instances[1];
    second.serverOpen();
    second.serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({
        invocation_id: "inv-20",
        status: "pending",
        requester_partner_id: "pa",
        target_partner_id: "pb",
      }),
    });
    expect(second.framesWithAction("approve_invocation")).toHaveLength(0);
  });

  it("an invocation update rewrites the matching persisted message", async () => {
    const { result } = await openReadySession([
      makeMessage({
        author_id: "pb",
        kind: "invocation_question",
        turn_id: "t-fq",
        invocation_id: "inv-7",
        invocation: null,
      }),
    ]);
    expect(result.current.messages[0]?.invocation).toBeNull();

    FakeWebSocket.instances[0].serverMessage({
      type: "invocation_updated",
      invocation: makeInvocation({
        invocation_id: "inv-7",
        status: "rejected",
      }),
    });
    expect(result.current.messages[0]?.invocation?.status).toBe("rejected");
  });
});

describe("cancel and stop", () => {
  it("cancel records the live round as stopped and the server confirms", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa", "pb"]));
    expect(invoke(() => result.current.cancel())).toBe(true);
    expect(socket.framesWithAction("cancel")).toEqual([
      { action: "cancel", session_key: SESSION },
    ]);
    expect(
      result.current.rounds.find((round) => round.turnId === "turn-1")?.stopped,
    ).toBe(true);
    expect(result.current.running).toBe(true);

    socket.serverMessage({ type: "cancelled" });
    expect(result.current.running).toBe(false);
  });

  it("cancel with no live round sends but marks nothing", async () => {
    const { result, socket } = await openReadySession();
    expect(invoke(() => result.current.cancel())).toBe(true);
    expect(result.current.rounds.some((round) => round.stopped)).toBe(false);
  });

  it("a failed cancel send does not record a stop", async () => {
    const { result, socket } = await openReadySession();
    socket.serverMessage(userFrame("turn-1", ["pa"]));
    socket.failNextSend = true;
    expect(invoke(() => result.current.cancel())).toBe(false);
    expect(
      result.current.rounds.find((round) => round.turnId === "turn-1")?.stopped,
    ).toBe(false);
  });

  it("a persisted round_stopped marker survives a reload", async () => {
    const { result } = await openReadySession([
      makeMessage({
        role: "user",
        author_id: "owner-1",
        turn_id: "t-stop",
      }),
      makeMessage({
        author_id: "pa",
        kind: "round_stopped",
        turn_id: "t-stop",
        content: "",
      }),
      makeMessage({ author_id: "pa", turn_id: "t-stop" }),
    ]);

    const round = result.current.rounds.find((item) => item.turnId === "t-stop");
    expect(round?.stopped).toBe(true);
    // The marker is metadata, not a speaker.
    expect(seatIds(round)).toEqual(["pa"]);
  });
});

describe("socket errors and retries", () => {
  it("a drop disables sending until the reconnect lands, then re-attaches", async () => {
    const { result, socket } = await openReadySession();
    socket.serverClose();
    expect(result.current.connected).toBe(false);
    expect(invoke(() => result.current.send("hi", null))).toBe(false);

    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    const second = FakeWebSocket.instances[1];
    expect(second).toBeDefined();
    second.serverOpen();
    expect(result.current.connected).toBe(true);
    expect(invoke(() => result.current.send("hi", null))).toBe(true);
    expect(second.framesWithAction("attach")).toEqual([
      { action: "attach", session_key: SESSION },
    ]);
  });

  it("reconnect backoff grows across attempts", async () => {
    renderSession();
    const first = FakeWebSocket.instances[0];
    first.serverClose();

    await act(async () => {
      vi.advanceTimersByTime(249);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    FakeWebSocket.instances[1].serverClose();
    await act(async () => {
      vi.advanceTimersByTime(499);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it("an error event marks the socket disconnected without tearing it down", async () => {
    const { result, socket } = await openReadySession();
    socket.serverError();
    expect(result.current.connected).toBe(false);
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("unmounting stops the socket and a late open cannot resurrect it", async () => {
    const { unmount } = renderSession();
    const socket = FakeWebSocket.instances[0];
    unmount();

    expect(() => socket.serverOpen()).not.toThrow();
    expect(socket.readyState).toBe(WS_CLOSED);
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe("outbound helpers", () => {
  it("send wraps content, session and mentions", async () => {
    const { result, socket } = await openReadySession();
    expect(invoke(() => result.current.send("hello", ["pb"]))).toBe(true);
    expect(socket.sentFrames().at(-1)).toEqual({
      content: "hello",
      session_key: SESSION,
      mentions: ["pb"],
    });
  });

  it("summarizeRound addresses one partner for one turn", async () => {
    const { result, socket } = await openReadySession();
    expect(invoke(() => result.current.summarizeRound("turn-1", "pc"))).toBe(
      true,
    );
    expect(socket.sentFrames().at(-1)).toEqual({
      action: "summarize_round",
      session_key: SESSION,
      turn_id: "turn-1",
      partner_id: "pc",
    });
  });

  it("consultation activity reports draft and presence state", async () => {
    const { result, socket } = await openReadySession();
    expect(() =>
      invoke(() => result.current.reportConsultationActivity(true, false)),
    ).not.toThrow();
    expect(socket.sentFrames().at(-1)).toEqual({
      action: "consultation_activity",
      session_key: SESSION,
      has_draft: true,
      active: false,
    });
  });

  it("every outbound helper is a no-op while disconnected", async () => {
    const { result, socket } = await openReadySession();
    const sentBefore = socket.sent.length;
    socket.serverClose();
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(invoke(() => result.current.send("hi", null))).toBe(false);
    expect(invoke(() => result.current.cancel())).toBe(false);
    expect(invoke(() => result.current.actOnInvocation("i", "approve"))).toBe(
      false,
    );
    expect(invoke(() => result.current.askPeer("pa", "pb", "q"))).toBe(false);
    expect(invoke(() => result.current.summarizeRound("t", "pa"))).toBe(false);
    expect(() =>
      invoke(() => result.current.reportConsultationActivity(true, true)),
    ).not.toThrow();
    expect(socket.sent).toHaveLength(sentBefore);
    expect(FakeWebSocket.instances[1]?.sent ?? []).toHaveLength(0);
  });
});
