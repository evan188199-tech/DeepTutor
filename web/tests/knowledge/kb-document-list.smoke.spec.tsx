import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KbDocumentList from "@/components/knowledge/KbDocumentList";
import type { KnowledgeBaseFile } from "@/features/knowledge/api/files";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  list: vi.fn(),
  createFolder: vi.fn(),
  deleteFile: vi.fn(),
  moveFile: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/features/knowledge/api/files", () => ({
  listKnowledgeBaseFiles: fixture.list,
  createKbFolder: fixture.createFolder,
  deleteKbFile: fixture.deleteFile,
  moveKbFile: fixture.moveFile,
}));

function entry(
  name: string,
  extra: Partial<KnowledgeBaseFile> = {},
): KnowledgeBaseFile {
  return { name, type: "file", size: 2048, modified: 1_700_000_000, ...extra };
}

function folder(name: string): KnowledgeBaseFile {
  return { name, type: "folder" };
}

const baseProps = {
  kbName: "papers",
  selectedFile: null,
  onSelect: vi.fn(),
  collapsed: false,
  onToggleCollapsed: vi.fn(),
};

function renderList(props: Partial<typeof baseProps> = {}) {
  const onSelect = vi.fn();
  const onToggleCollapsed = vi.fn();
  render(
    <KbDocumentList
      {...baseProps}
      onSelect={onSelect}
      onToggleCollapsed={onToggleCollapsed}
      {...props}
    />,
  );
  return { onSelect, onToggleCollapsed };
}

function fileCountBadge(): string | null {
  return screen.getByText("Files").nextElementSibling?.textContent ?? null;
}

beforeEach(() => {
  fixture.list.mockReset().mockResolvedValue([]);
  fixture.createFolder.mockReset().mockResolvedValue(undefined);
  fixture.deleteFile.mockReset().mockResolvedValue({ was_indexed: false });
  fixture.moveFile.mockReset().mockResolvedValue(undefined);
});

describe("KbDocumentList rendering states", () => {
  it("shows the loading skeleton while the file listing is in flight", async () => {
    fixture.list.mockImplementation(() => new Promise(() => {}));
    renderList();

    expect(await screen.findByText("Files")).toBeInTheDocument();
    expect(fixture.list).toHaveBeenCalledWith("papers", { force: false });
    expect(document.querySelectorAll(".animate-pulse")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("renders the empty state when the KB has no files or folders", async () => {
    renderList();

    expect(
      await screen.findByText("No files yet. Add one using the Add Documents tab."),
    ).toBeInTheDocument();
    expect(fileCountBadge()).toBe("0");
  });

  it("renders the error banner with retry and recovers after a forced reload", async () => {
    fixture.list
      .mockRejectedValueOnce(new Error("Kb files offline"))
      .mockResolvedValueOnce([entry("a.pdf")]);
    renderList();

    expect(await screen.findByText("Kb files offline")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("button", { name: "a.pdf" })).toBeInTheDocument();
    await waitFor(() =>
      expect(fixture.list).toHaveBeenNthCalledWith(2, "papers", { force: true }),
    );
  });

  it("surfaces non-Error rejections as text in the banner", async () => {
    fixture.list.mockRejectedValueOnce("boom-string");
    renderList();

    expect(await screen.findByText("boom-string")).toBeInTheDocument();
  });
});

describe("KbDocumentList tree and selection", () => {
  const tree = [
    entry("zeta.txt"),
    entry("Papers/b.md"),
    folder("Papers"),
    entry("alpha.pdf"),
  ];

  it("builds the tree with default-expanded folders and a file count badge", async () => {
    fixture.list.mockResolvedValue(tree);
    renderList();

    expect(
      await screen.findByRole("button", { name: "Papers/b.md" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "alpha.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "zeta.txt" })).toBeInTheDocument();
    expect(screen.getByText("Papers")).toBeInTheDocument();
    expect(fileCountBadge()).toBe("3");
  });

  it("selects a file via its row and toggles folder expansion", async () => {
    fixture.list.mockResolvedValue(tree);
    const { onSelect } = renderList();

    fireEvent.click(await screen.findByRole("button", { name: "zeta.txt" }));
    expect(onSelect).toHaveBeenCalledWith(tree[0]);

    fireEvent.click(screen.getByText("Papers"));
    expect(
      screen.queryByRole("button", { name: "Papers/b.md" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Papers"));
    expect(
      await screen.findByRole("button", { name: "Papers/b.md" }),
    ).toBeInTheDocument();
  });
});

describe("KbDocumentList row actions", () => {
  it("cancels a delete confirmation without calling the API", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf")]);
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "a.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete file" }));
    expect(screen.getByText("Delete?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Delete?")).not.toBeInTheDocument();
    expect(fixture.deleteFile).not.toHaveBeenCalled();
  });

  it("confirms a delete, clears a matching selection and force-reloads", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf")]);
    const { onSelect } = renderList({ selectedFile: "a.pdf" });

    fireEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() =>
      expect(fixture.deleteFile).toHaveBeenCalledWith("papers", "a.pdf"),
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
    await waitFor(() =>
      expect(fixture.list).toHaveBeenNthCalledWith(2, "papers", { force: true }),
    );
  });

  it("surfaces a failed delete in the error banner", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf")]);
    fixture.deleteFile.mockRejectedValueOnce(new Error("delete failed: 500"));
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByText("delete failed: 500")).toBeInTheDocument();
  });

  it("moves a root file into a listed folder from the move menu", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf"), folder("Papers")]);
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "Move to…" }));
    expect(screen.getByText("Move to")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Papers" }));

    await waitFor(() =>
      expect(fixture.moveFile).toHaveBeenCalledWith("papers", "a.pdf", "Papers"),
    );
    await waitFor(() =>
      expect(fixture.list).toHaveBeenNthCalledWith(2, "papers", { force: true }),
    );
  });

  it("offers Root for nested files and reports when no folders exist", async () => {
    fixture.list.mockResolvedValue([entry("Papers/b.md"), folder("Papers")]);
    renderList();

    const rowButton = await screen.findByRole("button", { name: "Papers/b.md" });
    const row = rowButton.closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Move to…" }));

    const root = screen.getByRole("button", { name: "/ Root" });
    fireEvent.click(root);
    await waitFor(() =>
      expect(fixture.moveFile).toHaveBeenCalledWith("papers", "Papers/b.md", ""),
    );
  });

  it("shows a no-folder hint in the move menu for a flat KB", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf")]);
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "Move to…" }));
    expect(screen.getByText("No folders yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "/ Root" })).not.toBeInTheDocument();
  });
});

describe("KbDocumentList folder creation", () => {
  it("creates a folder from the header form and refuses empty names", async () => {
    fixture.createFolder.mockResolvedValue(undefined);
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "New folder" }));
    const input = screen.getByPlaceholderText("Folder name");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();

    fireEvent.change(input, { target: { value: "Notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(fixture.createFolder).toHaveBeenCalledWith("papers", "Notes"),
    );
    await waitFor(() =>
      expect(fixture.list).toHaveBeenNthCalledWith(2, "papers", { force: true }),
    );
    expect(screen.queryByPlaceholderText("Folder name")).not.toBeInTheDocument();
  });
});

describe("KbDocumentList collapsed rail", () => {
  it("shows one icon button per file and forwards expand and select actions", async () => {
    fixture.list.mockResolvedValue([entry("a.pdf"), entry("b.md")]);
    const { onSelect, onToggleCollapsed } = renderList({ collapsed: true });

    expect(await screen.findByRole("button", { name: "a.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "b.md" })).toBeInTheDocument();
    expect(screen.queryByText("Files")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Refresh" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "b.md" }));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ name: "b.md", type: "file" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);
  });
});

describe("KbDocumentList refresh and scale", () => {
  it("forces a refetch when refreshKey is bumped", async () => {
    const view = render(
      <KbDocumentList
        {...baseProps}
        onSelect={vi.fn()}
        onToggleCollapsed={vi.fn()}
      />,
    );
    await waitFor(() => expect(fixture.list).toHaveBeenCalledTimes(1));

    view.rerender(
      <KbDocumentList
        {...baseProps}
        refreshKey={1}
        onSelect={vi.fn()}
        onToggleCollapsed={vi.fn()}
      />,
    );
    await waitFor(() => expect(fixture.list).toHaveBeenCalledTimes(2));
    expect(fixture.list).toHaveBeenNthCalledWith(1, "papers", { force: false });
    expect(fixture.list).toHaveBeenNthCalledWith(2, "papers", { force: true });
  });

  it("renders many documents and a very long filename with truncation classes", async () => {
    const longName = `${"L".repeat(180)}.pdf`;
    const many = Array.from({ length: 40 }, (_, i) =>
      entry(`doc-${String(i).padStart(2, "0")}.pdf`),
    );
    fixture.list.mockResolvedValue([...many, entry(longName)]);
    renderList();

    const longButton = await screen.findByRole("button", { name: longName });
    expect(longButton).toBeInTheDocument();
    const label = within(longButton).getByText(longName);
    expect(label.className).toContain("truncate");

    for (const item of many) {
      expect(screen.getByRole("button", { name: item.name })).toBeInTheDocument();
    }
    expect(fileCountBadge()).toBe("41");
  });
});
