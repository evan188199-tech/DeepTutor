import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import BankSelectionBar from "@/components/space/question-bank/BankSelectionBar";
import type { NotebookCategory } from "@/lib/notebook-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const categories: NotebookCategory[] = [
  { id: 7, name: "Mistakes", entry_count: 3 },
  { id: 9, name: "Formulas", entry_count: 1 },
] as NotebookCategory[];

type Props = Parameters<typeof BankSelectionBar>[0];

function renderBar(overrides: Partial<Props> = {}) {
  const onSelectAll = vi.fn();
  const onClear = vi.fn();
  const onFile = vi.fn().mockResolvedValue(true);
  const onCreateAndFile = vi.fn().mockResolvedValue(true);
  const onUnfileFromCurrent = vi.fn().mockResolvedValue(true);
  const utils = render(
    <BankSelectionBar
      count={2}
      visibleCount={5}
      scope={{ kind: "all" }}
      categories={categories}
      onSelectAll={onSelectAll}
      onClear={onClear}
      onFile={onFile}
      onCreateAndFile={onCreateAndFile}
      onUnfileFromCurrent={onUnfileFromCurrent}
      {...overrides}
    />,
  );
  return {
    onSelectAll,
    onClear,
    onFile,
    onCreateAndFile,
    onUnfileFromCurrent,
    container: utils.container,
    unmount: utils.unmount,
  };
}

describe("BankSelectionBar", () => {
  it("renders nothing without a selection", () => {
    const { container } = renderBar({ count: 0 });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the selection count", () => {
    renderBar({ count: 4 });
    expect(screen.getByText("4 selected")).toBeInTheDocument();
  });

  it("offers select-all only while part of the visible list is selected", () => {
    const { onSelectAll } = renderBar({ count: 2, visibleCount: 5 });
    expect(
      screen.getByRole("button", { name: "Select all" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(onSelectAll).toHaveBeenCalledTimes(1);
  });

  it("hides select-all once everything visible is selected", () => {
    renderBar({ count: 5, visibleCount: 5 });
    expect(screen.queryByRole("button", { name: "Select all" })).toBeNull();
  });

  it("clears the selection from the close control", () => {
    const { onClear } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("offers remove-from-category only inside a category scope", async () => {
    const inside = renderBar({ scope: { kind: "category", categoryId: 7 } });
    const remove = screen.getByRole("button", { name: "Remove tag" });
    fireEvent.click(remove);
    await waitFor(() => {
      expect(inside.onUnfileFromCurrent).toHaveBeenCalledTimes(1);
    });

    inside.unmount();
    renderBar({ scope: { kind: "all" } });
    expect(screen.queryByRole("button", { name: "Remove tag" })).toBeNull();
  });

  it("files the selection into an existing tag from the menu", async () => {
    const { onFile } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    fireEvent.click(screen.getByRole("button", { name: /Formulas/ }));

    await waitFor(() => {
      expect(onFile).toHaveBeenCalledTimes(1);
      expect(onFile).toHaveBeenCalledWith(9);
    });
    expect(onFile.mock.results[0].type).toBe("return");
  });

  it("creates a new tag and files the selection in one gesture", async () => {
    const { onCreateAndFile } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    const input = screen.getByPlaceholderText("New tag…") as HTMLInputElement;
    fireEvent.change(input, { target: { value: " Hard finals " } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));

    await waitFor(() => {
      expect(onCreateAndFile).toHaveBeenCalledTimes(1);
      expect(onCreateAndFile).toHaveBeenCalledWith("Hard finals");
    });
  });

  it("keeps the menu open when filing reports a failure", async () => {
    renderBar({ onFile: vi.fn().mockResolvedValue(false) });

    fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    fireEvent.click(screen.getByRole("button", { name: /Mistakes/ }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("New tag…")).toBeInTheDocument();
    });
  });
});
