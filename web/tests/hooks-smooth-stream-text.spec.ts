import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSmoothStreamText } from "@/hooks/useSmoothStreamText";

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

type SmoothOptions = Parameters<typeof useSmoothStreamText>[2];

interface SmoothProps {
  content: string;
  isStreaming: boolean;
  options?: SmoothOptions;
}

function renderSmooth(initial: SmoothProps) {
  return renderHook(
    ({ content, isStreaming, options }: SmoothProps) =>
      useSmoothStreamText(content, isStreaming, options),
    { initialProps: initial },
  );
}

beforeEach(() => {
  frames.cancelled.length = 0;
  vi.stubGlobal("requestAnimationFrame", frames.requestAnimationFrame);
  vi.stubGlobal("cancelAnimationFrame", frames.cancelAnimationFrame);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useSmoothStreamText", () => {
  it("shows the full initial content without waiting for a frame", () => {
    const { result } = renderSmooth({ content: "Hello", isStreaming: true });
    expect(result.current).toBe("Hello");
    expect(frames.queued).toBe(0);
  });

  it("reveals the backlog gradually across frames while streaming", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "x".repeat(30), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(6);
    act(() => frames.flush(0));
    expect(result.current.length).toBe(11);
  });

  it("never exceeds maxCharsPerFrame per frame", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "y".repeat(1000), isStreaming: true });
    act(() => frames.flush(100));
    expect(result.current.length).toBe(120);
    act(() => frames.flush(200));
    expect(result.current.length).toBe(240);
  });

  it("never falls below minCharsPerFrame per frame", () => {
    const { result, rerender } = renderSmooth({
      content: "a".repeat(30),
      isStreaming: true,
      options: { catchUpDivisor: 1000 },
    });
    expect(result.current).toBe("a".repeat(30));
    rerender({
      content: "a".repeat(32),
      isStreaming: true,
      options: { catchUpDivisor: 1000 },
    });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(32);
  });

  it("skips frames while inside the reveal gap for long messages", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "z".repeat(3000), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(0);
    act(() => frames.flush(20));
    expect(result.current.length).toBe(0);
    act(() => frames.flush(30));
    expect(result.current.length).toBe(120);
    act(() => frames.flush(40));
    expect(result.current.length).toBe(120);
    act(() => frames.flush(60));
    expect(result.current.length).toBe(240);
  });

  it("caps the enforced gap at maxRevealGapMs", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "c".repeat(30_000), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(0);
    act(() => frames.flush(60));
    expect(result.current.length).toBe(0);
    act(() => frames.flush(120));
    expect(result.current.length).toBe(120);
  });

  it("snaps to the full content when the stream is interrupted", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "q".repeat(100), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(20);
    rerender({ content: "q".repeat(100), isStreaming: false });
    expect(result.current).toBe("q".repeat(100));
    expect(frames.queued).toBe(0);
    expect(frames.cancelled.length).toBeGreaterThan(0);
    act(() => frames.flush(1000));
    expect(result.current).toBe("q".repeat(100));
  });

  it("truncates immediately when content shrinks mid-stream", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "w".repeat(100), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(20);
    rerender({ content: "w".repeat(5), isStreaming: true });
    expect(result.current).toBe("w".repeat(5));
    expect(frames.queued).toBe(0);
  });

  it("idles without frames once caught up", () => {
    const { result, rerender } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "k".repeat(12), isStreaming: true });
    while (frames.queued > 0) {
      act(() => frames.flush(0));
    }
    expect(result.current.length).toBe(12);
    expect(frames.queued).toBe(0);
    rerender({ content: "k".repeat(12), isStreaming: true });
    expect(frames.queued).toBe(0);
  });

  it("resumes revealing when a new delta arrives after catch-up", () => {
    const { result, rerender } = renderSmooth({
      content: "d".repeat(30),
      isStreaming: true,
    });
    expect(result.current).toBe("d".repeat(30));
    rerender({ content: "d".repeat(90), isStreaming: true });
    act(() => frames.flush(0));
    expect(result.current.length).toBe(42);
  });

  it("passes content straight through when disabled", () => {
    const long = "much longer content ".repeat(50);
    const { result, rerender } = renderSmooth({
      content: "short",
      isStreaming: true,
      options: { enabled: false },
    });
    expect(result.current).toBe("short");
    rerender({
      content: long,
      isStreaming: true,
      options: { enabled: false },
    });
    expect(result.current).toBe(long);
    expect(frames.queued).toBe(0);
    rerender({ content: "tiny", isStreaming: false, options: { enabled: false } });
    expect(result.current).toBe("tiny");
  });

  it("cancels the pending reveal frame on unmount", () => {
    const { rerender, unmount } = renderSmooth({ content: "", isStreaming: true });
    rerender({ content: "u".repeat(500), isStreaming: true });
    expect(frames.queued).toBe(1);
    unmount();
    expect(frames.queued).toBe(0);
    expect(frames.cancelled.length).toBe(1);
  });
});
