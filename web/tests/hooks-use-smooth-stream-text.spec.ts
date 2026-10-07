import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  revealGapMs,
  revealStep,
  useSmoothStreamText,
} from "@/hooks/useSmoothStreamText";

class FakeFrames {
  private seq = 0;
  private pending = new Map<number, FrameRequestCallback>();
  cancelled: number[] = [];

  requestAnimationFrame = (callback: FrameRequestCallback): number => {
    this.seq += 1;
    const id = this.seq;
    this.pending.set(id, callback);
    return id;
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

beforeEach(() => {
  frames.cancelled.length = 0;
  vi.stubGlobal("requestAnimationFrame", frames.requestAnimationFrame);
  vi.stubGlobal("cancelAnimationFrame", frames.cancelAnimationFrame);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("revealStep", () => {
  it("returns 0 when there is no backlog", () => {
    expect(revealStep(10, 10)).toBe(0);
    expect(revealStep(12, 10)).toBe(0);
  });

  it("never advances below minCharsPerFrame", () => {
    expect(revealStep(0, 3, { minCharsPerFrame: 2 })).toBe(2);
  });

  it("scales with the backlog and clamps at maxCharsPerFrame", () => {
    expect(revealStep(0, 11, { catchUpDivisor: 5 })).toBe(3);
    expect(revealStep(0, 10_000, { maxCharsPerFrame: 120 })).toBe(120);
  });
});

describe("revealGapMs", () => {
  it("imposes no gap for short messages", () => {
    expect(revealGapMs(100)).toBe(0);
    expect(revealGapMs(1600)).toBe(0);
  });

  it("rises with length and caps at maxRevealGapMs", () => {
    expect(revealGapMs(1700)).toBe(17);
    expect(revealGapMs(20_000, { maxRevealGapMs: 120 })).toBe(120);
    expect(revealGapMs(1000, { revealGapCharsPerMs: 10 })).toBe(100);
  });
});

describe("useSmoothStreamText", () => {
  it("passes content straight through while disabled", () => {
    const { result, rerender } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming, { enabled: false }),
      { initialProps: { content: "a", streaming: true } },
    );
    rerender({ content: "abcdef", streaming: true });
    expect(result.current).toBe("abcdef");
    expect(frames.queued).toBe(0);
  });

  it("shows the full initial content before any frame runs", () => {
    const { result } = renderHook(() => useSmoothStreamText("ready", true));
    expect(result.current).toBe("ready");
  });

  it("reveals in bounded steps across frames until caught up", () => {
    const target = "x".repeat(20);
    const { result, rerender } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming),
      { initialProps: { content: "x", streaming: true } },
    );

    rerender({ content: target, streaming: true });
    expect(frames.queued).toBe(1);

    act(() => frames.flush(0));
    expect(result.current).toBe("x".repeat(5));

    act(() => frames.flush(16));
    expect(result.current).toBe("x".repeat(8));

    let guard = 0;
    while (frames.queued > 0 && guard < 20) {
      act(() => frames.flush(32 + guard * 16));
      guard += 1;
    }
    expect(result.current).toBe(target);
    expect(frames.queued).toBe(0);
    expect(guard).toBeLessThanOrEqual(10);
  });

  it("skips frames while the rate cap is in force for long messages", () => {
    const target = "y".repeat(2400);
    const { rerender } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming),
      { initialProps: { content: "y", streaming: true } },
    );
    rerender({ content: target, streaming: true });

    act(() => frames.flush(0));
    expect(frames.queued).toBe(1);

    act(() => frames.flush(50));
    expect(frames.queued).toBe(1);

    act(() => frames.flush(120));
    expect(frames.queued).toBe(1);
  });

  it("snaps to the full content the moment streaming stops", () => {
    const { result, rerender } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming),
      { initialProps: { content: "abc", streaming: true } },
    );
    rerender({ content: "abcdefgh", streaming: true });
    act(() => frames.flush(0));
    expect(result.current).toBe("abcde");

    rerender({ content: "abcdefgh", streaming: false });
    expect(result.current).toBe("abcdefgh");
    expect(frames.queued).toBe(0);
  });

  it("snaps back when content shrinks mid-stream", () => {
    const { result, rerender } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming),
      { initialProps: { content: "x".repeat(20), streaming: false } },
    );
    rerender({ content: "x".repeat(24), streaming: true });
    rerender({ content: "hi", streaming: true });
    expect(result.current).toBe("hi");
    expect(frames.queued).toBe(0);
  });

  it("cancels the pending frame on unmount", () => {
    const target = "z".repeat(40);
    const { rerender, unmount } = renderHook(
      ({ content, streaming }) => useSmoothStreamText(content, streaming),
      { initialProps: { content: "z", streaming: true } },
    );
    rerender({ content: target, streaming: true });
    expect(frames.queued).toBe(1);

    unmount();
    expect(frames.cancelled.length).toBe(1);
    expect(frames.queued).toBe(0);

    const before = frames.cancelled.length;
    frames.flush(999);
    expect(frames.cancelled.length).toBe(before);
  });
});
