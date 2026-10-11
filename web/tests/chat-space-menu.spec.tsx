import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatSpaceMenu, {
  type ChatSpaceSelectionCounts,
} from "@/components/chat/space/ChatSpaceMenu";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const onSelect = vi.fn();

const emptyCounts: ChatSpaceSelectionCounts = {
  attachments: 0,
  knowledge: 0,
  chatHistory: 0,
  myAgents: 0,
  books: 0,
  reading: 0,
  notebooks: 0,
  questionBank: 0,
  persona: 0,
  memory: 0,
};

function renderMenu(
  props: Partial<Parameters<typeof ChatSpaceMenu>[0]> = {},
): ReturnType<typeof render> {
  return render(
    <ChatSpaceMenu
      variant="toolbar"
      selectedCounts={emptyCounts}
      onSelectItem={onSelect}
      {...props}
    />,
  );
}

function visibleLabels(): string[] {
  return screen
    .getAllByRole("button")
    .map((button) => button.textContent?.trim() ?? "");
}

describe("ChatSpaceMenu", () => {
  beforeEach(() => {
    onSelect.mockClear();
  });

  it("renders the fixed item order for the toolbar variant", () => {
    renderMenu({ readingAvailable: true });

    expect(visibleLabels()).toEqual([
      "Attach files",
      "Knowledge",
      "Chat History",
      "My Agents",
      "Books",
      "Reading",
      "Notebooks",
      "Question Bank",
      "Persona",
    ]);
  });

  it("drops entries whose availability flag is off", () => {
    renderMenu({
      knowledgeAvailable: false,
      personaAvailable: false,
      agentsAvailable: false,
    });

    expect(screen.queryByText("Knowledge")).toBeNull();
    expect(screen.queryByText("Persona")).toBeNull();
    expect(screen.queryByText("My Agents")).toBeNull();
    expect(screen.queryByText("Reading")).toBeNull();
    expect(screen.getByText("Attach files")).toBeTruthy();
    expect(screen.getByText("Notebooks")).toBeTruthy();
  });

  it("renames the agents entry on the resources variant", () => {
    renderMenu({ variant: "resources" });

    expect(screen.getByText("Agent conversations")).toBeTruthy();
    expect(screen.queryByText("My Agents")).toBeNull();
    expect(screen.getByText("Attach files")).toBeTruthy();
  });

  it("filters items by the typed query and can end up empty", () => {
    const { rerender } = renderMenu({ query: "book" });

    expect(screen.getByText("Books")).toBeTruthy();
    expect(screen.getByText("Notebooks")).toBeTruthy();
    expect(screen.queryByText("Chat History")).toBeNull();

    rerender(
      <ChatSpaceMenu
        variant="toolbar"
        query="zzz-no-match"
        selectedCounts={emptyCounts}
        onSelectItem={onSelect}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("reports the clicked entry key", () => {
    renderMenu();

    fireEvent.click(screen.getByText("Books"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("books");

    fireEvent.click(screen.getByText("Attach files"));
    expect(onSelect).toHaveBeenLastCalledWith("attach");
  });

  it("badges nonzero selection counts on their rows", () => {
    renderMenu({
      selectedCounts: { ...emptyCounts, books: 2, notebooks: 1 },
    });

    const booksRow = screen.getByText("Books").closest("button");
    const notebooksRow = screen.getByText("Notebooks").closest("button");
    expect(booksRow).toBeTruthy();
    expect(notebooksRow).toBeTruthy();
    expect(within(booksRow as HTMLElement).getByText("2")).toBeTruthy();
    expect(within(notebooksRow as HTMLElement).getByText("1")).toBeTruthy();
    expect(within(booksRow as HTMLElement).queryByText("1")).toBeNull();
  });

  it("renders a mention listbox with a single active option", () => {
    renderMenu({ variant: "mention" });

    const listbox = screen.getByRole("listbox", { name: "Reference space" });
    const options = within(listbox).getAllByRole("option");
    expect(options.length).toBeGreaterThan(2);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    for (const option of options.slice(1)) {
      expect(option).toHaveAttribute("aria-selected", "false");
    }
  });

  it("moves the active option with arrow keys and selects with Enter", () => {
    renderMenu({ variant: "mention" });

    const options = screen.getAllByRole("option");
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveAttribute("aria-selected", "false");

    fireEvent.keyDown(document, { key: "ArrowUp" });
    fireEvent.keyDown(document, { key: "ArrowUp" });
    const last = options[options.length - 1];
    expect(last).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(document, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("persona");
  });

  it("hovering an option moves the keyboard selection to it", () => {
    renderMenu({ variant: "mention" });

    const options = screen.getAllByRole("option");
    fireEvent.mouseEnter(options[3]);
    expect(options[3]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveAttribute("aria-selected", "false");

    fireEvent.keyDown(document, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("my_agents");
  });

  it("ignores Enter when the filtered list is empty", () => {
    renderMenu({ variant: "mention", query: "zzz-no-match" });

    fireEvent.keyDown(document, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not attach keyboard handling outside the mention variant", () => {
    renderMenu({ variant: "toolbar" });

    fireEvent.keyDown(document, { key: "ArrowDown" });
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });
});
