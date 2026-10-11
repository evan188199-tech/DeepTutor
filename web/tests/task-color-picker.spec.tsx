import {
  act,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TaskColorPicker from "@/components/tasks/TaskColorPicker";
import { DEFAULT_TASK_COLORS, type TaskColors } from "@/lib/task-board-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const base: TaskColors = {
  todo: "#2563eb",
  doing: "#a16207",
  done: "#15803d",
};

type PickerProps = Parameters<typeof TaskColorPicker>[0];

function renderPicker(overrides: Partial<PickerProps> = {}) {
  const onSave = vi.fn();
  const utils = render(
    <TaskColorPicker
      colors={base}
      disabled={false}
      busy={false}
      onSave={onSave}
      {...overrides}
    />,
  );
  return { onSave, utils };
}

const trigger = () =>
  screen.getByRole("button", { name: "tasks.colors" }) as HTMLButtonElement;

const hexInput = (status: "todo" | "doing" | "done") =>
  screen.getByLabelText(`kanban.${status}: tasks.color`) as HTMLInputElement;

function openPanel() {
  fireEvent.click(trigger());
  return screen.getByRole("dialog", { name: "tasks.colors" });
}

describe("TaskColorPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens and closes the panel from the trigger", () => {
    const { utils } = renderPicker();

    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: "tasks.colors" })).toBeTruthy();

    fireEvent.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(utils.container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("disables the trigger while disabled or busy", () => {
    const { utils } = renderPicker({ disabled: true });
    expect(trigger()).toBeDisabled();

    utils.rerender(
      <TaskColorPicker colors={base} disabled={false} busy onSave={vi.fn()} />,
    );
    expect(trigger()).toBeDisabled();
  });

  it("marks the active status tab and switches the edited color", () => {
    renderPicker();

    openPanel();
    const todoTab = screen.getByRole("button", { name: "kanban.todo" });
    const doingTab = screen.getByRole("button", { name: "kanban.doing" });
    expect(todoTab).toHaveAttribute("aria-pressed", "true");
    expect(hexInput("todo").value).toBe("#2563EB");

    fireEvent.click(doingTab);
    expect(doingTab).toHaveAttribute("aria-pressed", "true");
    expect(todoTab).toHaveAttribute("aria-pressed", "false");
    expect(hexInput("doing").value).toBe("#A16207");
  });

  it("applies a swatch to the active status and reports the draft on save", () => {
    const { onSave } = renderPicker();

    openPanel();
    const swatch = screen.getByLabelText("Choose color: #8b5cf6");
    expect(swatch).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(swatch);
    expect(swatch).toHaveAttribute("aria-pressed", "true");

    const save = screen.getByRole("button", { name: "kanban.save" });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledTimes(1);
    const [draft, onSuccess] = onSave.mock.calls[0];
    expect(draft).toEqual({ ...base, todo: "#8b5cf6" });
    expect(draft.doing).toBe(base.doing);

    act(() => {
      onSuccess();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("rejects an incomplete hex but accepts a valid custom one", () => {
    const { onSave } = renderPicker();

    openPanel();
    const input = hexInput("todo");

    fireEvent.change(input, { target: { value: "#12ab" } });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "kanban.save" })).toBeDisabled();

    fireEvent.change(input, { target: { value: "#12ABCF" } });
    expect(input).toHaveAttribute("aria-invalid", "false");
    expect(input.value).toBe("#12ABCF");

    fireEvent.click(screen.getByRole("button", { name: "kanban.save" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toEqual({ ...base, todo: "#12ABCF" });
  });

  it("keeps save disabled until the draft actually differs", () => {
    renderPicker({ colors: { ...DEFAULT_TASK_COLORS } });

    openPanel();
    expect(screen.getByRole("button", { name: "kanban.save" })).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Choose color: #db2777"));
    expect(screen.getByRole("button", { name: "kanban.save" })).toBeEnabled();
  });

  it("surfaces the save error through an alert only when present", () => {
    const { utils } = renderPicker({ error: "could not save colors" });

    openPanel();
    expect(screen.getByRole("alert").textContent).toBe(
      "could not save colors",
    );

    utils.rerender(
      <TaskColorPicker
        colors={base}
        disabled={false}
        busy={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog", { name: "tasks.colors" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("resets the draft back to the default palette", () => {
    const custom: TaskColors = {
      todo: "#111111",
      doing: "#222222",
      done: "#333333",
    };
    const { onSave } = renderPicker({ colors: custom });

    openPanel();
    fireEvent.click(screen.getByLabelText("Choose color: #db2777"));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(hexInput("todo").value).toBe("#2563EB");
    fireEvent.click(screen.getByRole("button", { name: "kanban.save" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toEqual(DEFAULT_TASK_COLORS);
  });

  it("closes via the close button and via Escape", () => {
    renderPicker();

    openPanel();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    openPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on an outside mousedown but not while busy", () => {
    const { utils } = renderPicker();

    openPanel();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();

    utils.rerender(
      <TaskColorPicker
        colors={base}
        disabled={false}
        busy={false}
        onSave={vi.fn()}
      />,
    );
    openPanel();
    utils.rerender(
      <TaskColorPicker colors={base} disabled={false} busy onSave={vi.fn()} />,
    );
    fireEvent.mouseDown(document.body);
    expect(screen.getByRole("dialog", { name: "tasks.colors" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "tasks.colors" })).toBeTruthy();

    const save = screen.getByRole("button", { name: "kanban.save" });
    expect(save).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  });
});
