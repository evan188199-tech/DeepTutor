import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DocxPreview from "@/components/chat/preview/previewers/DocxPreview";
import FallbackPreview from "@/components/chat/preview/previewers/FallbackPreview";
import SvgPreview from "@/components/chat/preview/previewers/SvgPreview";
import TextPreview from "@/components/chat/preview/previewers/TextPreview";
import XlsxPreview from "@/components/chat/preview/previewers/XlsxPreview";

const fixture = vi.hoisted(() => {
  const apiFetch = vi.fn();
  const renderAsync = vi.fn();
  const exceljs = {
    queue: [] as unknown[],
    workbooks: [] as Array<{
      sheets: unknown[];
      worksheets: unknown[];
      xlsx: { load: () => Promise<void> };
    }>,
    Workbook: class {
      sheets: unknown[] = [];
      xlsx: { load: () => Promise<void> };
      constructor() {
        exceljs.workbooks.push(this as unknown as {
          sheets: unknown[];
          worksheets: unknown[];
          xlsx: { load: () => Promise<void> };
        });
        this.xlsx = {
          load: async () => {
            const spec = exceljs.queue.shift();
            if (spec instanceof Error) throw spec;
            this.sheets = (spec as unknown[]) ?? [];
          },
        };
      }
      get worksheets() {
        return this.sheets;
      }
    },
  };
  return { apiFetch, renderAsync, exceljs };
});

vi.mock("@/lib/api", () => ({ apiFetch: fixture.apiFetch }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("exceljs", () => ({ default: { Workbook: fixture.exceljs.Workbook } }));
vi.mock("docx-preview", () => ({ renderAsync: fixture.renderAsync }));
vi.mock("@/components/common/RichCodeBlock", () => ({
  default: ({ raw, lang }: { raw: string; lang: string }) => (
    <pre data-testid="rich-code-block" data-lang={lang}>
      {raw}
    </pre>
  ),
}));

interface MockSheet {
  name: string;
  columnCount: number;
  rows: string[][];
}

function sheet(name: string, rows: string[][], columnCount?: number): MockSheet {
  return { name, columnCount: columnCount ?? rows[0]?.length ?? 0, rows };
}

function sheetNode(spec: MockSheet) {
  return {
    name: spec.name,
    columnCount: spec.columnCount,
    eachRow: (
      _opts: unknown,
      visit: (
        row: { getCell: (column: number) => { text: string } },
        rowNumber: number,
      ) => void,
    ) => {
      spec.rows.forEach((cells, index) => {
        visit(
          { getCell: (column: number) => ({ text: cells[column - 1] ?? "" }) },
          index + 1,
        );
      });
    },
  };
}

function bytesResponse(
  body: ArrayBuffer | string,
  {
    ok = true,
    status = 200,
    contentLength = null as string | null,
  }: { ok?: boolean; status?: number; contentLength?: string | null } = {},
): Response {
  const buffer =
    body instanceof ArrayBuffer
      ? body
      : new TextEncoder().encode(body).buffer as ArrayBuffer;
  return {
    ok,
    status,
    headers: {
      get: (name: string) => (name === "content-length" ? contentLength : null),
    },
    arrayBuffer: async () => buffer,
    text: async () => new TextDecoder().decode(buffer),
  } as unknown as Response;
}

const decoder = new TextDecoder();

function arrayBufferOf(text: string): ArrayBuffer {
  // Built with the test realm's Uint8Array so the buffer satisfies
  // `expect.any(ArrayBuffer)` inside the jsdom environment.
  const view = new Uint8Array(
    Array.from(text, (ch) => ch.charCodeAt(0) & 0xff),
  );
  return view.buffer as ArrayBuffer;
}

const observers: Array<{ resize: () => void; observed: Element[]; disconnect: ReturnType<typeof vi.fn> }> = [];

beforeEach(() => {
  fixture.exceljs.queue.length = 0;
  fixture.exceljs.workbooks.length = 0;
  observers.length = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect = vi.fn();
      observed: Element[] = [];
      constructor(resize: () => void) {
        observers.push({ resize, observed: this.observed, disconnect: this.disconnect });
      }
      observe(target: Element) {
        this.observed.push(target);
      }
      unobserve() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SvgPreview", () => {
  it("renders the served file as a plain img element", () => {
    render(
      <SvgPreview url="/files/outputs/diagram.svg" filename="diagram.svg" />,
    );

    const image = screen.getByRole("img", { name: "diagram.svg" });
    expect(image).toHaveAttribute("src", "/files/outputs/diagram.svg");
  });
});

describe("FallbackPreview", () => {
  it("offers the Download CTA for a stored file of an unsupported type", () => {
    render(
      <FallbackPreview filename="model.bin" url="/files/outputs/model.bin" />,
    );

    expect(screen.getByText("model.bin")).toBeInTheDocument();
    expect(
      screen.getByText("Preview is not available for this file type."),
    ).toBeInTheDocument();
    const download = screen.getByRole("link", { name: "Download" });
    expect(download).toHaveAttribute("href", "/files/outputs/model.bin");
    expect(download).toHaveAttribute("download", "model.bin");
  });

  it("explains that a legacy attachment's original file was never stored", () => {
    render(
      <FallbackPreview
        filename="old-notes.pages"
        url={null}
        reason="legacy"
      />,
    );

    expect(screen.getByText("old-notes.pages")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Original file is not stored (sent before preview was supported).",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
  });
});

describe("TextPreview", () => {
  it("shows the loading state while the source is being fetched", () => {
    fixture.apiFetch.mockReturnValue(new Promise(() => {}));
    render(
      <TextPreview url="/files/outputs/notes.txt" filename="notes.txt" />,
    );

    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
    expect(fixture.apiFetch).toHaveBeenCalledWith(
      "/files/outputs/notes.txt",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("renders a recognised code file through the syntax-highlighted block", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse('print("hello")\n'),
    );

    render(<TextPreview url="/files/outputs/app.py" filename="app.py" />);

    const block = await screen.findByTestId("rich-code-block");
    expect(block).toHaveAttribute("data-lang", "python");
    expect(block).toHaveTextContent('print("hello")');
  });

  it("renders a non-code file as plain text", async () => {
    fixture.apiFetch.mockResolvedValue(bytesResponse("meeting notes"));

    render(
      <TextPreview url="/files/outputs/notes.txt" filename="notes.txt" />,
    );

    const block = await screen.findByTestId("rich-code-block");
    expect(block).toHaveAttribute("data-lang", "text");
    expect(block).toHaveTextContent("meeting notes");
  });

  it("surfaces the fetch error message when the source is missing", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse("gone", { ok: false, status: 404 }),
    );

    render(<TextPreview url="/files/outputs/app.py" filename="app.py" />);

    expect(await screen.findByText("HTTP 404")).toBeInTheDocument();
    expect(screen.queryByTestId("rich-code-block")).toBeNull();
  });

  it("refuses to preview a text file over the size cap", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse("log line", {
        contentLength: String(9 * 1024 * 1024),
      }),
    );

    render(<TextPreview url="/files/outputs/huge.log" filename="huge.log" />);

    expect(
      await screen.findByText(
        "File is too large to preview as text. Use the Download button.",
      ),
    ).toBeInTheDocument();
  });
});

describe("DocxPreview", () => {
  it("renders the fetched document bytes via docx-preview and hides the loading overlay", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse(arrayBufferOf("PK\u0003\u0004 docx-bytes")),
    );
    fixture.renderAsync.mockImplementation(
      async (_buffer: ArrayBuffer, container: HTMLElement) => {
        await new Promise((resolve) => setTimeout(resolve, 0));
        container.innerHTML =
          '<div class="docx-wrapper"><section class="docx">Quarterly report</section></div>';
      },
    );

    const { unmount } = render(
      <DocxPreview url="/files/outputs/report.docx" />,
    );

    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
    expect(
      await screen.findByText("Quarterly report"),
    ).toBeInTheDocument();
    expect(fixture.renderAsync).toHaveBeenCalledWith(
      expect.any(ArrayBuffer),
      expect.any(HTMLElement),
      undefined,
      expect.objectContaining({ className: "docx", breakPages: true }),
    );
    expect(decoder.decode(fixture.renderAsync.mock.calls[0][0])).toContain(
      "docx-bytes",
    );
    expect(screen.queryByText("Loading preview…")).toBeNull();

    unmount();
    expect(observers[0]?.disconnect).toHaveBeenCalled();
  });

  it("falls back to the Download hint when the document bytes fail to load", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse("gone", { ok: false, status: 500 }),
    );

    render(<DocxPreview url="/files/outputs/report.docx" />);

    expect(
      await screen.findByText(
        "Couldn't render this document — use Download to open it.",
      ),
    ).toBeInTheDocument();
    expect(fixture.renderAsync).not.toHaveBeenCalled();
  });

  it("falls back to the Download hint when the renderer throws", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse(arrayBufferOf("PK\u0003\u0004 docx-bytes")),
    );
    fixture.renderAsync.mockRejectedValue(new Error("corrupt document"));

    render(<DocxPreview url="/files/outputs/report.docx" />);

    expect(
      await screen.findByText(
        "Couldn't render this document — use Download to open it.",
      ),
    ).toBeInTheDocument();
  });
});

describe("XlsxPreview", () => {
  it("renders the active worksheet and switches sheets from the tab strip", async () => {
    fixture.apiFetch.mockResolvedValue(bytesResponse(arrayBufferOf("xlsx")));
    fixture.exceljs.queue.push([
      sheetNode(sheet("Budget", [["Month", "Spend"], ["Jan", "42"]])),
      sheetNode(sheet("Notes", [["todo: reconcile"]])),
    ]);

    render(<XlsxPreview url="/files/outputs/budget.xlsx" />);

    expect(await screen.findByText("Spend")).toBeInTheDocument();
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.queryByText("todo: reconcile")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Notes" }));

    expect(await screen.findByText("todo: reconcile")).toBeInTheDocument();
    expect(screen.queryByText("Spend")).toBeNull();
    expect(fixture.apiFetch).toHaveBeenCalledWith(
      "/files/outputs/budget.xlsx",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("flags truncation when a worksheet exceeds the column cap", async () => {
    fixture.apiFetch.mockResolvedValue(bytesResponse(arrayBufferOf("xlsx")));
    const wideRow = Array.from({ length: 61 }, (_unused, index) => `c${index}`);
    fixture.exceljs.queue.push([
      sheetNode(sheet("Wide", [wideRow], 61)),
    ]);

    render(<XlsxPreview url="/files/outputs/wide.xlsx" />);

    expect(
      await screen.findByText(
        "Large sheet — preview truncated. Download for the full file.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("c59")).toBeInTheDocument();
    expect(screen.queryByText("c60")).toBeNull();
  });

  it("shows the empty state for a workbook without sheets", async () => {
    fixture.apiFetch.mockResolvedValue(bytesResponse(arrayBufferOf("xlsx")));
    fixture.exceljs.queue.push([]);

    render(<XlsxPreview url="/files/outputs/empty.xlsx" />);

    expect(
      await screen.findByText("This workbook has no sheets to preview."),
    ).toBeInTheDocument();
  });

  it("falls back to the Download hint when parsing fails", async () => {
    fixture.apiFetch.mockResolvedValue(bytesResponse(arrayBufferOf("xlsx")));
    fixture.exceljs.queue.push(new Error("not a workbook"));

    render(<XlsxPreview url="/files/outputs/broken.xlsx" />);

    expect(
      await screen.findByText(
        "Couldn't render this spreadsheet — use Download to open it.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Loading preview…")).toBeNull();
    });
  });

  it("falls back to the Download hint when the workbook bytes fail to load", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse("gone", { ok: false, status: 500 }),
    );

    render(<XlsxPreview url="/files/outputs/broken.xlsx" />);

    expect(
      await screen.findByText(
        "Couldn't render this spreadsheet — use Download to open it.",
      ),
    ).toBeInTheDocument();
    expect(fixture.exceljs.workbooks).toHaveLength(0);
  });

  it("refuses to preview a workbook over the byte cap", async () => {
    fixture.apiFetch.mockResolvedValue(
      bytesResponse("spreadsheet bytes", {
        contentLength: String(26 * 1024 * 1024),
      }),
    );

    render(<XlsxPreview url="/files/outputs/huge.xlsx" />);

    expect(
      await screen.findByText(
        "Couldn't render this spreadsheet — use Download to open it.",
      ),
    ).toBeInTheDocument();
  });
});
