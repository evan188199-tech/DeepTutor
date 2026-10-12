import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KbFilePreview from "@/components/knowledge/KbFilePreview";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";

const fixture = vi.hoisted(() => ({
  officePdfProps: [] as Array<{
    url?: string | null;
    filename?: string;
    fallback?: ReactElement;
  }>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => `http://localhost${path}`,
}));

// next/dynamic in this component only defers renderer imports; resolve the
// (already mocked) previewer modules through React.lazy so assertions can
// await the rendered stub deterministically.
vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (
      loader: () => Promise<{
        default: React.ComponentType<Record<string, unknown>>;
      }>,
      options?: { loading?: React.ComponentType },
    ) => {
      const Lazy = React.lazy(loader);
      const Loading = options?.loading;
      function DynamicMock(props: Record<string, unknown>) {
        return (
          <React.Suspense fallback={Loading ? <Loading /> : null}>
            <Lazy {...props} />
          </React.Suspense>
        );
      }
      // Tag the wrapper with the wrapped renderer's mock name so tests can
      // identify which dynamic() a fallback element was built from.
      void loader().then((mod) => {
        (DynamicMock as { mockName?: string }).mockName =
          (mod.default as { mockName?: string }).mockName ?? "dynamic";
      });
      return DynamicMock;
    },
  };
});

vi.mock("@/components/chat/preview/previewers/PdfPreview", () => {
  const PdfPreview = (props: { url?: string | null }) => (
    <div data-testid="pdf-preview" data-url={props.url ?? ""} />
  );
  return { default: PdfPreview };
});

vi.mock("@/components/chat/preview/previewers/ImagePreview", () => {
  const ImagePreview = (props: { url?: string | null }) => (
    <div data-testid="image-preview" data-url={props.url ?? ""} />
  );
  return { default: ImagePreview };
});

vi.mock("@/components/chat/preview/previewers/VideoPreview", () => {
  const VideoPreview = (props: { url?: string | null }) => (
    <div data-testid="video-preview" data-url={props.url ?? ""} />
  );
  return { default: VideoPreview };
});

vi.mock("@/components/chat/preview/previewers/SvgPreview", () => {
  const SvgPreview = (props: { url?: string | null }) => (
    <div data-testid="svg-preview" data-url={props.url ?? ""} />
  );
  return { default: SvgPreview };
});

vi.mock("@/components/chat/preview/previewers/MarkdownPreview", () => {
  const MarkdownPreview = (props: { url?: string | null }) => (
    <div data-testid="markdown-preview" data-url={props.url ?? ""} />
  );
  return { default: MarkdownPreview };
});

vi.mock("@/components/chat/preview/previewers/TextPreview", () => {
  const TextPreview = (props: { url?: string | null }) => (
    <div data-testid="text-preview" data-url={props.url ?? ""} />
  );
  return { default: TextPreview };
});

vi.mock("@/components/chat/preview/previewers/DocxPreview", () => {
  const DocxPreviewMock = (props: { url?: string | null }) => (
    <div data-testid="docx-preview" data-url={props.url ?? ""} />
  );
  (DocxPreviewMock as unknown as { mockName: string }).mockName = "docx";
  return { default: DocxPreviewMock };
});

vi.mock("@/components/chat/preview/previewers/XlsxPreview", () => {
  const XlsxPreviewMock = (props: { url?: string | null }) => (
    <div data-testid="xlsx-preview" data-url={props.url ?? ""} />
  );
  (XlsxPreviewMock as unknown as { mockName: string }).mockName = "xlsx";
  return { default: XlsxPreviewMock };
});

vi.mock("@/components/chat/preview/previewers/OfficeTextPreview", () => {
  const OfficeTextPreviewMock = (props: {
    url?: string | null;
    extractedTextUrl?: string | null;
  }) => (
    <div
      data-testid="office-text-preview"
      data-url={props.url ?? ""}
      data-text-url={props.extractedTextUrl ?? ""}
    />
  );
  (OfficeTextPreviewMock as unknown as { mockName: string }).mockName =
    "office-text";
  return { default: OfficeTextPreviewMock };
});

vi.mock("@/components/chat/preview/previewers/OfficePdfPreview", () => {
  const OfficePdfPreview = (props: {
    url?: string | null;
    filename?: string;
    fallback?: ReactElement;
  }) => {
    fixture.officePdfProps.push(props);
    return (
      <div data-testid="office-pdf-preview" data-url={props.url ?? ""} />
    );
  };
  return { default: OfficePdfPreview };
});

vi.mock("@/components/chat/preview/previewers/FallbackPreview", () => {
  const FallbackPreview = (props: {
    url?: string | null;
    reason?: string;
  }) => (
    <div
      data-testid="fallback-preview"
      data-url={props.url ?? ""}
      data-reason={props.reason ?? ""}
    />
  );
  return { default: FallbackPreview };
});

const writeText = vi.fn();

beforeEach(() => {
  fixture.officePdfProps.length = 0;
  writeText.mockReset();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("KbFilePreview empty state", () => {
  it("shows guidance instead of a header when no source is selected", () => {
    render(<KbFilePreview source={null} />);

    expect(
      screen.getByText("Select a file to preview"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Pick any document from the list on the left to view it here without leaving the knowledge base.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Fullscreen")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Hide file list")).not.toBeInTheDocument();
  });

  it("offers a file-list toggle that follows the collapsed prop", () => {
    const onToggleFileList = vi.fn();
    const view = render(
      <KbFilePreview
        source={null}
        fileListCollapsed={false}
        onToggleFileList={onToggleFileList}
      />,
    );

    fireEvent.click(screen.getByLabelText("Hide file list"));
    expect(onToggleFileList).toHaveBeenCalledTimes(1);

    view.rerender(
      <KbFilePreview
        source={null}
        fileListCollapsed={true}
        onToggleFileList={onToggleFileList}
      />,
    );
    expect(screen.getByLabelText("Show file list")).toBeInTheDocument();
    expect(screen.queryByLabelText("Hide file list")).not.toBeInTheDocument();
  });
});

function mockNameOf(type: unknown): string | undefined {
  return (type as { mockName?: string }).mockName;
}

describe("KbFilePreview renderer routing", () => {
  it.each([
    ["pdf", { filename: "report.pdf", url: "/files/report.pdf" }, "pdf-preview"],
    [
      "image",
      { filename: "photo.png", url: "https://cdn.example.com/photo.png" },
      "image-preview",
    ],
    ["video", { filename: "clip.mp4", url: "/files/clip.mp4" }, "video-preview"],
    ["svg", { filename: "logo.svg", url: "/files/logo.svg" }, "svg-preview"],
    [
      "markdown",
      { filename: "readme.md", url: "/files/readme.md" },
      "markdown-preview",
    ],
    ["text", { filename: "notes.txt", url: "/files/notes.txt" }, "text-preview"],
    ["code", { filename: "main.py", url: "/files/main.py" }, "text-preview"],
    ["docx", { filename: "spec.docx", url: "/files/spec.docx" }, "office-pdf-preview"],
    ["xlsx", { filename: "sheet.xlsx", url: "/files/sheet.xlsx" }, "office-pdf-preview"],
    [
      "office-text",
      { filename: "deck.pptx", url: "/files/deck.pptx" },
      "office-pdf-preview",
    ],
    ["unknown", { filename: "data.bin", url: "/files/data.bin" }, "fallback-preview"],
  ])(
    "routes a %s source to the matching renderer",
    async (_kind, source, testid) => {
      render(<KbFilePreview source={source as FilePreviewSource} />);

      const node = await screen.findByTestId(testid);
      const expectedUrl = source.url.startsWith("http")
        ? source.url
        : `http://localhost${source.url}`;
      expect(node).toHaveAttribute("data-url", expectedUrl);
    },
  );

  it("renders base64-only images through a data URL", async () => {
    render(
      <KbFilePreview
        source={{ filename: "pic.jpg", base64: "QUJD", mimeType: "image/jpeg" }}
      />,
    );

    expect(await screen.findByTestId("image-preview")).toHaveAttribute(
      "data-url",
      "data:image/jpeg;base64,QUJD",
    );
  });

  it("falls back to the legacy notice when no URL can be resolved", async () => {
    render(
      <KbFilePreview
        source={{ filename: "legacy.bin", extractedText: "words" }}
      />,
    );

    expect(await screen.findByTestId("fallback-preview")).toHaveAttribute(
      "data-reason",
      "legacy",
    );
    expect(screen.queryByLabelText("Download")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Copy link")).not.toBeInTheDocument();
  });

  it("hands docx sources the office PDF renderer with a docx fallback", async () => {
    render(
      <KbFilePreview
        source={{ filename: "spec.docx", url: "/files/spec.docx" }}
      />,
    );

    await screen.findByTestId("office-pdf-preview");
    const props = fixture.officePdfProps.at(-1);
    const fallback = props?.fallback as ReactElement<{ url?: string }>;
    expect(mockNameOf(fallback?.type)).toBe("docx");
    expect(fallback?.props.url).toBe("http://localhost/files/spec.docx");
  });

  it("hands xlsx sources the office PDF renderer with an xlsx fallback", async () => {
    render(
      <KbFilePreview
        source={{ filename: "sheet.xlsx", url: "/files/sheet.xlsx" }}
      />,
    );

    await screen.findByTestId("office-pdf-preview");
    const props = fixture.officePdfProps.at(-1);
    const fallback = props?.fallback as ReactElement<{ url?: string }>;
    expect(mockNameOf(fallback?.type)).toBe("xlsx");
    expect(fallback?.props.url).toBe("http://localhost/files/sheet.xlsx");
  });

  it("wires extracted text and its resolved URL into the office-text fallback", async () => {
    render(
      <KbFilePreview
        source={{
          filename: "deck.pptx",
          url: "/files/deck.pptx",
          extractedText: "Slide words",
          extractedTextUrl: "/files/deck.txt",
        }}
      />,
    );

    await screen.findByTestId("office-pdf-preview");
    const props = fixture.officePdfProps.at(-1);
    expect(props?.url).toBe("http://localhost/files/deck.pptx");
    const fallback = props?.fallback as ReactElement<{
      extractedText?: string;
      extractedTextUrl?: string | null;
      url?: string | null;
    }>;
    expect(mockNameOf(fallback?.type)).toBe("office-text");
    expect(fallback?.props.extractedText).toBe("Slide words");
    expect(fallback?.props.extractedTextUrl).toBe(
      "http://localhost/files/deck.txt",
    );
    expect(fallback?.props.url).toBe("http://localhost/files/deck.pptx");
  });
});

describe("KbFilePreview header actions", () => {
  const pdfSource: FilePreviewSource = {
    filename: "report.pdf",
    url: "/files/report.pdf",
    size: 12288,
  };

  it("shows filename, kind/size label and a download link", async () => {
    render(<KbFilePreview source={pdfSource} />);

    await screen.findByTestId("pdf-preview");
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("PDF · 12.0 KB")).toBeInTheDocument();

    const download = screen.getByLabelText("Download");
    expect(download).toHaveAttribute("href", "http://localhost/files/report.pdf");
    expect(download).toHaveAttribute("download", "report.pdf");
  });

  it("renders the meta suffix slot next to the title", async () => {
    render(
      <KbFilePreview
        source={pdfSource}
        metaSuffix={<span data-testid="meta-chip">3 files</span>}
      />,
    );

    await screen.findByTestId("pdf-preview");
    expect(screen.getByTestId("meta-chip")).toHaveTextContent("3 files");
  });

  it("toggles fullscreen and leaves it on Escape", async () => {
    const view = render(<KbFilePreview source={pdfSource} />);
    await screen.findByTestId("pdf-preview");

    const root = view.container.firstElementChild as HTMLElement;
    expect(root.className).not.toContain("fixed inset-0");

    fireEvent.click(screen.getByLabelText("Fullscreen"));
    expect(root.className).toContain("fixed inset-0");
    expect(screen.getByLabelText("Exit fullscreen")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(root.className).not.toContain("fixed inset-0");
    expect(screen.getByLabelText("Fullscreen")).toBeInTheDocument();
  });

  it("copies the resolved URL and clears the indicator afterwards", async () => {
    writeText.mockResolvedValue(undefined);
    render(<KbFilePreview source={pdfSource} />);
    await screen.findByTestId("pdf-preview");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.click(screen.getByLabelText("Copy link"));
      });
      expect(writeText).toHaveBeenCalledWith(
        "http://localhost/files/report.pdf",
      );
      expect(
        document.querySelector("svg.text-emerald-500"),
      ).not.toBeNull();

      act(() => {
        vi.advanceTimersByTime(1500);
      });
      expect(document.querySelector("svg.text-emerald-500")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stays calm when the clipboard rejects the write", async () => {
    writeText.mockRejectedValue(new Error("clipboard denied"));
    render(<KbFilePreview source={pdfSource} />);
    await screen.findByTestId("pdf-preview");

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Copy link"));
    });
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(document.querySelector("svg.text-emerald-500")).toBeNull();
    expect(screen.getByLabelText("Copy link")).toBeInTheDocument();
  });
});
