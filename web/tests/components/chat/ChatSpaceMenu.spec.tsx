import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import { peekPickerOrigin } from "@/lib/picker-origin";
import ChatSpaceMenu from "@/components/chat/space/ChatSpaceMenu";
import type { ChatSpaceSelectionCounts } from "@/components/chat/space/ChatSpaceMenu";

initI18n("en");

const zeroCounts: ChatSpaceSelectionCounts = {
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

function mountMenu(
  overrides: Partial<
    React.ComponentProps<typeof ChatSpaceMenu>
  > = {},
) {
  return render(
    <ChatSpaceMenu
      variant="toolbar"
      selectedCounts={zeroCounts}
      onSelectItem={vi.fn()}
      {...overrides}
    />,
  );
}

const rowLabels = () =>
  screen.getAllByRole("button").map((row) => row.textContent);

describe("ChatSpaceMenu", () => {
  it("renders the composer rows in a fixed order and hides optional entries by default", () => {
    mountMenu();

    expect(rowLabels()).toEqual([
      "Attach files",
      "Knowledge",
      "Chat History",
      "Subagents",
      "Books",
      "Notebooks",
      "Question Bank",
      "Persona",
    ]);
    expect(screen.queryByText("Reading")).toBeNull();
    expect(screen.queryByText("Search the selected knowledge bases.")).toBeNull();
  });

  it("exposes listbox semantics, descriptions and the initial active row in the mention variant", () => {
    mountMenu({ variant: "mention" });

    const listbox = screen.getByRole("listbox", { name: "Reference space" });
    const options = within(listbox).getAllByRole("option");
    expect(options).toHaveLength(8);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");
    expect(
      within(listbox).getByText("Search the selected knowledge bases."),
    ).toBeTruthy();
  });

  it("adds and removes rows according to the availability flags", () => {
    mountMenu({
      knowledgeAvailable: false,
      personaAvailable: false,
      agentsAvailable: false,
      readingAvailable: true,
    });

    expect(rowLabels()).toEqual([
      "Attach files",
      "Chat History",
      "Books",
      "Reading",
      "Notebooks",
      "Question Bank",
    ]);
  });

  it("filters rows by the localized label when a query is set", () => {
    const { rerender } = mountMenu({ variant: "mention", query: "att" });
    const matches = screen.getAllByRole("option");
    expect(matches).toHaveLength(1);
    expect(within(matches[0]).getByText("Attach files")).toBeTruthy();

    rerender(
      <ChatSpaceMenu
        variant="mention"
        query="hist"
        selectedCounts={zeroCounts}
        onSelectItem={vi.fn()}
      />,
    );
    const historyMatches = screen.getAllByRole("option");
    expect(historyMatches).toHaveLength(1);
    expect(within(historyMatches[0]).getByText("Chat History")).toBeTruthy();
  });

  it("renders an empty menu when the query matches no label", () => {
    mountMenu({ variant: "mention", query: "zzz" });

    expect(screen.getByRole("listbox", { name: "Reference space" })).toBeTruthy();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("dispatches the clicked key and records the picker origin", () => {
    const onSelectItem = vi.fn();
    mountMenu({ onSelectItem });

    fireEvent.click(screen.getByRole("button", { name: "Attach files" }));
    expect(onSelectItem).toHaveBeenCalledWith("attach");

    fireEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    expect(onSelectItem).toHaveBeenCalledWith("knowledge");
    expect(peekPickerOrigin()).not.toBeNull();
  });

  it("badges each row with its selection count", () => {
    mountMenu({
      selectedCounts: { ...zeroCounts, attachments: 2, knowledge: 3 },
    });

    expect(
      within(screen.getByRole("button", { name: /Attach files/ })).getByText(
        "2",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("button", { name: /Knowledge/ })).getByText("3"),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("button", { name: /Books/ })).queryByText("0"),
    ).toBeNull();
  });

  it("keeps attach a direct action while picker rows get a chevron", () => {
    mountMenu();

    const attach = screen.getByRole("button", { name: "Attach files" });
    expect(attach.querySelector("svg.lucide-chevron-right")).toBeNull();
    const knowledge = screen.getByRole("button", { name: "Knowledge" });
    expect(knowledge.querySelector("svg.lucide-chevron-right")).not.toBeNull();
  });

  it("wraps arrow-key navigation in the mention variant and Enter dispatches the active row", () => {
    const onSelectItem = vi.fn();
    mountMenu({ variant: "mention", onSelectItem });

    const options = () => screen.getAllByRole("option");
    fireEvent.keyDown(document, { key: "ArrowUp" });
    expect(options()[7]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onSelectItem).toHaveBeenCalledTimes(1);
    expect(onSelectItem).toHaveBeenCalledWith("knowledge");
  });

  it("activates a mention row on hover", () => {
    mountMenu({ variant: "mention" });

    const options = screen.getAllByRole("option");
    fireEvent.mouseEnter(options[2]);
    expect(options[2]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveAttribute("aria-selected", "false");
  });

  it("relabels agents and widens attach in the resources variant", () => {
    mountMenu({ variant: "resources" });

    expect(
      screen.getByRole("button", { name: "Agent conversations" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Subagents" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Attach files" }).className,
    ).toContain("col-span-2");
  });
});
