import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KbFilesTab from "@/components/knowledge/KbFilesTab";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";
import type { KnowledgeBaseFile } from "@/features/knowledge/api/files";
import type { TaskState } from "@/hooks/useKnowledgeProgress";

const children = vi.hoisted(() => ({
  KbDocumentList: vi.fn(),
  KbFilePreview: vi.fn(),
  KbVisualCoverage: vi.fn(),
}));

vi.mock("@/components/knowledge/KbDocumentList", () => ({
  default: children.KbDocumentList,
}));
vi.mock("@/components/knowledge/KbFilePreview", () => ({
  default: children.KbFilePreview,
}));
vi.mock("@/components/knowledge/KbVisualCoverage", () => ({
  default: children.KbVisualCoverage,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

interface DocumentListProps {
  kbName: string;
  refreshKey: number;
  selectedFile: string | null;
  onSelect: (file: KnowledgeBaseFile | null) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

interface FilePreviewProps {
  source: {
    filename: string;
    mimeType?: string;
    url: string;
    extractedTextUrl: string;
    size?: number;
    id: string;
  } | null;
  fileListCollapsed?: boolean;
  onToggleFileList?: () => void;
}

interface VisualCoverageProps {
  kbName: string;
  sourcePath: string;
  revision: number;
}

const kb: KnowledgeBase = { name: "papers", id: "kb-1" };

const task = (executing: boolean): TaskState => ({
  taskId: "t1",
  kind: "upload",
  label: "upload",
  logs: [],
  executing,
  error: null,
});

const pdf = (name: string): KnowledgeBaseFile => ({
  name,
  type: "file",
  size: 2048,
  mime_type: "application/pdf",
});

function lastCall<Props>(mock: { mock: { lastCall?: unknown[] } }): Props {
  const call = mock.mock.lastCall;
  expect(call, "expected the child component to have rendered").toBeDefined();
  return call![0] as Props;
}

function stubDocumentList(pick: () => KnowledgeBaseFile | null) {
  children.KbDocumentList.mockImplementation((props: DocumentListProps) => (
    <>
      <button
        data-testid="doc-list-toggle"
        onClick={() => props.onToggleCollapsed()}
      >
        toggle-list
      </button>
      <button data-testid="pick-file" onClick={() => props.onSelect(pick())}>
        pick
      </button>
    </>
  ));
}

beforeEach(() => {
  children.KbFilePreview.mockImplementation((props: FilePreviewProps) => (
    <button data-testid="preview-toggle" onClick={() => props.onToggleFileList?.()}>
      toggle-preview
    </button>
  ));
  children.KbVisualCoverage.mockImplementation(
    (props: VisualCoverageProps) => (
      <div data-testid="visual-coverage">
        {props.sourcePath}
      </div>
    ),
  );
});

afterEach(cleanup);

describe("KbFilesTab", () => {
  it("renders the file list beside an empty preview pane before any selection", () => {
    stubDocumentList(() => null);
    render(<KbFilesTab kb={kb} />);

    const list = lastCall<DocumentListProps>(children.KbDocumentList);
    expect(list.kbName).toBe("papers");
    expect(list.selectedFile).toBeNull();
    expect(list.collapsed).toBe(false);
    expect(list.refreshKey).toBe(1);

    const preview = lastCall<FilePreviewProps>(children.KbFilePreview);
    expect(preview.source).toBeNull();
    expect(preview.fileListCollapsed).toBe(false);
    expect(screen.queryByTestId("visual-coverage")).not.toBeInTheDocument();
  });

  it("mounts the lazy visual coverage entry and preview source once a file is picked", () => {
    let pick: KnowledgeBaseFile | null = null;
    stubDocumentList(() => pick);
    render(<KbFilesTab kb={kb} />);
    expect(screen.queryByTestId("visual-coverage")).not.toBeInTheDocument();

    pick = pdf("docs/curve fit.pdf");
    fireEvent.click(screen.getByTestId("pick-file"));

    const preview = lastCall<FilePreviewProps>(children.KbFilePreview);
    expect(preview.source).toEqual({
      filename: "docs/curve fit.pdf",
      mimeType: "application/pdf",
      url: "/api/knowledge-bases/papers/files/docs/curve%20fit.pdf",
      extractedTextUrl:
        "/api/knowledge-bases/papers/file-preview-text/docs/curve%20fit.pdf",
      size: 2048,
      id: "papers/docs/curve fit.pdf",
    });

    const coverage = lastCall<VisualCoverageProps>(children.KbVisualCoverage);
    expect(coverage.kbName).toBe("papers");
    expect(coverage.sourcePath).toBe("docs/curve fit.pdf");
    expect(coverage.revision).toBe(listRefreshKey());
    expect(screen.getByTestId("visual-coverage")).toHaveTextContent(
      "docs/curve fit.pdf",
    );
  });

  it("remounts the coverage panel per picked file and clears it on deselection", () => {
    let pick: KnowledgeBaseFile | null = null;
    stubDocumentList(() => pick);
    render(<KbFilesTab kb={kb} />);

    pick = pdf("a.pdf");
    fireEvent.click(screen.getByTestId("pick-file"));
    expect(screen.getByTestId("visual-coverage")).toHaveTextContent("a.pdf");

    pick = pdf("b.epub");
    fireEvent.click(screen.getByTestId("pick-file"));
    expect(screen.queryByText("a.pdf")).not.toBeInTheDocument();
    expect(screen.getByTestId("visual-coverage")).toHaveTextContent("b.epub");
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).selectedFile,
    ).toBe("b.epub");

    pick = null;
    fireEvent.click(screen.getByTestId("pick-file"));
    expect(screen.queryByTestId("visual-coverage")).not.toBeInTheDocument();
    expect(
      lastCall<FilePreviewProps>(children.KbFilePreview).source,
    ).toBeNull();
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).selectedFile,
    ).toBeNull();
  });

  it("shares the collapse state between the file list and the preview pane", () => {
    stubDocumentList(() => null);
    render(<KbFilesTab kb={kb} />);

    fireEvent.click(screen.getByTestId("doc-list-toggle"));
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).collapsed,
    ).toBe(true);
    expect(
      lastCall<FilePreviewProps>(children.KbFilePreview).fileListCollapsed,
    ).toBe(true);
    expect(
      window.localStorage.getItem("panel:knowledge-file-list:collapsed"),
    ).toBe("1");

    fireEvent.click(screen.getByTestId("preview-toggle"));
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).collapsed,
    ).toBe(false);
    expect(
      window.localStorage.getItem("panel:knowledge-file-list:collapsed"),
    ).toBe("0");
  });

  it("bumps the list refresh key only when an active task settles", () => {
    stubDocumentList(() => null);
    const view = render(<KbFilesTab kb={kb} task={task(true)} />);
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).refreshKey,
    ).toBe(0);

    view.rerender(<KbFilesTab kb={kb} task={task(false)} />);
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).refreshKey,
    ).toBe(1);

    view.rerender(<KbFilesTab kb={kb} task={task(false)} />);
    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).refreshKey,
    ).toBe(1);
  });

  it("addresses an assigned knowledge base by its workspace id", () => {
    stubDocumentList(() => null);
    render(
      <KbFilesTab
        kb={{ name: "papers", id: "workspace:kb-9", assigned: true }}
      />,
    );

    expect(
      lastCall<DocumentListProps>(children.KbDocumentList).kbName,
    ).toBe("workspace:kb-9");
  });
});

function listRefreshKey(): number {
  return lastCall<DocumentListProps>(children.KbDocumentList).refreshKey;
}
