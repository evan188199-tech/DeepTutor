import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";

import { shouldSubmitOnEnter, type KeyboardSubmitEventLike } from "@/lib/composer-keyboard";
import { useImeComposing } from "@/lib/use-ime-composing";

const enterEvent: KeyboardSubmitEventLike = { key: "Enter" };

function submitBlocked(result: ReturnType<typeof useImeComposing>) {
  return shouldSubmitOnEnter(enterEvent, result.current.isComposingRef.current);
}

async function flushDeferredReset() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

it("starts idle so Enter submits", () => {
  const { result } = renderHook(() => useImeComposing());

  expect(result.current.isComposingRef.current).toBe(false);
  expect(submitBlocked(result)).toBe(true);
});

it("blocks Enter submit while composing", () => {
  const { result } = renderHook(() => useImeComposing());

  act(() => {
    result.current.onCompositionStart();
  });

  expect(result.current.isComposingRef.current).toBe(true);
  expect(submitBlocked(result)).toBe(false);
});

it("keeps the guard through the turn that confirms a candidate", () => {
  const { result } = renderHook(() => useImeComposing());

  act(() => {
    result.current.onCompositionStart();
  });
  act(() => {
    result.current.onCompositionEnd();
  });

  expect(result.current.isComposingRef.current).toBe(true);
  expect(submitBlocked(result)).toBe(false);
});

it("clears after the deferred reset and guards a new composition", async () => {
  const { result } = renderHook(() => useImeComposing());

  act(() => {
    result.current.onCompositionStart();
  });
  act(() => {
    result.current.onCompositionEnd();
  });
  await flushDeferredReset();

  expect(result.current.isComposingRef.current).toBe(false);
  expect(submitBlocked(result)).toBe(true);

  act(() => {
    result.current.onCompositionStart();
  });

  expect(result.current.isComposingRef.current).toBe(true);
  expect(submitBlocked(result)).toBe(false);
});

it("stays idle when composition end arrives without a start", async () => {
  const { result } = renderHook(() => useImeComposing());

  act(() => {
    result.current.onCompositionEnd();
  });
  await flushDeferredReset();

  expect(result.current.isComposingRef.current).toBe(false);
  expect(submitBlocked(result)).toBe(true);
});
