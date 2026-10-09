import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode, RefObject } from "react";

import { useModalDialog } from "@/hooks/useModalDialog";

function pressKey(key: string, options: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", {
    key,
    cancelable: true,
    ...options,
  });
  act(() => {
    document.dispatchEvent(event);
  });
  return event;
}

async function flushInitialFocus() {
  await act(async () => {});
}

function DialogHarness({
  onClose,
  closeDisabled = false,
  returnFocusRef,
  dialogTabIndex,
  children,
}: {
  onClose: () => void;
  closeDisabled?: boolean;
  returnFocusRef?: RefObject<HTMLElement | null>;
  dialogTabIndex?: number;
  children?: ReactNode;
}) {
  const dialogRef = useModalDialog(onClose, closeDisabled, returnFocusRef);
  return (
    <div ref={dialogRef} tabIndex={dialogTabIndex} data-testid="dialog">
      {children}
    </div>
  );
}

function makeVisible(element: HTMLElement) {
  Object.defineProperty(element, "offsetParent", {
    value: document.body,
    configurable: true,
  });
}

it("focuses the [data-modal-initial-focus] target after mount", async () => {
  render(
    <DialogHarness onClose={() => {}}>
      <button>First</button>
      <button data-modal-initial-focus>Preferred</button>
    </DialogHarness>,
  );
  await flushInitialFocus();
  expect(document.activeElement).toBe(screen.getByText("Preferred"));
});

it("falls back to the first focusable element", async () => {
  render(
    <DialogHarness onClose={() => {}}>
      <button>First</button>
      <button>Second</button>
    </DialogHarness>,
  );
  await flushInitialFocus();
  expect(document.activeElement).toBe(screen.getByText("First"));
});

it("falls back to the dialog itself when nothing is focusable", async () => {
  render(
    <DialogHarness onClose={() => {}} dialogTabIndex={-1}>
      <span>body</span>
    </DialogHarness>,
  );
  await flushInitialFocus();
  expect(document.activeElement).toBe(screen.getByTestId("dialog"));
});

it("closes on Escape and prevents the default action", () => {
  const onClose = vi.fn();
  render(
    <DialogHarness onClose={onClose} dialogTabIndex={-1}>
      <span>body</span>
    </DialogHarness>,
  );
  const event = pressKey("Escape");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(event.defaultPrevented).toBe(true);
});

it("ignores Escape while closeDisabled is set", () => {
  const onClose = vi.fn();
  const { rerender } = render(<DialogHarness onClose={onClose} />);
  rerender(<DialogHarness onClose={onClose} closeDisabled />);
  const event = pressKey("Escape");
  expect(onClose).not.toHaveBeenCalled();
  expect(event.defaultPrevented).toBe(false);
});

it("always invokes the latest onClose after re-render", () => {
  const first = vi.fn();
  const latest = vi.fn();
  const { rerender } = render(<DialogHarness onClose={first} />);
  rerender(<DialogHarness onClose={latest} />);
  pressKey("Escape");
  expect(first).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledTimes(1);
});

it("wraps Tab from the last focusable element to the first", () => {
  render(
    <DialogHarness onClose={() => {}}>
      <button>First</button>
      <button>Last</button>
    </DialogHarness>,
  );
  const first = screen.getByText("First");
  const last = screen.getByText("Last");
  makeVisible(first);
  makeVisible(last);
  act(() => {
    last.focus();
  });
  const event = pressKey("Tab");
  expect(document.activeElement).toBe(first);
  expect(event.defaultPrevented).toBe(true);
});

it("wraps Shift+Tab from the first focusable element to the last", () => {
  render(
    <DialogHarness onClose={() => {}}>
      <button>First</button>
      <button>Last</button>
    </DialogHarness>,
  );
  const first = screen.getByText("First");
  const last = screen.getByText("Last");
  makeVisible(first);
  makeVisible(last);
  act(() => {
    first.focus();
  });
  pressKey("Tab", { shiftKey: true });
  expect(document.activeElement).toBe(last);
});

it("refocuses the dialog when Tab finds no visible focusable element", () => {
  render(
    <DialogHarness onClose={() => {}} dialogTabIndex={-1}>
      <span>body</span>
    </DialogHarness>,
  );
  const dialog = screen.getByTestId("dialog");
  const event = pressKey("Tab");
  expect(document.activeElement).toBe(dialog);
  expect(event.defaultPrevented).toBe(true);
});

it("restores focus to the previously focused element on unmount", async () => {
  const trigger = document.createElement("button");
  document.body.appendChild(trigger);
  trigger.focus();
  try {
    const { unmount } = render(
      <DialogHarness onClose={() => {}}>
        <button>In dialog</button>
      </DialogHarness>,
    );
    await flushInitialFocus();
    expect(document.activeElement).not.toBe(trigger);
    unmount();
    expect(document.activeElement).toBe(trigger);
  } finally {
    trigger.remove();
  }
});

it("focuses the returnFocusRef target on unmount when provided", async () => {
  const anchor = document.createElement("a");
  anchor.href = "#somewhere";
  document.body.appendChild(anchor);
  const returnFocusRef: RefObject<HTMLElement | null> = { current: anchor };
  try {
    const { unmount } = render(
      <DialogHarness onClose={() => {}} returnFocusRef={returnFocusRef}>
        <button>In dialog</button>
      </DialogHarness>,
    );
    await flushInitialFocus();
    unmount();
    expect(document.activeElement).toBe(anchor);
  } finally {
    anchor.remove();
  }
});
