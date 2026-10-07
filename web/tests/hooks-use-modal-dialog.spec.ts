import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useModalDialog } from "@/hooks/useModalDialog";

function keyEvent(key: string, shiftKey = false) {
  const event = new KeyboardEvent("keydown", { key, shiftKey });
  return { event, preventDefault: vi.spyOn(event, "preventDefault") };
}

function pressKey(key: string, shiftKey = false) {
  const { event, preventDefault } = keyEvent(key, shiftKey);
  act(() => {
    document.dispatchEvent(event);
  });
  return preventDefault;
}

function buildDialog(options?: { initialFocus?: boolean }) {
  const dialog = document.createElement("div");
  const initial = document.createElement("button");
  initial.textContent = "first";
  const second = document.createElement("button");
  second.textContent = "second";
  if (options?.initialFocus) initial.setAttribute("data-modal-initial-focus", "");
  dialog.append(initial, second);
  document.body.appendChild(dialog);
  return { dialog, initial, second };
}

function renderDialogHook(options?: {
  closeDisabled?: boolean;
  returnFocus?: HTMLElement | null;
  initialFocus?: boolean;
}) {
  const { dialog } = buildDialog({ initialFocus: options?.initialFocus });
  const returnFocusRef = { current: options?.returnFocus ?? null };
  const onClose = vi.fn();
  const { result, unmount } = renderHook(
    ({
      close,
      disabled,
      returnRef,
    }: {
      close: () => void;
      disabled: boolean;
      returnRef: { current: HTMLElement | null };
    }) => {
      const ref = useModalDialog(close, disabled, returnRef);
      if (ref.current === null) ref.current = dialog;
      return ref;
    },
    {
      initialProps: {
        close: onClose,
        disabled: options?.closeDisabled ?? false,
        returnRef: returnFocusRef,
      },
    },
  );
  return { result, unmount, onClose, dialog, returnFocusRef };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  cleanup();
});

describe("useModalDialog", () => {
  it("moves focus to the [data-modal-initial-focus] element after mount", async () => {
    const { dialog } = renderDialogHook({ initialFocus: true });
    await act(async () => {
      await Promise.resolve();
    });
    const initialFocus = dialog.querySelector("[data-modal-initial-focus]");
    expect(document.activeElement).toBe(initialFocus);
  });

  it("closes on Escape and prevents the default", () => {
    const { onClose } = renderDialogHook();
    const preventDefault = pressKey("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("ignores Escape while closeDisabled", () => {
    const { onClose } = renderDialogHook({ closeDisabled: true });
    const preventDefault = pressKey("Escape");
    expect(onClose).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it("keeps Escape working after onClose identity changes", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { dialog } = buildDialog();
    const { rerender } = renderHook(
      ({ close }: { close: () => void }) => {
        const ref = useModalDialog(close, false);
        if (ref.current === null) ref.current = dialog;
        return ref;
      },
      { initialProps: { close: first } },
    );
    rerender({ close: second });
    pressKey("Escape");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("traps Tab on a dialog with no visible focusable elements", () => {
    const { result } = renderDialogHook();
    const dialog = result.current.current as HTMLDivElement;
    const focusSpy = vi.spyOn(dialog, "focus");
    const preventDefault = pressKey("Tab");
    expect(preventDefault).toHaveBeenCalled();
    expect(focusSpy).toHaveBeenCalled();
  });

  it("restores focus to the return-focus ref on unmount and removes the key listener", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    const { unmount, onClose } = renderDialogHook({ returnFocus: opener });
    opener.focus();

    unmount();
    expect(document.activeElement).toBe(opener);

    pressKey("Escape");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("skips focus restoration when the return target is detached", () => {
    const detached = document.createElement("button");
    const { unmount } = renderDialogHook({ returnFocus: detached });
    unmount();
    expect(document.activeElement).not.toBe(detached);
    expect(document.activeElement).toBe(document.body);
  });
});
