import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import KnowledgeSelector from "@/components/chat/home/KnowledgeSelector";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("KnowledgeSelector", () => {
  it("labels the collapsed scope from zero, one and many selections", () => {
    const bases = [{ name: "Alpha KB" }, { name: "Beta KB" }];
    const { rerender } = render(
      <KnowledgeSelector
        knowledgeBases={bases}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Knowledge")).toBeInTheDocument();

    rerender(
      <KnowledgeSelector
        knowledgeBases={bases}
        selected={["Alpha KB"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Alpha KB")).toBeInTheDocument();

    rerender(
      <KnowledgeSelector
        knowledgeBases={bases}
        selected={["Alpha KB", "Beta KB"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("2 knowledge bases")).toBeInTheDocument();
  });

  it("opens the menu and marks active bases with aria-pressed", () => {
    render(
      <KnowledgeSelector
        knowledgeBases={[
          { name: "Alpha KB" },
          { name: "Beta KB", provenance_label: "assigned" },
        ]}
        selected={["Beta KB"]}
        onToggle={vi.fn()}
      />,
    );
    const trigger = screen.getByRole("button", {
      name: "Select knowledge bases",
    });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: /Alpha KB/ }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: /Beta KB/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("toggling a base reports its resource ref and keeps the menu open", () => {
    const onToggle = vi.fn();
    render(
      <KnowledgeSelector
        knowledgeBases={[
          { id: "account:kb:corp", name: "Corp KB" },
          { name: "Loose KB" },
        ]}
        selected={[]}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Corp KB" }));
    expect(onToggle).toHaveBeenCalledWith("account:kb:corp");
    fireEvent.click(screen.getByRole("button", { name: "Loose KB" }));
    expect(onToggle).toHaveBeenCalledWith("Loose KB");
    expect(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("shows the empty state when no bases are configured", () => {
    render(
      <KnowledgeSelector
        knowledgeBases={[]}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    );
    expect(
      screen.getByText("No knowledge bases available"),
    ).toBeInTheDocument();
  });

  it("filters the list from the embedded search input", () => {
    render(
      <KnowledgeSelector
        embedded
        knowledgeBases={[{ name: "Repo KB" }, { name: "Docs KB" }]}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Select knowledge bases" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "repo" },
    });
    expect(screen.getByRole("button", { name: "Repo KB" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Docs KB" }),
    ).not.toBeInTheDocument();
  });
});
