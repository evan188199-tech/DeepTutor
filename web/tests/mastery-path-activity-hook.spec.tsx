import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMasteryPathActivity } from "@/hooks/useMasteryPathActivity";
import type { MasteryEvent } from "@/lib/learning-api";
import type { MasterySocketEnvelope } from "@/lib/mastery-ws";

const mocks = vi.hoisted(() => {
  class FakeMasteryTopicSocket {
    static instances: FakeMasteryTopicSocket[] = [];
    started = 0;
    stopped = 0;
    woken = 0;
    constructor(
      public pathId: string,
      public handlers: {
        onEnvelope?: (envelope: { type: string }) => void;
        onConnecting?: () => void;
        onLive?: () => void;
        onDisconnect?: () => void;
        onError?: (message: string) => void;
      },
      public initialRevision: number,
      public options: unknown,
    ) {
      FakeMasteryTopicSocket.instances.push(this);
    }
    start(): void {
      this.started += 1;
    }
    wake(): void {
      this.woken += 1;
    }
    stop(): void {
      this.stopped += 1;
    }
  }
  return {
    fetchProgressEvents: vi.fn(),
    Socket: FakeMasteryTopicSocket,
  };
});

vi.mock("@/lib/learning-api", () => ({
  fetchProgressEvents: mocks.fetchProgressEvents,
}));
vi.mock("@/lib/mastery-ws", () => ({
  MasteryTopicSocket: mocks.Socket,
}));

function event(revision: number): MasteryEvent {
  return {
    id: revision,
    revision,
    event_type: "attempt.recorded",
    payload: {},
    session_id: "",
    turn_id: "",
    created_at: revision,
  };
}

function subscribed(
  pathId: string,
  revision: number,
  events: MasteryEvent[],
): MasterySocketEnvelope {
  return {
    type: "subscribed",
    path_id: pathId,
    revision,
    events,
  } as MasterySocketEnvelope;
}

function topicEvent(
  pathId: string,
  revision: number,
  events: MasteryEvent[],
): MasterySocketEnvelope {
  return {
    type: "topic_event",
    path_id: pathId,
    revision,
    reason: "turn.completed",
    sequence: revision,
    events,
  } as MasterySocketEnvelope;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function Harness({ pathId }: { pathId: string | null }) {
  const activity = useMasteryPathActivity(pathId);
  return (
    <div>
      <span data-testid="events">
        {activity.events.map((item) => item.revision).join(",")}
      </span>
      <span data-testid="revision">{activity.revision}</span>
      <span data-testid="signal">{activity.signal}</span>
      <span data-testid="connection">{activity.connection}</span>
      <span data-testid="error">{activity.error ?? "none"}</span>
      <button type="button" onClick={activity.refresh}>
        refresh
      </button>
    </div>
  );
}

const view = (pathId: string | null) => <Harness pathId={pathId} />;

const socket = () => mocks.Socket.instances.at(-1)!;

beforeEach(() => {
  mocks.Socket.instances.length = 0;
});

describe("useMasteryPathActivity", () => {
  it("registers the socket on mount and the server replay loads the feed", async () => {
    render(view("p1"));
    expect(mocks.fetchProgressEvents).not.toHaveBeenCalled();
    expect(mocks.Socket.instances).toHaveLength(1);
    expect(socket().initialRevision).toBe(0);
    expect(socket().started).toBe(1);
    expect(screen.getByTestId("connection")).toHaveTextContent("connecting");
    expect(screen.getByTestId("events")).toHaveTextContent("");

    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );
    expect(screen.getByTestId("revision")).toHaveTextContent("2");
    expect(screen.getByTestId("signal")).toHaveTextContent("1");
  });

  it("a failed reconcile degrades offline with the message and keeps the loaded feed", async () => {
    render(view("p1"));
    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );

    const failing = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(failing.promise);
    fireEvent.click(screen.getByText("refresh"));
    expect(mocks.fetchProgressEvents).toHaveBeenLastCalledWith(
      "p1",
      2,
      expect.anything(),
    );
    await act(async () => failing.reject(new Error("network down")));
    await waitFor(() =>
      expect(screen.getByTestId("connection")).toHaveTextContent("offline"),
    );
    expect(screen.getByTestId("error")).toHaveTextContent("network down");
    expect(screen.getByTestId("events")).toHaveTextContent("1,2");
  });

  it("refresh resumes from the committed revision without duplicating events", async () => {
    render(view("p1"));
    const replay = [event(1), event(2), event(3)];
    act(() => socket().handlers.onEnvelope?.(subscribed("p1", 3, replay)));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2,3"),
    );

    const batch = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(batch.promise);
    fireEvent.click(screen.getByText("refresh"));
    expect(mocks.fetchProgressEvents).toHaveBeenLastCalledWith(
      "p1",
      3,
      expect.anything(),
    );
    await act(async () => batch.resolve([replay[2], event(4)]));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2,3,4"),
    );
    expect(screen.getByTestId("revision")).toHaveTextContent("4");
  });

  it("a non-Error rejection falls back to the generic offline message", async () => {
    render(view("p1"));
    act(() => socket().handlers.onEnvelope?.(subscribed("p1", 1, [event(1)])));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1"),
    );

    const failing = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(failing.promise);
    fireEvent.click(screen.getByText("refresh"));
    await act(async () => failing.reject("boom"));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent(
        "Live update unavailable",
      ),
    );
    expect(screen.getByTestId("connection")).toHaveTextContent("offline");
  });

  it("switching paths never flashes the previous topic's history or cursor", async () => {
    const rendered = render(view("p1"));
    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );

    rendered.rerender(view("p2"));
    expect(screen.getByTestId("events")).toHaveTextContent("");
    expect(screen.getByTestId("revision")).toHaveTextContent("0");
    expect(mocks.Socket.instances).toHaveLength(2);
    expect(mocks.Socket.instances[0].stopped).toBe(1);
    expect(socket().pathId).toBe("p2");
    expect(socket().initialRevision).toBe(0);

    const batch = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(batch.promise);
    fireEvent.click(screen.getByText("refresh"));
    expect(mocks.fetchProgressEvents).toHaveBeenLastCalledWith(
      "p2",
      0,
      expect.anything(),
    );
    await act(async () => batch.resolve([]));
    act(() => socket().handlers.onEnvelope?.(subscribed("p2", 7, [event(7)])));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("7"),
    );
  });

  it("socket envelopes merge into the feed, advance the revision and bump the signal", async () => {
    render(view("p1"));
    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );
    expect(screen.getByTestId("signal")).toHaveTextContent("1");

    act(() => socket().handlers.onLive?.());
    expect(screen.getByTestId("connection")).toHaveTextContent("live");
    act(() =>
      socket().handlers.onEnvelope?.(topicEvent("p1", 5, [event(3)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2,3"),
    );
    expect(screen.getByTestId("revision")).toHaveTextContent("5");
    expect(screen.getByTestId("signal")).toHaveTextContent("2");
    expect(screen.getByTestId("connection")).toHaveTextContent("live");
  });

  it("a socket drop returns offline and reconciles from durable storage", async () => {
    render(view("p1"));
    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );
    act(() => socket().handlers.onLive?.());
    expect(screen.getByTestId("connection")).toHaveTextContent("live");

    const batch = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(batch.promise);
    act(() => socket().handlers.onDisconnect?.());
    await waitFor(() =>
      expect(screen.getByTestId("connection")).toHaveTextContent("offline"),
    );
    expect(mocks.fetchProgressEvents).toHaveBeenCalledTimes(1);
    expect(mocks.fetchProgressEvents).toHaveBeenLastCalledWith(
      "p1",
      2,
      expect.anything(),
    );
    await act(async () => batch.resolve([event(3)]));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2,3"),
    );
    expect(screen.getByTestId("connection")).toHaveTextContent("offline");
    expect(screen.getByTestId("error")).toHaveTextContent("none");
  });

  it("a socket error surfaces offline with the server message", async () => {
    render(view("p1"));
    act(() => socket().handlers.onEnvelope?.(subscribed("p1", 1, [event(1)])));
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1"),
    );

    act(() => socket().handlers.onError?.("rate limited"));
    await waitFor(() =>
      expect(screen.getByTestId("connection")).toHaveTextContent("offline"),
    );
    expect(screen.getByTestId("error")).toHaveTextContent("rate limited");
  });

  it("returning focus wakes the socket and re-reconciles, and stops after unmount", async () => {
    const rendered = render(view("p1"));
    act(() =>
      socket().handlers.onEnvelope?.(subscribed("p1", 2, [event(1), event(2)])),
    );
    await waitFor(() =>
      expect(screen.getByTestId("events")).toHaveTextContent("1,2"),
    );

    const batch = deferred<MasteryEvent[]>();
    mocks.fetchProgressEvents.mockReturnValueOnce(batch.promise);
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(socket().woken).toBe(1);
    expect(mocks.fetchProgressEvents).toHaveBeenCalledTimes(1);
    expect(mocks.fetchProgressEvents).toHaveBeenLastCalledWith(
      "p1",
      2,
      expect.anything(),
    );
    await act(async () => batch.resolve([]));

    rendered.unmount();
    expect(socket().stopped).toBe(1);
    const callsAfterUnmount = mocks.fetchProgressEvents.mock.calls.length;
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(mocks.fetchProgressEvents.mock.calls.length).toBe(
      callsAfterUnmount,
    );
  });
});
