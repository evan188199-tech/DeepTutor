import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PartnerChat from "@/components/partners/PartnerChat";

interface MockComposerProps {
  onSend: (content: string, attachments: []) => boolean | "handled";
  restoreDraft?: { id: number; content: string; attachments: unknown[] };
  disabled?: boolean;
}

const api = vi.hoisted(() => ({
  historyPage: vi.fn(),
  sessions: vi.fn(),
  commands: vi.fn(),
}));
const translate = vi.hoisted(() => (key: string) => key);
const composer = vi.hoisted(() => ({ current: null as MockComposerProps | null }));
const sockets = vi.hoisted(() => ({
  instances: [] as Array<{
    disconnect: () => void;
    emit: (frame: Record<string, unknown>) => void;
    messages: string[];
  }>,
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@/lib/partners-api", () => ({
  getPartnerHistoryPage: api.historyPage,
  getPartnerSessions: api.sessions,
  getPartnerCommands: api.commands,
}));
vi.mock("@/lib/reconnecting-websocket", () => {
  class MockSocket {
    connected = true;
    messages: string[] = [];
    constructor(
      _url: string,
      private handlers: {
        onOpen: () => void;
        onMessage: (event: MessageEvent) => void;
        onDisconnect: () => void;
      },
    ) {
      sockets.instances.push(this);
    }
    start() {
      this.handlers.onOpen();
      this.emit({ type: "ready" });
    }
    send(payload: string) {
      this.messages.push(payload);
      return true;
    }
    stop() {}
    wake() {}
    emit(frame: Record<string, unknown>) {
      this.handlers.onMessage({ data: JSON.stringify(frame) } as MessageEvent);
    }
    disconnect() {
      this.handlers.onDisconnect();
    }
  }
  return { ReconnectingWebSocket: MockSocket };
});
vi.mock("@/components/partners/PartnerComposer", () => ({
  PartnerComposer: (props: MockComposerProps) => {
    composer.current = props;
    return <div data-testid="composer" />;
  },
}));
vi.mock("@/components/partners/PartnerAvatar", () => ({
  default: () => <div data-testid="avatar" />,
}));
vi.mock("@/features/chat/trace", () => ({ AssistantActivity: () => null }));
vi.mock("next/dynamic", () => ({
  default: () => ({ content }: { content: string }) => <span>{content}</span>,
}));
vi.mock("@/hooks/useChatAutoScroll", async () => {
  const React = await import("react");
  return {
    useChatAutoScroll: () => ({
      containerRef: React.useRef<HTMLDivElement>(null),
      shouldAutoScrollRef: React.useRef(true),
      scrollToBottom: React.useCallback(() => {}, []),
      handleScroll: React.useCallback(() => {}, []),
    }),
  };
});

const initialPage = {
  messages: [{ role: "assistant", content: "Earlier answer" }],
  start: 0,
  total: 1,
  next_before: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  sockets.instances.length = 0;
  composer.current = null;
  api.historyPage.mockResolvedValue(initialPage);
  api.sessions.mockResolvedValue([]);
  api.commands.mockResolvedValue([]);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

async function ready() {
  await waitFor(() => expect(composer.current?.disabled).toBe(false));
  return sockets.instances[0];
}

function sendOrphanQuestion() {
  act(() => {
    expect(composer.current?.onSend("Orphan question", [])).toBe(true);
  });
}

it("clears a pending attach_busy retry timer when the chat unmounts", async () => {
  const view = render(
    <PartnerChat partnerId="ada" partnerName="Ada" sessionKey="web-current" />,
  );
  const socket = await ready();
  sendOrphanQuestion();
  act(() => socket.disconnect());
  vi.useFakeTimers();
  try {
    act(() => socket.emit({ type: "attach_busy", session_key: "web-current" }));
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(2_000));
    expect(
      socket.messages.filter((payload) => payload.includes('"attach"')),
    ).toHaveLength(1);
    expect(sockets.instances).toHaveLength(1);
  } finally {
    vi.useRealTimers();
  }
});

it("clears a pending attach_idle retry timer when the chat unmounts", async () => {
  api.historyPage
    .mockResolvedValueOnce(initialPage)
    .mockRejectedValueOnce(new Error("history unavailable"));
  const view = render(
    <PartnerChat partnerId="ada" partnerName="Ada" sessionKey="web-current" />,
  );
  const socket = await ready();
  sendOrphanQuestion();
  act(() => socket.disconnect());
  vi.useFakeTimers();
  try {
    act(() => socket.emit({ type: "attach_idle", session_key: "web-current" }));
    await act(async () => {});
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(2_000));
    expect(
      socket.messages.filter((payload) => payload.includes('"attach"')),
    ).toHaveLength(1);
    expect(sockets.instances).toHaveLength(1);
  } finally {
    vi.useRealTimers();
  }
});
