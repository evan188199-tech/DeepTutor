import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePickerOpen } from "@/hooks/usePickerOpen";

async function setPickerAttribute(present: boolean) {
  await act(async () => {
    if (present) {
      document.body.setAttribute("data-picker-open", "");
    } else {
      document.body.removeAttribute("data-picker-open");
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(async () => {
  if (document.body.hasAttribute("data-picker-open")) {
    await setPickerAttribute(false);
  }
});

describe("usePickerOpen", () => {
  it("defaults to closed", () => {
    const { result } = renderHook(() => usePickerOpen());
    expect(result.current).toBe(false);
  });

  it("reports open when the body marker is already present at mount", async () => {
    await setPickerAttribute(true);
    const { result } = renderHook(() => usePickerOpen());
    expect(result.current).toBe(true);
  });

  it("flips to open when the marker is added", async () => {
    const { result } = renderHook(() => usePickerOpen());
    expect(result.current).toBe(false);
    await setPickerAttribute(true);
    expect(result.current).toBe(true);
  });

  it("flips back to closed when the marker is removed", async () => {
    const { result } = renderHook(() => usePickerOpen());
    await setPickerAttribute(true);
    expect(result.current).toBe(true);
    await setPickerAttribute(false);
    expect(result.current).toBe(false);
  });

  it("ignores unrelated body attribute changes", async () => {
    const { result } = renderHook(() => usePickerOpen());
    await act(async () => {
      document.body.setAttribute("data-other-flag", "1");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(result.current).toBe(false);
  });

  it("disconnects its observer on unmount", () => {
    const disconnect = vi.spyOn(MutationObserver.prototype, "disconnect");
    const { unmount } = renderHook(() => usePickerOpen());
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });
});
