import { act, fireEvent, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDragSort } from "@/hooks/useDragSort";

/**
 * Behavior tests for the pointer/keyboard drag-sort hook.
 *
 * Rows are laid out in jsdom by stubbing getBoundingClientRect on each row
 * (40px tall, stacked) and on the scroll container (tall interior, so the
 * edge auto-scroll zone never fires and drags stay deterministic). Pointer
 * sequences start on the row element — React synthesizes onPointerDown — and
 * continue on document, where the hook parks its move/up/cancel/key/touch
 * listeners for the life of the drag.
 */

const ROW_HEIGHT = 40;
const POINTER = { pointerId: 7, pointerType: "mouse" } as const;
const TOUCH = { pointerId: 9, pointerType: "touch" } as const;

type PointerSpec = { pointerId: number; pointerType: string };

function rowRect(index: number): DOMRect {
  return new DOMRect(0, index * ROW_HEIGHT, 240, ROW_HEIGHT);
}

function stubRowRects(scope: HTMLElement) {
  scope.querySelectorAll<HTMLElement>("[data-row]").forEach((row, index) => {
    vi.spyOn(row, "getBoundingClientRect").mockReturnValue(rowRect(index));
  });
}

function stubContainerRect(container: HTMLElement) {
  vi.spyOn(container, "getBoundingClientRect").mockReturnValue(
    new DOMRect(0, 0, 320, 4000),
  );
}

type DragListProps = {
  ids: string[];
  onReorder: (nextIds: string[]) => void;
  disabled?: boolean;
  withScroll?: boolean;
  onRowClick?: () => void;
};

function DragList({
  ids,
  onReorder,
  disabled = false,
  withScroll = false,
  onRowClick,
}: DragListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { draggingId, getItemProps } = useDragSort({
    ids,
    onReorder,
    disabled,
    scrollRef: withScroll ? scrollRef : undefined,
  });
  return (
    <div ref={scrollRef} data-testid="scroll-box">
      {ids.map((id, index) => (
        <a
          key={id}
          href="#"
          data-row={id}
          data-testid={`row-${id}`}
          onClick={onRowClick}
          {...getItemProps(id)}
        >
          {`${index}:${id}`}
          {id === "b" ? (
            <button type="button" data-testid="row-b-menu" data-no-drag>
              menu
            </button>
          ) : null}
        </a>
      ))}
    </div>
  );
}

function setup(props: Partial<DragListProps> = {}) {
  const onReorder = vi.fn();
  const utils = render(
    <DragList
      ids={props.ids ?? ["a", "b", "c", "d"]}
      onReorder={props.onReorder ?? onReorder}
      disabled={props.disabled}
      withScroll={props.withScroll}
      onRowClick={props.onRowClick}
    />,
  );
  const scrollBox = utils.getByTestId("scroll-box");
  stubContainerRect(scrollBox);
  stubRowRects(scrollBox);
  return { ...utils, onReorder, onRowClick: props.onRowClick };
}

function dragMove(clientY: number, pointer: PointerSpec = POINTER) {
  act(() => {
    document.dispatchEvent(
      new PointerEvent("pointermove", {
        pointerId: pointer.pointerId,
        clientX: 100,
        clientY,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

function dragRelease(clientY: number, pointer: PointerSpec = POINTER) {
  act(() => {
    document.dispatchEvent(
      new PointerEvent("pointerup", {
        pointerId: pointer.pointerId,
        clientX: 100,
        clientY,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

function pressRow(
  row: HTMLElement,
  clientY: number,
  pointer: PointerSpec = POINTER,
  button = 0,
) {
  fireEvent.pointerDown(row, {
    pointerId: pointer.pointerId,
    pointerType: pointer.pointerType,
    button,
    clientX: 100,
    clientY,
  });
}

function pressCancel(pointer: PointerSpec = POINTER) {
  act(() => {
    document.dispatchEvent(
      new PointerEvent("pointercancel", {
        pointerId: pointer.pointerId,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

function pressEscape() {
  const event = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
  });
  act(() => {
    document.dispatchEvent(event);
  });
  return event;
}

describe("useDragSort pointer drags", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ignores a press that never travels past the pointer slop", () => {
    const utils = setup({ onRowClick: vi.fn() });
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(13);
    dragRelease(13);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
    // A press that never became a drag must not swallow the row's click.
    fireEvent.click(rowA);
    expect(utils.onRowClick).toHaveBeenCalledTimes(1);
  });

  it("commits a downward reorder once the drag passes the neighbor midpoint", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    // Press on row a (top 0) at y=10, drag to offset 31: the row's leading
    // edge (center 20 + half 20 + 31 = 71) is past row b's center (60).
    pressRow(rowA, 10);
    dragMove(41);

    expect(utils.getByTestId("row-a").style.transform).toBe(
      "translateY(31px)",
    );
    expect(utils.getByTestId("row-a").style.position).toBe("relative");
    expect(utils.getByTestId("row-a").style.zIndex).toBe("30");
    expect(utils.getByTestId("row-a").style.touchAction).toBe("none");
    expect(utils.getByTestId("row-b").style.transform).toBe(
      "translateY(-40px)",
    );
    expect(utils.getByTestId("row-b").style.transition).toContain("transform");
    expect(utils.getByTestId("row-d").style.transform).toBe(
      "translateY(0px)",
    );

    dragRelease(41);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["b", "a", "c", "d"]);
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
  });

  it("commits an upward drag across two rows", () => {
    const utils = setup();
    const rowC = utils.getByTestId("row-c");

    pressRow(rowC, 100);
    dragMove(39);
    dragRelease(39);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["c", "a", "b", "d"]);
  });

  it("releases at the same position without reordering but still swallows the click", () => {
    const utils = setup({ onRowClick: vi.fn() });
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    // 15px is short of row b's midpoint (half a 40px row).
    dragMove(25);
    dragRelease(25);

    expect(utils.onReorder).not.toHaveBeenCalled();

    // Activation happened, so the release swallows exactly one click — the
    // one the press would have produced — then lets normal clicks through.
    expect(fireEvent.click(rowA)).toBe(false);
    expect(utils.onRowClick).not.toHaveBeenCalled();
    fireEvent.click(rowA);
    expect(utils.onRowClick).toHaveBeenCalledTimes(1);
  });

  it("clamps a drag far past the list end to the last slot", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(510);
    dragRelease(510);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["b", "c", "d", "a"]);
  });

  it("ignores moves and releases from other pointers until the owning pointer releases", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");
    const other = { pointerId: 99, pointerType: "mouse" } as const;

    pressRow(rowA, 10);
    dragMove(41, other);
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");

    dragMove(41);
    dragRelease(41, other);
    expect(utils.onReorder).not.toHaveBeenCalled();

    dragRelease(41);
    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["b", "a", "c", "d"]);
  });

  it("rejects presses with a non-primary mouse button", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10, POINTER, 2);
    dragMove(41);
    dragRelease(41);

    expect(utils.onReorder).not.toHaveBeenCalled();
  });

  it("supports rapid consecutive drags in one sequence", () => {
    const utils = setup();

    pressRow(utils.getByTestId("row-a"), 10);
    dragMove(41);
    dragRelease(41);

    pressRow(utils.getByTestId("row-c"), 100);
    dragMove(131);
    dragRelease(131);

    expect(utils.onReorder).toHaveBeenCalledTimes(2);
    expect(utils.onReorder).toHaveBeenNthCalledWith(1, ["b", "a", "c", "d"]);
    expect(utils.onReorder).toHaveBeenNthCalledWith(2, ["a", "b", "d", "c"]);
  });
});

describe("useDragSort cancellation", () => {
  it("aborts on pointercancel without reordering", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    pressCancel();
    dragRelease(41);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
  });

  it("aborts on escape and restores the document body", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    expect(document.body.style.userSelect).toBe("none");
    expect(document.body.style.cursor).toBe("grabbing");

    const escape = pressEscape();
    dragRelease(41);

    expect(escape.defaultPrevented).toBe(true);
    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
  });

  it("releases document listeners when the drag ends", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    dragRelease(41);
    expect(utils.onReorder).toHaveBeenCalledTimes(1);

    // Stray events after the drag must not resurrect it.
    dragMove(81);
    dragRelease(81);
    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
  });

  it("unmounting mid-drag releases listeners and the body styles", () => {
    const cancelAnimationFrameSpy = vi.spyOn(
      window,
      "cancelAnimationFrame",
    );
    const utils = setup({ withScroll: true });

    pressRow(utils.getByTestId("row-a"), 10);
    dragMove(41);
    expect(document.body.style.userSelect).toBe("none");

    utils.unmount();
    dragRelease(41);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
    expect(cancelAnimationFrameSpy).toHaveBeenCalled();
  });

  it("cancels the auto-scroll follow loop when the drag settles", () => {
    const cancelAnimationFrameSpy = vi.spyOn(window, "cancelAnimationFrame");
    const utils = setup({ withScroll: true });
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    dragRelease(41);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(cancelAnimationFrameSpy).toHaveBeenCalled();
  });
});

describe("useDragSort touch drags", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ignores a finger that scrolls away before the hold elapses", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 50, TOUCH);
    dragMove(65, TOUCH);
    // Advancing past the hold delay must not resurrect the cleared timer.
    act(() => {
      vi.advanceTimersByTime(400);
    });
    dragRelease(65, TOUCH);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
  });

  it("activates after the hold, blocks touch scroll, and commits the drop", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const utils = setup();
    const rowC = utils.getByTestId("row-c");

    pressRow(rowC, 100, TOUCH);
    expect(document.body.style.userSelect).toBe("");

    act(() => {
      vi.advanceTimersByTime(320);
    });
    expect(document.body.style.userSelect).toBe("none");

    // An active drag must hold the page still under the finger.
    const touchMove = new TouchEvent("touchmove", { cancelable: true });
    act(() => {
      document.dispatchEvent(touchMove);
    });
    expect(touchMove.defaultPrevented).toBe(true);

    dragMove(39, TOUCH);
    dragRelease(39, TOUCH);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["c", "a", "b", "d"]);
    expect(document.body.style.userSelect).toBe("");
  });
});

describe("useDragSort keyboard reordering", () => {
  it("moves a row one slot down with alt+arrow down", () => {
    const utils = setup();
    const rowB = utils.getByTestId("row-b");

    // A handled shortcut is prevented: fireEvent yields false then.
    expect(
      fireEvent.keyDown(rowB, { key: "ArrowDown", altKey: true }),
    ).toBe(false);

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["a", "c", "b", "d"]);
  });

  it("moves a row one slot up with alt+arrow up", () => {
    const utils = setup();
    const rowC = utils.getByTestId("row-c");

    fireEvent.keyDown(rowC, { key: "ArrowUp", altKey: true });

    expect(utils.onReorder).toHaveBeenCalledTimes(1);
    expect(utils.onReorder).toHaveBeenCalledWith(["a", "c", "b", "d"]);
  });

  it("treats alt+arrows at the list edges as no-ops", () => {
    const utils = setup();

    expect(
      fireEvent.keyDown(utils.getByTestId("row-a"), {
        key: "ArrowUp",
        altKey: true,
      }),
    ).toBe(true);
    expect(
      fireEvent.keyDown(utils.getByTestId("row-d"), {
        key: "ArrowDown",
        altKey: true,
      }),
    ).toBe(true);
    expect(utils.onReorder).not.toHaveBeenCalled();
  });

  it("ignores arrows without alt and non-vertical keys", () => {
    const utils = setup();
    const rowB = utils.getByTestId("row-b");

    fireEvent.keyDown(rowB, { key: "ArrowDown" });
    fireEvent.keyDown(rowB, { key: "ArrowLeft", altKey: true });

    expect(utils.onReorder).not.toHaveBeenCalled();
  });

  it("cannot reorder a single-item list", () => {
    const utils = setup({ ids: ["only"] });
    const row = utils.getByTestId("row-only");

    pressRow(row, 10);
    dragMove(41);
    dragRelease(41);
    fireEvent.keyDown(row, { key: "ArrowDown", altKey: true });

    expect(utils.onReorder).not.toHaveBeenCalled();
  });
});

describe("useDragSort guards", () => {
  it("ignores pointer and keyboard when disabled", () => {
    const utils = setup({ disabled: true });
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    dragRelease(41);
    fireEvent.keyDown(rowA, { key: "ArrowDown", altKey: true });

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
  });

  it("never starts a drag from a data-no-drag child", () => {
    const utils = setup();
    const menu = utils.getByTestId("row-b-menu");

    pressRow(menu, 60);
    dragMove(101);
    dragRelease(101);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(utils.getByTestId("row-b").style.position).not.toBe("relative");
  });

  it("lets go instead of dropping when the list changes under the drag", () => {
    const utils = setup();
    const rowA = utils.getByTestId("row-a");

    pressRow(rowA, 10);
    dragMove(41);
    expect(utils.getByTestId("row-a").style.position).toBe("relative");

    utils.rerender(
      <DragList ids={["a", "b", "c"]} onReorder={utils.onReorder} />,
    );
    stubRowRects(utils.getByTestId("scroll-box"));

    dragMove(51);
    dragRelease(51);

    expect(utils.onReorder).not.toHaveBeenCalled();
    expect(utils.getByTestId("row-a").style.position).not.toBe("relative");
    expect(document.body.style.userSelect).toBe("");
  });
});
