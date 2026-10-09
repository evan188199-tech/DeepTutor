import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import FileDropZone from "@/components/knowledge/FileDropZone";
import type { KnowledgeUploadPolicy } from "@/lib/knowledge-helpers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options
        ? key.replace(
            /\{\{(\w+)\}\}/g,
            (_match: string, name: string) => String(options[name]),
          )
        : key,
  }),
}));

const POLICY: KnowledgeUploadPolicy = {
  extensions: [".pdf", ".md"],
  accept: ".pdf,.md",
  max_file_size_bytes: 1024 * 1024,
};

const pdfFile = (name = "doc.pdf") =>
  new File(["%PDF-1.4"], name, { type: "application/pdf" });

const textFile = (name = "notes.txt") =>
  new File(["hello"], name, { type: "text/plain" });

const makeDataTransfer = (files: File[], types: string[] = ["Files"]) => ({
  types,
  items: files.map((file) => ({
    kind: "file",
    getAsFile: () => file,
  })),
  files,
  dropEffect: "copy",
});

function Harness({
  initial = [],
  policy = POLICY,
  onChange,
}: {
  initial?: File[];
  policy?: KnowledgeUploadPolicy;
  onChange?: (files: File[]) => void;
}) {
  const [files, setFiles] = useState<File[]>(initial);
  return (
    <FileDropZone
      files={files}
      onChange={(next) => {
        setFiles(next);
        onChange?.(next);
      }}
      uploadPolicy={policy}
    />
  );
}

const dropZone = () => screen.getByRole("button", { name: /Choose files/ });

describe("FileDropZone", () => {
  it("counts nested dragenter/dragleave so the highlight survives child hops and resets once", () => {
    render(<Harness />);
    const zone = dropZone();
    const label = within(zone).getByText("Choose files...");
    const inner = label.parentElement as HTMLElement;
    const dataTransfer = makeDataTransfer([pdfFile()]);

    fireEvent.dragLeave(zone, { dataTransfer });
    expect(within(zone).getByText("Choose files...")).toBeInTheDocument();

    fireEvent.dragEnter(zone, { dataTransfer });
    expect(
      within(zone).getByText("Drop files to add them"),
    ).toBeInTheDocument();
    expect(within(zone).getByText("1 files detected")).toBeInTheDocument();

    fireEvent.dragEnter(inner, { dataTransfer });
    fireEvent.dragLeave(inner, { dataTransfer });
    expect(
      within(zone).getByText("Drop files to add them"),
    ).toBeInTheDocument();

    fireEvent.dragLeave(zone, { dataTransfer });
    expect(within(zone).getByText("Choose files...")).toBeInTheDocument();
    expect(
      within(zone).queryByText("Drop files to add them"),
    ).not.toBeInTheDocument();
  });

  it("ignores drag events whose dataTransfer does not carry files", () => {
    render(<Harness />);
    const zone = dropZone();
    const dataTransfer = makeDataTransfer([], ["text/plain"]);

    fireEvent.dragEnter(zone, { dataTransfer });
    fireEvent.dragOver(zone, { dataTransfer });

    expect(within(zone).getByText("Choose files...")).toBeInTheDocument();
    expect(
      within(zone).queryByText("Drop files to add them"),
    ).not.toBeInTheDocument();
  });

  it("previews the dragged file count and merges every dropped file with the selection", () => {
    const onChange = vi.fn();
    const existing = pdfFile("existing.pdf");
    const incoming = [pdfFile("doc.pdf"), pdfFile("doc2.pdf")];
    render(<Harness initial={[existing]} onChange={onChange} />);
    const zone = screen
      .getAllByText("1 files ready")[0]
      .closest("button") as HTMLElement;
    const dataTransfer = makeDataTransfer(incoming);

    fireEvent.dragEnter(zone, { dataTransfer });
    expect(within(zone).getByText("2 files detected")).toBeInTheDocument();

    fireEvent.drop(zone, { dataTransfer });

    expect(onChange).toHaveBeenCalledTimes(1);
    const merged = onChange.mock.calls[0][0] as File[];
    expect(merged).toHaveLength(3);
    expect(merged.map((file) => file.name)).toEqual([
      "existing.pdf",
      "doc.pdf",
      "doc2.pdf",
    ]);
    expect(within(zone).getByText("3 files ready")).toBeInTheDocument();
    expect(
      within(zone).queryByText("Drop files to add them"),
    ).not.toBeInTheDocument();
  });

  it("flags unsupported dragged types during the drag preview and after the drop", () => {
    const onChange = vi.fn();
    const incoming = [textFile(), pdfFile()];
    render(<Harness onChange={onChange} />);
    const zone = dropZone();
    const dataTransfer = makeDataTransfer(incoming);

    fireEvent.dragEnter(zone, { dataTransfer });
    expect(
      within(zone).getByText("Some dragged files are not supported"),
    ).toBeInTheDocument();
    expect(within(zone).getByText("2 files detected")).toBeInTheDocument();

    fireEvent.drop(zone, { dataTransfer });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toHaveLength(2);
    expect(within(zone).getByText("1 invalid files")).toBeInTheDocument();
    expect(screen.getByText("1 ready, 1 will be skipped")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Supported")).toBeInTheDocument();
  });
});
