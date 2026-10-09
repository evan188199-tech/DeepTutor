import {
  act,
  cleanup,
  render,
  screen,
} from "@testing-library/react";
import { useLayoutEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";

class FakeFrames {
  private seq = 0;
  private pending = new Map<number, FrameRequestCallback>();
  readonly cancelled: number[] = [];

  requestAnimationFrame = (callback: FrameRequestCallback): number => {
    this.seq += 1;
    this.pending.set(this.seq, callback);
    return this.seq;
  };

  cancelAnimationFrame = (id: number) => {
    if (this.pending.delete(id)) this.cancelled.push(id);
  };

  flush(now = 0) {
    const callbacks = [...this.pending.values()];
    this.pending.clear();
    for (const callback of callbacks) callback(now);
  }

  get queued() {
    return this.pending.size;
  }
}

const frames = new FakeFrames();

interface ScrollModel {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

/**
 * jsdom has no layout engine, so ``scrollHeight``/``scrollTop`` are stubbed
 * with a clamped scroll model the test drives directly.
 */
function installScrollModel(el: HTMLElement, model: ScrollModel) {
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => model.scrollHeight,
  });
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    get: () => model.clientHeight,
  });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => model.scrollTop,
    set: (value: number) => {
      const max = Math.max(0, model.scrollHeight - model.clientHeight);
      model.scrollTop = Math.min(Math.max(0, value), max);
    },
  });
}

const bottomOf = (model: ScrollModel) =>
  Math.max(0, model.scrollHeight - model.clientHeight);

type AutoScrollOptions = Parameters<typeof useChatAutoScroll>[0];
type AutoScrollApi = ReturnType<typeof useChatAutoScroll>;

const modeledElements = new WeakSet<HTMLElement>();

function Harness({
  options,
  model,
  apiRef,
}: {
  options: AutoScrollOptions;
  model: ScrollModel;
  apiRef: { current: AutoScrollApi | null };
}) {
  const {
    containerRef,
    endRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll,
  } = useChatAutoScroll(options);
  // jsdom has no layout engine: install the clamped scroll model as soon as
  // the container element exists, before any frame flush observes it.
  useLayoutEffect(() => {
    apiRef.current = {
      containerRef,
      endRef,
      shouldAutoScrollRef,
      scrollToBottom,
      handleScroll,
    };
    const el = containerRef.current;
    if (el && !modeledElements.has(el)) {
      modeledElements.add(el);
      installScrollModel(el, model);
    }
  });
  return (
    <div
      data-testid="chat-scroll-root"
      ref={containerRef}
      onScroll={handleScroll}
    >
      <div ref={endRef} />
    </div>
  );
}

function renderAutoScroll(overrides: Partial<AutoScrollOptions> = {}) {
  const model: ScrollModel = {
    scrollHeight: 1000,
    scrollTop: 0,
    clientHeight: 400,
  };
  const apiRef: { current: AutoScrollApi | null } = { current: null };
  let options: AutoScrollOptions = {
    hasMessages: true,
    isStreaming: true,
    composerHeight: 0,
    messageCount: 1,
    lastMessageContent: "hello",
    lastEventCount: 0,
    ...overrides,
  };
  const view = render(
    <Harness options={options} model={model} apiRef={apiRef} />,
  );
  const setOptions = (partial: Partial<AutoScrollOptions>) => {
    options = { ...options, ...partial };
    view.rerender(<Harness options={options} model={model} apiRef={apiRef} />);
  };
  return {
    view,
    model,
    api: apiRef,
    setOptions,
    container: screen.getByTestId("chat-scroll-root"),
  };
}

function wheelUp(el: Element) {
  const event = new Event("wheel");
  Object.defineProperty(event, "deltaY", { value: -120 });
  el.dispatchEvent(event);
}

function touchDrag(el: Element, fromY: number, toY: number) {
  const start = new Event("touchstart");
  Object.defineProperty(start, "touches", { value: [{ clientY: fromY }] });
  el.dispatchEvent(start);
  const move = new Event("touchmove");
  Object.defineProperty(move, "touches", { value: [{ clientY: toY }] });
  el.dispatchEvent(move);
}

const armed = (api: { current: AutoScrollApi | null }) =>
  api.current?.shouldAutoScrollRef.current;

beforeEach(() => {
  frames.cancelled.length = 0;
  vi.stubGlobal("requestAnimationFrame", frames.requestAnimationFrame);
  vi.stubGlobal("cancelAnimationFrame", frames.cancelAnimationFrame);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useChatAutoScroll streaming pin", () => {
  it("pins to the bottom on mount while streaming", () => {
    const { model } = renderAutoScroll();
    act(() => frames.flush());
    expect(model.scrollTop).toBe(bottomOf(model));
  });

  it("keeps following content growth during streaming", () => {
    const { model, container } = renderAutoScroll();
    act(() => frames.flush());
    model.scrollHeight = 1400;
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(1000);
    expect(bottomOf(model)).toBe(1000);
  });

  it("re-pins synchronously when message content changes while pinned", () => {
    const { model, setOptions } = renderAutoScroll();
    model.scrollHeight = 1400;
    setOptions({ lastMessageContent: "hello world", messageCount: 2 });
    expect(model.scrollTop).toBe(1000);
    expect(frames.queued).toBeGreaterThanOrEqual(0);
  });

  it("releases the pin when the position drops below the last pinned frame", () => {
    const { model, api, container } = renderAutoScroll();
    act(() => frames.flush());
    expect(model.scrollTop).toBe(600);
    model.scrollHeight = 1400;
    model.scrollTop = 500;
    container.dispatchEvent(new Event("scroll"));
    expect(armed(api)).toBe(false);
    expect(model.scrollTop).toBe(500);
    model.scrollHeight = 2000;
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(500);
  });

  it("releases the pin on an upward wheel gesture and stops following", () => {
    const { model, api, container } = renderAutoScroll();
    act(() => frames.flush());
    wheelUp(container);
    expect(armed(api)).toBe(false);
    model.scrollHeight = 1400;
    act(() => frames.flush());
    expect(model.scrollTop).toBe(600);
  });

  it("keeps the pin armed for upward-finger touch moves but releases on drag down", () => {
    const { api, container } = renderAutoScroll();
    touchDrag(container, 300, 298);
    expect(armed(api)).toBe(true);
    touchDrag(container, 300, 360);
    expect(armed(api)).toBe(false);
  });

  it("re-arms near the bottom via handleScroll and follows growth again", () => {
    const { model, api, container } = renderAutoScroll();
    act(() => frames.flush());
    wheelUp(container);
    expect(armed(api)).toBe(false);
    model.scrollHeight = 1400;
    model.scrollTop = 950;
    act(() => api.current!.handleScroll());
    expect(armed(api)).toBe(true);
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(1000);
  });

  it("keeps the pin released when handleScroll reads far from the bottom", () => {
    const { model, api, container } = renderAutoScroll();
    act(() => frames.flush());
    wheelUp(container);
    model.scrollTop = bottomOf(model) - 200;
    act(() => api.current!.handleScroll());
    expect(armed(api)).toBe(false);
  });

  it("does not re-pin on a render after the pin was released", () => {
    const { model, api, container, setOptions } = renderAutoScroll();
    act(() => frames.flush());
    wheelUp(container);
    model.scrollHeight = 1400;
    setOptions({ lastMessageContent: "grown", messageCount: 2 });
    expect(armed(api)).toBe(false);
    expect(model.scrollTop).toBe(600);
  });

  it("cancels the pending stream frame when streaming ends", () => {
    const { setOptions } = renderAutoScroll();
    expect(frames.queued).toBe(1);
    setOptions({ isStreaming: false });
    expect(frames.cancelled.length).toBe(1);
    expect(frames.queued).toBe(0);
  });
});

describe("useChatAutoScroll post-stream window", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: 0, toFake: ["setTimeout", "clearTimeout", "performance"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("follows height growth right after the stream ends", () => {
    const { model, container, setOptions } = renderAutoScroll();
    act(() => frames.flush());
    setOptions({ isStreaming: false });
    model.scrollHeight = 1600;
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(1200);
  });

  it("stops following growth once the post-stream window closes", () => {
    const { model, container, setOptions } = renderAutoScroll();
    act(() => frames.flush());
    setOptions({ isStreaming: false });
    vi.advanceTimersByTime(4000);
    model.scrollHeight = 1600;
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(600);
  });

  it("extends the window when a newly appearing data-chat-grow viewer mounts", () => {
    const { model, container, setOptions } = renderAutoScroll();
    act(() => frames.flush());
    setOptions({ isStreaming: false });
    const viewer = document.createElement("div");
    viewer.setAttribute("data-chat-grow", "true");
    container.appendChild(viewer);
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    vi.advanceTimersByTime(5000);
    model.scrollHeight = 1600;
    container.dispatchEvent(new Event("load"));
    act(() => frames.flush());
    expect(model.scrollTop).toBe(1200);
  });
});

describe("useChatAutoScroll escape hatch", () => {
  it("scrollToBottom pins unconditionally even after release", () => {
    const { model, api, container } = renderAutoScroll();
    act(() => frames.flush());
    wheelUp(container);
    act(() => api.current!.scrollToBottom("smooth"));
    expect(model.scrollTop).toBe(bottomOf(model));
  });
});
