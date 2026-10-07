import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePickerOpen } from "@/hooks/usePickerOpen";

async function flushMutations() {
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

function setPickerOpen(open: boolean) {
  if (open) {
    document.body.setAttribute("data-picker-open", "");
  } else {
    document.body.removeAttribute("data-picker-open");
  }
}

afterEach(() => {
  cleanup();
  setPickerOpen(false);
});

describe("usePickerOpen", () => {
  it("reads false when no picker marker is present", () => {
    const { result } = renderHook(() => usePickerOpen());
    expect(result.current).toBe(false);
  });

  it("reads the marker that already exists on mount", async () => {
    setPickerOpen(true);
    const { result } = renderHook(() => usePickerOpen());
    await flushMutations();
    expect(result.current).toBe(true);
  });

  it("flips true when the picker marker appears and false when it leaves", async () => {
    const { result } = renderHook(() => usePickerOpen());
    expect(result.current).toBe(false);

    setPickerOpen(true);
    await flushMutations();
    expect(result.current).toBe(true);

    setPickerOpen(false);
    await flushMutations();
    expect(result.current).toBe(false);
  });

  it("disconnects its MutationObserver on unmount", async () => {
    const disconnect = vi.spyOn(MutationObserver.prototype, "disconnect");
    const { unmount } = renderHook(() => usePickerOpen());
    unmount();
    expect(disconnect).toHaveBeenCalled();
    disconnect.mockRestore();
  });
});
