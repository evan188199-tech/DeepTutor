import { useEffect, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { initI18n } from "@/i18n/init";

initI18n("en");

const transport = vi.hoisted(() => {
  type MockEvent = Record<string, unknown>;
  type EventListener = (event: MockEvent) => void;
  const instances: MockUnifiedTurnClient[] = [];
  // Per-test knobs. The default reproduces #1278's original fix: a socket
  // that is connected the moment connect() returns. Flip them to expose
  // the races the sync mock was hiding.
  const knobs = {
    // connect() only raises `connected` after this delay (0 = sync).
    connectDelayMs: 0,
    // Emit ask_user_resolved before done, i.e. the card was answered.
    resolveCard: false,
  };

  class MockUnifiedTurnClient {
    connected = false;
    submitted: Array<Record<string, unknown>> = [];

    constructor(
      private readonly onEvent: EventListener,
      private readonly onClose?: () => void,
    ) {
      instances.push(this);
    }

    connect(): void {
      if (knobs.connectDelayMs <= 0) {
        this.connected = true;
        return;
      }
      window.setTimeout(() => {
        this.connected = true;
      }, knobs.connectDelayMs);
    }

    setResumeState(): void {}

    disconnect(): void {
      this.connected = false;
      this.onClose?.();
    }

    send(message: Record<string, unknown>): void {
      if (message.type !== "start_turn") return;
      window.setTimeout(() => {
        this.onEvent({
          type: "tool_result",
          source: "chat",
          stage: "responding",
          content: "",
          metadata: {
            tool_call_id: "call-1273",
            tool_metadata: {
              ask_user: {
                questions: [{ id: "source", prompt: "Which source?" }],
              },
            },
          },
          turn_id: "turn-1273",
          seq: 1,
          timestamp: Date.now() / 1000,
        });
      }, 0);
      if (knobs.resolveCard) {
        window.setTimeout(() => {
          this.onEvent({
            type: "progress",
            source: "chat",
            stage: "responding",
            content: "",
            metadata: {
              ask_user_resolved: true,
              ask_user_tool_call_id: "call-1273",
            },
            turn_id: "turn-1273",
            seq: 2,
            timestamp: Date.now() / 1000,
          });
        }, 0);
      }
      window.setTimeout(() => {
        this.onEvent({
          type: "done",
          source: "chat",
          stage: "responding",
          content: "",
          metadata: { status: "completed" },
          turn_id: "turn-1273",
          seq: 3,
          timestamp: Date.now() / 1000,
        });
      }, 0);
    }

    sendAwaitingAck(message: Record<string, unknown>): Promise<boolean> {
      this.submitted.push(message);
      return Promise.resolve(true);
    }
  }

  return { MockUnifiedTurnClient, instances, knobs, reset: () => instances.splice(0) };
});

vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: transport.MockUnifiedTurnClient,
}));

function Harness() {
  const chat = useChatStateAdapter();
  const [submitResult, setSubmitResult] = useState<boolean | null>(null);

  useEffect(() => {
    chat.newSession();
    // Only initialize the draft once; the provider owns subsequent state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <span data-testid="streaming">{String(chat.state.isStreaming)}</span>
      <span data-testid="submit-result">{String(submitResult)}</span>
      <button type="button" onClick={() => chat.sendMessage("hello")}>
        Start turn
      </button>
      <button
        type="button"
        onClick={() => {
          void chat
            .submitUserReply({
              text: "Knowledge center",
              answers: [{ questionId: "source", text: "Knowledge center" }],
            })
            .then(setSubmitResult);
        }}
      >
        Submit answer
      </button>
    </div>
  );
}

describe("ask_user terminal turn state", () => {
  beforeEach(() => {
    transport.knobs.connectDelayMs = 0;
    transport.knobs.resolveCard = false;
    transport.reset();
  });

  it("keeps the pending card addressable after a completed turn", async () => {
    const user = userEvent.setup();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Start turn" }));
    await waitFor(() =>
      expect(screen.getByTestId("streaming")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await waitFor(() => {
      const client = transport.instances.at(-1);
      expect(client?.submitted.at(-1)).toMatchObject({
        type: "submit_user_reply",
        turn_id: "turn-1273",
        text: "Knowledge center",
      });
    });
  });

  it("submits a pending card after a completed turn when the socket connects asynchronously", async () => {
    // The completed turn's runner is already gone, so submitUserReply opens
    // a fresh socket. connect() only becomes true 50ms later, past the
    // first 200ms retry — the send-retry guard must not eat the frame
    // just because the turn itself is over (#1278 regression, #1359).
    transport.knobs.connectDelayMs = 50;
    const user = userEvent.setup();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Start turn" }));
    await waitFor(() =>
      expect(screen.getByTestId("streaming")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await waitFor(() => {
      const client = transport.instances.at(-1);
      expect(client?.submitted.at(-1)).toMatchObject({
        type: "submit_user_reply",
        turn_id: "turn-1273",
      });
    });
    await waitFor(() =>
      expect(screen.getByTestId("submit-result")).toHaveTextContent("true"),
    );
  });

  it("refuses to submit once the card is answered after the turn ends", async () => {
    transport.knobs.resolveCard = true;
    const user = userEvent.setup();
    render(
      <ChatStateAdapterProvider>
        <Harness />
      </ChatStateAdapterProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Start turn" }));
    await waitFor(() =>
      expect(screen.getByTestId("streaming")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await waitFor(() =>
      expect(screen.getByTestId("submit-result")).toHaveTextContent("false"),
    );
    // Leave enough time for a rogue retry ladder (200ms per attempt) to
    // fire — an answered card must never emit a submit_user_reply frame.
    await new Promise((resolve) => window.setTimeout(resolve, 600));
    expect(transport.instances.every((c) => c.submitted.length === 0)).toBe(
      true,
    );
  });
});
