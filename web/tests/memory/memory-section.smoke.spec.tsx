/**
 * Zero-coverage smoke tests for the web memory component layer:
 *   - components/memory/MemorySection.tsx (overview tabs, doc list/pane,
 *     L1 snapshot/changes/queries modes, edit/save/update callbacks)
 *   - components/memory/MemoryWorkbench.tsx (nav rail, view modes,
 *     edit/save, deep-link focus, footnote render preparation)
 *
 * Origin: web/evidence/web-test-gaps-20261007/summary.json zero list
 * (triage web-zero-triage-20261008 → AGEN-1188). Scope is the component
 * layer only — `lib/memory-graph.ts` pure functions are covered by
 * tests/lib/memory-graph.test.ts and deliberately not duplicated here.
 * All network access goes through the mocked `@/lib/api`.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import MemorySection from "@/components/memory/MemorySection";
import MemoryWorkbench from "@/components/memory/MemoryWorkbench";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  routerReplace: vi.fn(),
  scrollIntoView: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
  apiUrl: (url: string) => url,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
            String(opts[name] ?? ""),
          )
        : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (
      loader: () => Promise<{ default: React.ComponentType<unknown> }>,
    ) => {
      const Loaded = React.lazy(loader);
      const Dynamic = (props: Record<string, unknown>) =>
        React.createElement(
          React.Suspense,
          { fallback: null },
          React.createElement(Loaded, props),
        );
      return Dynamic;
    },
  };
});

// Stand-in for the real renderer: markdown links become anchors (so entity
// refs are clickable like in production prose output) while injected HTML
// (memory entry anchor spans) is kept verbatim, mirroring allowHtml.
vi.mock("@/components/common/MarkdownRenderer", async () => {
  const React = await import("react");
  return {
    default: (props: { content: string }) => {
      const html = props.content.replace(
        /\[([^\]]+)\]\(([^)\s]+)\)/g,
        '<a href="$2">$1</a>',
      );
      return React.createElement("div", {
        "data-testid": "markdown-stub",
        "data-content": props.content,
        dangerouslySetInnerHTML: { __html: html },
      });
    },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.routerReplace }),
}));

vi.mock("@/components/memory/MemoryRunPanel", async () => {
  const React = await import("react");
  return {
    default: (props: { docKey: string }) =>
      React.createElement("div", {
        "data-testid": "run-panel-stub",
        "data-doc-key": props.docKey,
      }),
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────

const ULID = "01H" + "Z".repeat(23);
const ENTRY = `m_${ULID}`;
const ISO = "2026-10-09T01:00:00Z";

const OVERVIEW = {
  docs: [
    { layer: "L2", key: "chat", exists: true, updated_at: ISO, entry_count: 3, backlog: 0 },
    { layer: "L2", key: "notebook", exists: true, updated_at: null, entry_count: 1, backlog: 2 },
    { layer: "L3", key: "recent", exists: true, updated_at: ISO, entry_count: 2, backlog: 0 },
    { layer: "L3", key: "preferences", exists: false, updated_at: null, entry_count: 0, backlog: 0 },
  ],
  backups: [],
};

const CHAT_DOC = "Note the discussion in chat:sess-42 for context.";
const CHAT_DOC_LINKIFIED =
  "Note the discussion in [chat:sess-42](#entity-chat__sess-42) for context.";

const CHAT_SNAPSHOT = {
  surface: "chat",
  entities: [
    { id: "sess-42", label: "Session 42", ts: ISO, content: "Discussed memory graphs.", metadata: {}, fingerprint: "f1" },
    { id: "sess-43", label: "Session 43", ts: ISO, content: "Quiz review.", metadata: {}, fingerprint: "f2" },
  ],
  last_refresh: ISO,
  pending_changes: [
    { ts: ISO, kind: "added", entity_id: "sess-43", label: "Session 43", prev_fingerprint: null, new_fingerprint: "f2" },
  ],
};

const CHAT_CHANGES = {
  surface: "chat",
  changes: [
    { ts: ISO, kind: "modified", entity_id: "sess-42", label: "Session 42", prev_fingerprint: "f0", new_fingerprint: "f1" },
  ],
};

const KB_QUERIES = {
  surface: "kb",
  events: [
    { id: "q1", ts: ISO, surface: "kb", kind: "kb_query", payload: { kb_name: "mykb", query: "what is memory" }, session_id: null, turn_id: null },
  ],
};

const REFRESH_CHANGES = {
  changes: [
    { ts: ISO, kind: "added", entity_id: "sess-44", label: "Session 44", prev_fingerprint: null, new_fingerprint: "f3" },
  ],
};

const L2_DOC = [
  "## Chat memory",
  `* discussed graphs <!--${ENTRY}-->`,
  "[^1]: chat:sess-42",
  `[^2]: ${ENTRY}`,
].join("\n");

const L3_DOC = ["## Scope", "[^1]: notebook", `[^2]: ${ENTRY}`, "[^3]: notasurface"].join("\n");

const L2_LINES = {
  lines: [
    { number: 1, kind: "title", text: "## Chat memory", entry_id: null, section: null },
    { number: 2, kind: "bullet", text: "* discussed graphs", entry_id: ENTRY, section: "Chat memory" },
  ],
};

// ── Network stubs ────────────────────────────────────────────────────

interface FakeResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  body: ReadableStream<Uint8Array> | null;
}

function jsonResponse(data: unknown, body: ReadableStream<Uint8Array> | null = null): FakeResponse {
  return { ok: true, status: 200, json: async () => data, body };
}

type RouteHandler = () => unknown;

function installRoutes(routes: Record<string, RouteHandler>) {
  mocks.fetch.mockImplementation((url: string) => {
    const handler = routes[url];
    if (!handler) throw new Error(`Unexpected fetch in test: ${url}`);
    return handler();
  });
}

/** Wrap the installed routes so PUT requests are captured for assertions. */
function capturePut(putCalls: Array<{ url: string; init?: RequestInit }>) {
  const routes = mocks.fetch.getMockImplementation() as (url: string) => unknown;
  mocks.fetch.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      putCalls.push({ url, init });
      return jsonResponse({});
    }
    return routes(url);
  });
}

/**
 * Clicks that trigger fetches must settle inside act, otherwise the async
 * state updates land outside act and are dropped by the act-environment
 * guard in tests/setup/rendered.ts.
 */
async function clickAsync(element: Element) {
  await act(async () => {
    fireEvent.click(element);
  });
}

function baseRoutes(overrides: Record<string, RouteHandler> = {}) {
  return {
    "/api/memory/overview": () => jsonResponse(OVERVIEW),
    "/api/memory/doc/L2/chat": () => jsonResponse({ layer: "L2", key: "chat", content: CHAT_DOC }),
    "/api/memory/doc/L2/notebook": () => jsonResponse({ layer: "L2", key: "notebook", content: "" }),
    "/api/memory/doc/L3/recent": () => jsonResponse({ layer: "L3", key: "recent", content: "recent body" }),
    "/api/memory/doc/L3/preferences": () => jsonResponse({ layer: "L3", key: "preferences", content: "" }),
    "/api/memory/doc/L3/scope": () => jsonResponse({ layer: "L3", key: "scope", content: L3_DOC }),
    "/api/memory/doc/L3/scope/lines": () => jsonResponse({ lines: [] }),
    "/api/memory/snapshot/notebook": () => jsonResponse({ surface: "notebook", entities: [], last_refresh: null, pending_changes: [] }),
    "/api/memory/snapshot/notebook/changes": () => jsonResponse({ surface: "notebook", changes: [] }),
    "/api/memory/snapshot/chat": () => jsonResponse(CHAT_SNAPSHOT),
    "/api/memory/snapshot/chat/changes": () => jsonResponse(CHAT_CHANGES),
    "/api/memory/snapshot/kb": () => jsonResponse({ surface: "kb", entities: [], last_refresh: null, pending_changes: [] }),
    "/api/memory/snapshot/kb/changes": () => jsonResponse({ surface: "kb", changes: [] }),
    "/api/memory/trace/kb?limit=200": () => jsonResponse(KB_QUERIES),
    ...overrides,
  };
}

// ── Harness ──────────────────────────────────────────────────────────

beforeAll(() => {
  (Element.prototype as Element & { scrollIntoView: unknown }).scrollIntoView =
    mocks.scrollIntoView;
});

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.routerReplace.mockReset();
  mocks.scrollIntoView.mockClear();
});

// ── MemorySection ────────────────────────────────────────────────────

describe("<MemorySection />", () => {
  it("shows the loading spinner until the overview resolves, then the picker state", async () => {
    let resolveOverview: (value: FakeResponse) => void = () => {};
    const pending = new Promise<FakeResponse>((resolve) => {
      resolveOverview = resolve;
    });
    installRoutes({ "/api/memory/overview": () => pending });

    render(<MemorySection />);
    expect(document.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("Pick a document to view or update")).not.toBeInTheDocument();

    await act(async () => {
      resolveOverview(jsonResponse({ docs: [], backups: [] }));
    });
    expect(await screen.findByText("Pick a document to view or update")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeNull();
  });

  it("surfaces an overview fetch failure as a header toast", async () => {
    installRoutes({ "/api/memory/overview": () => Promise.reject(new Error("boom")) });
    render(<MemorySection />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("renders the default L2 doc list with the picker state", async () => {
    installRoutes(baseRoutes());
    render(<MemorySection />);

    expect(await screen.findByRole("button", { name: "L1 · Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "L2 · Per-surface" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "L3 · Cross-surface" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Chat/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Notebook/ })).toBeInTheDocument();
    expect(screen.getByText("Pick a document to view or update")).toBeInTheDocument();
  });

  it("shows the doc list empty state when the overview has no docs", async () => {
    installRoutes({ "/api/memory/overview": () => jsonResponse({ docs: [], backups: [] }) });
    render(<MemorySection />);
    expect(await screen.findByText("Pick a document to view or update")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Chat/ })).not.toBeInTheDocument();
  });

  it("loads a selected L2 doc and round-trips edit + save with callbacks", async () => {
    const putCalls: Array<{ url: string; init?: RequestInit }> = [];
    installRoutes(baseRoutes());
    capturePut(putCalls);

    render(<MemorySection />);
    await clickAsync(await screen.findByRole("button", { name: /^Chat/ }));

    const stub = await screen.findByTestId("markdown-stub");
    expect(stub.getAttribute("data-content")).toBe(CHAT_DOC_LINKIFIED);
    expect(screen.getByText("L2 · Chat")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe(CHAT_DOC);

    fireEvent.change(textarea, { target: { value: "Rewritten body" } });
    await clickAsync(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putCalls).toHaveLength(1));
    expect(putCalls[0].url).toBe("/api/memory/doc/L2/chat");
    expect(putCalls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(putCalls[0].init?.body))).toEqual({ content: "Rewritten body" });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      (await screen.findByTestId("markdown-stub")).getAttribute("data-content"),
    ).toBe("Rewritten body");
  });

  it("streams the update run through the SSE panel and reloads the doc", async () => {
    let updateRequested = 0;
    let releaseStream: () => void = () => {};
    const encoder = new TextEncoder();
    installRoutes(
      baseRoutes({
        "/api/memory/doc/L2/chat/update": () => {
          updateRequested += 1;
          return jsonResponse(
            {},
            new ReadableStream<Uint8Array>({
              start(controller) {
                controller.enqueue(encoder.encode('data: {"stage":"scan","count":3}\n\n'));
                releaseStream = () => {
                  controller.enqueue(encoder.encode('data: {"stage":"done"}\n\n'));
                  controller.close();
                };
              },
            }),
          );
        },
      }),
    );

    render(<MemorySection />);
    await clickAsync(await screen.findByRole("button", { name: /^Chat/ }));
    await screen.findByTestId("markdown-stub");

    await clickAsync(screen.getByRole("button", { name: "Update" }));
    expect(await screen.findByText("Update progress")).toBeInTheDocument();
    expect(await screen.findByText("scan")).toBeInTheDocument();
    expect(screen.getByText("Count: 3")).toBeInTheDocument();
    expect(updateRequested).toBe(1);

    // Completing the run reloads the doc and clears the progress panel.
    await act(async () => {
      releaseStream();
    });
    await waitFor(() =>
      expect(screen.queryByText("Update progress")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("markdown-stub")).toBeInTheDocument();
  });

  it("hides Update for the L3 preferences doc and shows its guidance", async () => {
    installRoutes(baseRoutes());
    render(<MemorySection />);

    fireEvent.click(await screen.findByRole("button", { name: "L3 · Cross-surface" }));
    await clickAsync(await screen.findByRole("button", { name: /^偏好/ }));

    expect(await screen.findByText("L3 · 偏好")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Preferences are written when you explicitly tell the chat assistant your preferences (style, language, format).",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("opens the L1 tab with a focused entity after clicking an entity ref link", async () => {
    installRoutes(baseRoutes());
    render(<MemorySection />);

    await clickAsync(await screen.findByRole("button", { name: /^Chat/ }));
    const stub = await screen.findByTestId("markdown-stub");
    const link = stub.querySelector('a[href="#entity-chat__sess-42"]');
    expect(link).not.toBeNull();
    await clickAsync(link as HTMLElement);

    // The count shares a text node with the last-refresh timestamp.
    expect(await screen.findByText(/2 entities/)).toBeInTheDocument();
    expect(screen.getByText("Clear focus")).toBeInTheDocument();
    expect(screen.getByText("1 pending")).toBeInTheDocument();
    expect(mocks.scrollIntoView).toHaveBeenCalled();

    const row = document.querySelector('[data-entity-ref="chat:sess-42"]');
    expect(row).not.toBeNull();
    const rowLink = row?.querySelector("a");
    expect(rowLink?.getAttribute("href")).toBe("/chat/sess-42");
    expect(screen.getByText("new")).toBeInTheDocument();
  });

  it("switches L1 surfaces and modes, and wires the refresh callback", async () => {
    installRoutes(
      baseRoutes({
        "/api/memory/snapshot/chat/refresh": () => jsonResponse(REFRESH_CHANGES),
      }),
    );
    render(<MemorySection />);

    await clickAsync(await screen.findByRole("button", { name: "L1 · Workspace" }));
    expect(await screen.findByText("Nothing in workspace yet.")).toBeInTheDocument();

    await clickAsync(screen.getByRole("button", { name: "Chat" }));
    expect(await screen.findByText(/2 entities/)).toBeInTheDocument();

    // Queries mode is kb-only.
    expect(screen.queryByRole("button", { name: "Queries" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Changes" }));
    expect(
      await screen.findByText("Pending — 1 change(s) since last refresh"),
    ).toBeInTheDocument();
    expect(screen.getByText("Session 42")).toBeInTheDocument();

    await clickAsync(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Refreshed: 1 changes")).toBeInTheDocument();
  });

  it("gates the queries mode to the kb surface and lists recorded queries", async () => {
    installRoutes(baseRoutes());
    render(<MemorySection />);

    await clickAsync(await screen.findByRole("button", { name: "L1 · Workspace" }));
    expect(await screen.findByText("Nothing in workspace yet.")).toBeInTheDocument();

    await clickAsync(screen.getByRole("button", { name: "Knowledge base" }));
    fireEvent.click(await screen.findByRole("button", { name: "Queries" }));
    expect(await screen.findByText("mykb")).toBeInTheDocument();
    expect(screen.getByText("what is memory")).toBeInTheDocument();
  });

  it("shows the empty snapshot and changes states for a bare surface", async () => {
    installRoutes(baseRoutes());
    render(<MemorySection />);

    await clickAsync(await screen.findByRole("button", { name: "L1 · Workspace" }));
    expect(await screen.findByText("Nothing in workspace yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Changes" }));
    expect(
      await screen.findByText("No changes recorded yet. Run Refresh to capture the baseline."),
    ).toBeInTheDocument();
  });

  it("renders the v1 archive banner and keeps it dismissed across renders", async () => {
    const withBackup = () =>
      jsonResponse({
        docs: OVERVIEW.docs,
        backups: ["memory-backup-20260801.zip"],
      });
    installRoutes({ "/api/memory/overview": withBackup });

    const first = render(<MemorySection />);
    expect(await screen.findByText("Your v1 memory was archived")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Your v1 memory was archived")).not.toBeInTheDocument();
    first.unmount();

    render(<MemorySection />);
    expect(await screen.findByRole("button", { name: /^Chat/ })).toBeInTheDocument();
    expect(screen.queryByText("Your v1 memory was archived")).not.toBeInTheDocument();
  });

  it("locks the tab strip with forcedTab and can hide the section header", async () => {
    const withBackup = () => jsonResponse({ docs: OVERVIEW.docs, backups: ["memory-backup-20260801.zip"] });
    installRoutes({ "/api/memory/overview": withBackup });

    render(<MemorySection forcedTab="L3" hideHeader />);
    expect(await screen.findByText("近期总结")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "L1 · Workspace" })).not.toBeInTheDocument();
    expect(screen.queryByText("Your v1 memory was archived")).not.toBeInTheDocument();
  });
});

// ── MemoryWorkbench ──────────────────────────────────────────────────

function workbenchRoutes(overrides: Record<string, RouteHandler> = {}) {
  return {
    "/api/memory/overview": () => jsonResponse(OVERVIEW),
    "/api/memory/doc/L2/chat": () => jsonResponse({ layer: "L2", key: "chat", content: L2_DOC }),
    "/api/memory/doc/L2/chat/lines": () => jsonResponse(L2_LINES),
    "/api/memory/doc/L2/notebook": () => jsonResponse({ layer: "L2", key: "notebook", content: "" }),
    "/api/memory/doc/L2/notebook/lines": () => jsonResponse({ lines: [] }),
    "/api/memory/doc/L3/scope": () => jsonResponse({ layer: "L3", key: "scope", content: L3_DOC }),
    "/api/memory/doc/L3/scope/lines": () => jsonResponse({ lines: [] }),
    ...overrides,
  };
}

describe("<MemoryWorkbench />", () => {
  it("renders the L2 hub with nav rail, doc content and run panel", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" />);

    expect(await screen.findByTestId("markdown-stub")).toBeInTheDocument();
    expect(screen.getByText("L2 · Per-surface summaries")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Chat/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Co-writer/ })).toBeInTheDocument();
    expect(screen.getByTestId("run-panel-stub").getAttribute("data-doc-key")).toBe("chat");

    const l1Link = screen.getByText("L1").closest("a");
    expect(l1Link?.getAttribute("href")).toBe("/memory/l1");
    const l3Link = screen.getByText("L3").closest("a");
    expect(l3Link?.getAttribute("href")).toBe("/memory/l3");
  });

  it("honours initialKey on the L3 hub and fetches that doc", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L3" initialKey="scope" />);

    expect(await screen.findByText("L3 · Cross-surface knowledge")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Knowledge scope/ })).toBeInTheDocument();
    // Breadcrumb label + nav entry both carry the doc label.
    expect(screen.getAllByText("Knowledge scope").length).toBeGreaterThanOrEqual(2);
    const stub = await screen.findByTestId("markdown-stub");
    expect(stub.getAttribute("data-content")).toContain("[notebook](/memory/l2/notebook)");
    expect(mocks.fetch).toHaveBeenCalledWith("/api/memory/doc/L3/scope");
  });

  it("routes and reloads when another nav doc is selected", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" />);
    await screen.findByTestId("markdown-stub");

    await clickAsync(screen.getByRole("button", { name: /^Notebook/ }));

    await waitFor(() =>
      expect(mocks.routerReplace).toHaveBeenCalledWith("/memory/l2/notebook"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("run-panel-stub").getAttribute("data-doc-key")).toBe("notebook"),
    );
    expect(screen.getByText("Empty. Click Update to extract facts from your traces.")).toBeInTheDocument();
  });

  it("toggles between rendered and line-numbered views", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" />);
    await screen.findByTestId("markdown-stub");

    fireEvent.click(screen.getByRole("button", { name: "Line numbers" }));
    expect(screen.getByText("1:")).toBeInTheDocument();
    expect(screen.getByText("2:")).toBeInTheDocument();
    expect(screen.getByText("## Chat memory")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(screen.queryByText("2:")).not.toBeInTheDocument();
  });

  it("shows the line view empty state when no lines exist", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" />);
    await screen.findByTestId("markdown-stub");

    await clickAsync(screen.getByRole("button", { name: /^Notebook/ }));
    await screen.findByText("Empty. Click Update to extract facts from your traces.");
    fireEvent.click(screen.getByRole("button", { name: "Line numbers" }));
    expect(
      screen.getAllByText("Empty. Click Update to extract facts from your traces.").length,
    ).toBeGreaterThan(0);
  });

  it("edits the raw doc, cancels to discard, then saves with the PUT callback", async () => {
    const putCalls: Array<{ url: string; init?: RequestInit }> = [];
    installRoutes(workbenchRoutes());
    capturePut(putCalls);

    render(<MemoryWorkbench layer="L2" />);
    await screen.findByTestId("markdown-stub");

    fireEvent.click(screen.getByRole("button", { name: "Edit raw" }));
    let textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe(L2_DOC);

    fireEvent.change(textarea, { target: { value: "mutated" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    // The rendered view always receives the prepared form of the doc.
    const stubAfterCancel = screen.getByTestId("markdown-stub");
    expect(stubAfterCancel.getAttribute("data-content")).not.toContain("mutated");
    expect(stubAfterCancel.getAttribute("data-content")).toContain(
      "[^1]: [chat:sess-42](/memory/l1?ref=chat%3Asess-42)",
    );
    expect(putCalls).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Edit raw" }));
    textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "final body" } });
    await clickAsync(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putCalls).toHaveLength(1));
    expect(putCalls[0].url).toBe("/api/memory/doc/L2/chat");
    expect(putCalls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(putCalls[0].init?.body))).toEqual({ content: "final body" });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("prepares footnotes and entry anchors before rendering", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" />);
    const stub = await screen.findByTestId("markdown-stub");
    const prepared = stub.getAttribute("data-content") ?? "";

    expect(prepared).toContain(`<span id="${ENTRY}" class="memory-entry-anchor"></span>`);
    expect(prepared).toContain("[^1]: [chat:sess-42](/memory/l1?ref=chat%3Asess-42)");
    expect(prepared).toContain(`[^2]: [${ENTRY}](#${ENTRY})`);
  });

  it("linkifies L3 footnotes to the L2 hub and the legacy resolver", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L3" initialKey="scope" />);
    const stub = await screen.findByTestId("markdown-stub");
    const prepared = stub.getAttribute("data-content") ?? "";

    expect(prepared).toContain("[^1]: [notebook](/memory/l2/notebook)");
    expect(prepared).toContain(`[^2]: [${ENTRY}](/memory/resolve?id=${ENTRY})`);
    expect(prepared).not.toContain("[notasurface](");
    expect(prepared).toContain("[^3]: notasurface");
  });

  it("scrolls to and highlights the deep-linked entry once content renders", async () => {
    installRoutes(workbenchRoutes());
    render(<MemoryWorkbench layer="L2" initialFocus={ENTRY} />);

    await screen.findByTestId("markdown-stub");
    expect(document.getElementById(ENTRY)).not.toBeNull();
    await waitFor(() => expect(mocks.scrollIntoView).toHaveBeenCalled());
    expect(mocks.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: "center" }),
    );
  });
});
