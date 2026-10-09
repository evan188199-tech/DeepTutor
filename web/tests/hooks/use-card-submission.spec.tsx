import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { COMMAND_CONFIRMATION_FAILED } from "@/features/chat/transport/command-delivery";
import { useCardSubmission } from "@/hooks/use-card-submission";

afterEach(() => cleanup());

describe("useCardSubmission", () => {
  it("starts idle with nothing in flight and no failure recorded", () => {
    const { result } = renderHook(() => useCardSubmission(vi.fn()));

    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(false);
    expect(result.current.failureMessage).toBeNull();
  });

  it("passes the payload through and holds the sending state on an accepted submission", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({
        text: "Fourier",
        answers: [{ questionId: "q1", text: "42" }],
      });
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      text: "Fourier",
      answers: [{ questionId: "q1", text: "42" }],
    });
    // A true verdict means the host took over: the card stays claimed.
    expect(result.current.sending).toBe(true);
    expect(result.current.failed).toBe(false);
    expect(result.current.failureMessage).toBeNull();
  });

  it("treats a host without a verdict as still claimed, not failed", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({ text: "hello" });
    });

    expect(result.current.sending).toBe(true);
    expect(result.current.failed).toBe(false);
    expect(result.current.failureMessage).toBeNull();
  });

  it("reopens the card on an explicit false verdict without inventing a message", async () => {
    const onSubmit = vi.fn().mockResolvedValue(false);
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({ text: "hello" });
    });

    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(true);
    expect(result.current.failureMessage).toBeNull();
  });

  it("maps a thrown submission to the confirmation failure and reopens the card", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("socket gone"));
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({ text: "hello" });
    });

    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(true);
    expect(result.current.failureMessage).toBe(COMMAND_CONFIRMATION_FAILED);
  });

  it("keeps the card claimed while a submission is in flight, so a duplicate click is gated", async () => {
    const resolvers: Array<(value: boolean) => void> = [];
    const onSubmit = vi.fn().mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          resolvers.push(resolve);
        }),
    );
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    let firstFlight: Promise<void> = Promise.resolve();
    act(() => {
      firstFlight = result.current.submit({ text: "first" });
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(result.current.sending).toBe(true);
    expect(result.current.failed).toBe(false);

    // The consumer disables the button on `sending`; the hook must keep that
    // state held for the whole flight instead of settling early.
    let secondFlight: Promise<void> = Promise.resolve();
    act(() => {
      secondFlight = result.current.submit({ text: "second" });
    });
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(result.current.sending).toBe(true);
    expect(result.current.failed).toBe(false);

    await act(async () => {
      resolvers[0](true);
      resolvers[1](true);
      await Promise.all([firstFlight, secondFlight]);
    });
    expect(result.current.sending).toBe(true);
    expect(result.current.failed).toBe(false);
  });

  it("clears a previous failure the moment a retry starts", async () => {
    const onSubmit = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({ text: "try 1" });
    });
    expect(result.current.failed).toBe(true);

    let flight: Promise<void> = Promise.resolve();
    act(() => {
      flight = result.current.submit({ text: "try 2" });
    });
    // The stale failure is wiped up front, before the verdict is known.
    expect(result.current.failed).toBe(false);
    expect(result.current.failureMessage).toBeNull();

    await act(async () => {
      await flight;
    });
    expect(result.current.failed).toBe(false);
    expect(result.current.sending).toBe(true);
  });

  it("clears the failure message when a retry follows a thrown submission", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useCardSubmission(onSubmit));

    await act(async () => {
      await result.current.submit({ text: "try 1" });
    });
    expect(result.current.failureMessage).toBe(COMMAND_CONFIRMATION_FAILED);

    await act(async () => {
      await result.current.submit({ text: "try 2" });
    });
    expect(result.current.failureMessage).toBeNull();
    expect(result.current.failed).toBe(false);
    expect(result.current.sending).toBe(true);
  });
});
