import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import MemoryGraph from "@/components/memory/MemoryGraph";
import MemoryRunPanel from "@/components/memory/MemoryRunPanel";
import { apiFetch } from "@/lib/api";
import {
  fetchMemorySnapshot,
  type L1Entity,
  type ParsedDoc,
  type RawMemorySnapshot,
} from "@/lib/memory-graph";
import { listLLMOptions } from "@/lib/llm-options";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children?: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/memory-graph", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/memory-graph")>();
  return { ...actual, fetchMemorySnapshot: vi.fn() };
});
vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));
vi.mock("@/lib/llm-options", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/llm-options")>();
  return { ...actual, listLLMOptions: vi.fn() };
});

const fetchGraphSnapshot = vi.mocked(fetchMemorySnapshot);
const fetchApi = vi.mocked(apiFetch);
const fetchLLMOptions = vi.mocked(listLLMOptions);

// ── Shared fixtures ──────────────────────────────────────────────────

const ISO = "2026-10-09T00:00:00.000Z";
const EMPTY_DOC: ParsedDoc = { title: "", entries: [] };
// 26-char Crockford-base32 ULID shape required by the memory entry ids.
const ulid = (tag: string) => `m_${tag}${"0".repeat(26 - tag.length)}`;
const ENTRY_A = ulid("A");
const ENTRY_B = ulid("B");
const ENTRY_C = ulid("C");

const l1Entity = (id: string, label: string, content: string): L1Entity => ({
  id,
  label,
  ts: ISO,
  content,
});

// One chat L2 entry citing two L1 entities, a second citing one, and an
// L3 profile entry citing the chat surface (soft edge to the anchor).
function graphSnapshot(): RawMemorySnapshot {
  return {
    l1: {
      chat: [
        l1Entity(
          "ent_chat_1",
          "Prefers concise answers",
          "User said they prefer concise answers.",
        ),
        l1Entity("ent_chat_2", "Likes TypeScript", "Mentioned enjoying TypeScript."),
      ],
      notebook: [l1Entity("ent_nb_1", "Read chapter 3", "Studied chapter 3 about loops.")],
      quiz: [],
      kb: [],
      book: [],
      partner: [],
      cowriter: [],
    },
    l2: {
      chat: {
        title: "Chat memory",
        entries: [
          {
            id: ENTRY_A,
            section: "Preferences",
            text: "Prefers concise answers",
            refs: ["chat:ent_chat_1", "chat:ent_chat_2"],
          },
          {
            id: ENTRY_B,
            section: "Preferences",
            text: "Enjoys TypeScript",
            refs: ["chat:ent_chat_1"],
          },
        ],
      },
      notebook: EMPTY_DOC,
      quiz: EMPTY_DOC,
      kb: EMPTY_DOC,
      book: EMPTY_DOC,
      partner: EMPTY_DOC,
      cowriter: EMPTY_DOC,
    },
    l3: {
      profile: {
        title: "Profile",
        entries: [
          {
            id: ENTRY_C,
            section: "Summary",
            text: "Actively learning TypeScript",
            refs: ["chat"],
          },
        ],
      },
      recent: EMPTY_DOC,
      scope: EMPTY_DOC,
    },
  };
}

const NODE_L1 = `L1:chat:ent_chat_1`;
const NODE_L2 = `L2:chat:${ENTRY_A}`;
const NODE_L3 = `L3:profile:${ENTRY_C}`;

function nodeGroup(id: string): SVGGElement {
  const g = document.querySelector(`[data-node="${CSS.escape(id)}"]`);
  if (!g) throw new Error(`graph node not rendered: ${id}`);
  return g as SVGGElement;
}

// First circle inside a node group is the transparent hit target.
function hitTarget(g: SVGGElement): Element {
  const circle = g.querySelector("circle");
  if (!circle) throw new Error("node hit target missing");
  return circle;
}

function graphSvg(): SVGSVGElement {
  // The header back-link icon is also an <svg>; scope to the graph canvas.
  const svg = document.querySelector('svg[aria-label="Memory graph"]');
  if (!svg) throw new Error("graph svg missing");
  return svg as unknown as SVGSVGElement;
}

function edgePaths(svg: SVGSVGElement): Element[] {
  return Array.from(svg.querySelectorAll("path[stroke-opacity]"));
}

// ── MemoryGraph (component layer) ────────────────────────────────────

describe("MemoryGraph", () => {
  beforeEach(() => {
    fetchGraphSnapshot.mockResolvedValue(graphSnapshot());
  });

  it("shows a loading state, then renders nodes, edges, legend and header", async () => {
    let resolveSnapshot!: (value: RawMemorySnapshot) => void;
    fetchGraphSnapshot.mockImplementation(
      () =>
        new Promise<RawMemorySnapshot>((resolve) => {
          resolveSnapshot = resolve;
        }),
    );
    render(<MemoryGraph />);

    expect(screen.getByText("Composing memory graph…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
    expect(screen.queryByText(/Hover a node to preview/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Memory" })).toHaveAttribute(
      "href",
      "/memory",
    );

    await waitFor(() => expect(resolveSnapshot).toBeDefined());
    await waitFor(async () => {
      resolveSnapshot(graphSnapshot());
    });

    expect(
      screen.queryByText("Composing memory graph…"),
    ).not.toBeInTheDocument();
    // 3 L1 + 2 L2 chat + 1 L3 profile nodes; r=0 anchors stay hidden.
    expect(document.querySelectorAll("[data-node]").length).toBe(6);
    // 3 strong L2→L1 edges + 1 soft L3→surface edge.
    expect(edgePaths(graphSvg()).length).toBe(4);
    expect(screen.getByText(/Hover a node to preview/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("hovering a node opens the preview card and leaving closes it", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );

    fireEvent.pointerOver(hitTarget(nodeGroup(NODE_L1)));
    expect(
      await screen.findByText("User said they prefer concise answers."),
    ).toBeInTheDocument();
    expect(screen.getByText("L1 · raw trace")).toBeInTheDocument();

    fireEvent.pointerOut(hitTarget(nodeGroup(NODE_L1)));
    expect(
      screen.queryByText("User said they prefer concise answers."),
    ).not.toBeInTheDocument();

    fireEvent.pointerOver(hitTarget(nodeGroup(NODE_L2)));
    expect(await screen.findByText("L2 · curated")).toBeInTheDocument();
    expect(screen.getByText("Preferences")).toBeInTheDocument();

    fireEvent.pointerOut(hitTarget(nodeGroup(NODE_L2)));
    expect(screen.queryByText("L2 · curated")).not.toBeInTheDocument();
  });

  it("clicking a node locks the highlight, clicking again releases it", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );

    // Idle: unfocused strong edges 0.16, soft edge 0.08.
    expect(graphSvg().querySelectorAll('path[stroke-opacity="0.16"]').length).toBe(3);
    expect(graphSvg().querySelectorAll('path[stroke-opacity="0.08"]').length).toBe(1);
    expect(nodeGroup(NODE_L1).querySelectorAll("circle").length).toBe(2);

    fireEvent.click(hitTarget(nodeGroup(NODE_L1)));

    // Active node gains a halo circle and bright focused edges (2-hop
    // highlight reaches both L2 entries and the second L1 entity).
    expect(nodeGroup(NODE_L1).querySelectorAll("circle").length).toBe(3);
    expect(graphSvg().querySelectorAll('path[stroke-opacity="0.85"]').length).toBe(3);
    expect(graphSvg().querySelectorAll('path[stroke-opacity="0.04"]').length).toBe(1);

    fireEvent.click(hitTarget(nodeGroup(NODE_L1)));
    expect(nodeGroup(NODE_L1).querySelectorAll("circle").length).toBe(2);
    expect(graphSvg().querySelectorAll('path[stroke-opacity="0.85"]').length).toBe(0);
  });

  it("pointer-down on the canvas background clears the selection", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );

    fireEvent.click(hitTarget(nodeGroup(NODE_L1)));
    expect(nodeGroup(NODE_L1).querySelectorAll("circle").length).toBe(3);

    const container = graphSvg().parentElement;
    expect(container).not.toBeNull();
    fireEvent.pointerDown(container!);

    expect(nodeGroup(NODE_L1).querySelectorAll("circle").length).toBe(2);
  });

  it("layer toggles hide that layer's nodes and incident edges", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );

    fireEvent.click(screen.getByRole("button", { name: /Raw traces/ }));

    expect(document.querySelectorAll("[data-node]").length).toBe(3);
    // Only the soft L3→chat-surface edge survives without L1 endpoints.
    expect(edgePaths(graphSvg()).length).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: /Raw traces/ }));
    expect(document.querySelectorAll("[data-node]").length).toBe(6);
    expect(edgePaths(graphSvg()).length).toBe(4);
  });

  it("zoom buttons move the scale readout and fit resets it", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );

    // jsdom canvas is 0×0, so the initial fit computes scale 0.
    expect(screen.getByText("0%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("35%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("44%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByText("35%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("refresh refetches the snapshot", async () => {
    render(<MemoryGraph />);
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );
    expect(fetchGraphSnapshot).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(fetchGraphSnapshot).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(document.querySelectorAll("[data-node]").length).toBe(6),
    );
  });
});

// ── MemoryRunPanel (component layer, mocked transport) ───────────────

interface RunHandleFixture {
  id: string;
  layer: "L2" | "L3";
  key: string;
  mode: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  error: string | null;
  event_count: number;
  undo_count: number;
}

const RUN_HANDLE: RunHandleFixture = {
  id: "run-1",
  layer: "L2",
  key: "chat",
  mode: "update",
  status: "queued",
  started_at: ISO,
  ended_at: null,
  error: null,
  event_count: 0,
  undo_count: 0,
};

const SETTINGS = {
  update: { l2_budget: 12, l3_budget: 5 },
  audit: { l2_budget: 8, l3_budget: 3 },
  dedup: { iterations: 2, auto_after_update: false },
};

const UNDO_RESPONSE = {
  undo_count: 0,
  event: {
    seq: 100,
    ts: ISO,
    stage: "undo_applied",
    action: "undo",
    undo_depth: 0,
  },
};

// Server-sent-event stream whose chunks the test emits explicitly.
function createEventStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(stream),
    send: (event: Record<string, unknown>) =>
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)),
    close: () => controller.close(),
  };
}

function jsonResponse(payload: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(payload), { status: 200, ...init });
}

// Route every transport call the panel + run hook can make.
function installTransport(opts?: { startResponse?: () => Response }) {
  const stream = createEventStream();
  fetchApi.mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "POST" && url === "/api/memory/runs/start") {
      return opts?.startResponse
        ? opts.startResponse()
        : jsonResponse(RUN_HANDLE);
    }
    if (method === "POST" && url === "/api/memory/runs/run-1/cancel") {
      return jsonResponse({ ok: true });
    }
    if (method === "POST" && url === "/api/memory/runs/run-1/undo") {
      return jsonResponse(UNDO_RESPONSE);
    }
    if (method === "POST" && url === "/api/memory/doc/L2/chat/reset") {
      return jsonResponse({ ok: true });
    }
    if (url === "/api/memory/runs/run-1/events?since=0") return stream.response;
    if (url === "/api/memory/runs/run-1") return jsonResponse(RUN_HANDLE);
    if (url === "/api/memory/runs?layer=L2&key=chat") {
      return jsonResponse({ runs: [] });
    }
    if (url === "/api/memory/settings") return jsonResponse(SETTINGS);
    throw new Error(`unexpected apiFetch: ${method} ${url}`);
  });
  return stream;
}

function postsTo(path: string): { url: string; body: unknown }[] {
  return fetchApi.mock.calls
    .filter(
      ([input, init]) =>
        (init?.method ?? "GET").toUpperCase() === "POST" &&
        String(input) === path,
    )
    .map(([input, init]) => ({ url: String(input), body: init?.body }));
}

describe("MemoryRunPanel", () => {
  beforeEach(() => {
    fetchLLMOptions.mockResolvedValue({
      active: { profile_id: "p1", model_id: "m1" },
      options: [
        {
          profile_id: "p1",
          model_id: "m1",
          model: "glm-4.6",
          provider: "zai",
          provider_label: "Z.ai",
          model_name: "GLM-4.6",
          profile_name: "Main profile",
          is_active_default: true,
        },
      ],
    });
  });

  it("runs an update: composer defaults, running state, streamed turns, completion callbacks", async () => {
    const stream = installTransport();
    const onRunComplete = vi.fn();
    const onDocUpdated = vi.fn();
    render(
      <MemoryRunPanel
        layer="L2"
        docKey="chat"
        onRunComplete={onRunComplete}
        onDocUpdated={onDocUpdated}
      />,
    );

    expect(screen.getByText(/Pick a mode and click Run/)).toBeInTheDocument();
    expect(await screen.findByText("GLM-4.6")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Budget")).toHaveValue(12),
    );

    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    const [startPost] = postsTo("/api/memory/runs/start");
    expect(startPost).toBeTruthy();
    expect(JSON.parse(String(startPost!.body))).toEqual({
      layer: "L2",
      key: "chat",
      mode: "update",
      budget: 12,
      iterations: null,
      llm_selection: { profile_id: "p1", model_id: "m1" },
      language: "en",
    });

    expect(
      await screen.findByRole("button", { name: "Cancel" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update memory" })).toBeDisabled();
    expect(screen.getByLabelText("Budget")).toBeDisabled();
    expect(screen.getByText(/Working…/)).toBeInTheDocument();

    stream.send({ seq: 1, ts: ISO, stage: "run_started", mode: "update" });
    expect(await screen.findByText("Run started")).toBeInTheDocument();

    stream.send({
      seq: 2,
      ts: ISO,
      stage: "llm_io_start",
      turn: 1,
      system_prompt: "SYS-PROMPT",
      user_prompt: "USER-PROMPT",
      label: "update",
    });
    stream.send({ seq: 3, ts: ISO, stage: "llm_io_delta", turn: 1, delta: '{"ops":[]}' });
    stream.send({
      seq: 4,
      ts: ISO,
      stage: "llm_io_end",
      turn: 1,
      response: '{"ops":[]}',
    });
    expect(await screen.findByText('{"ops":[]}')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /System prompt/ }));
    expect(await screen.findByText("SYS-PROMPT")).toBeInTheDocument();

    stream.send({
      seq: 5,
      ts: ISO,
      stage: "doc_updated",
      action: "replace",
      turn: 1,
      undo_depth: 1,
    });
    expect(await screen.findByText("Markdown updated")).toBeInTheDocument();
    const undoButton = screen.getByRole("button", {
      name: "Undo last memory edit",
    });
    // Undo stays locked while the run is active; the queued depth shows.
    expect(undoButton).toBeDisabled();
    expect(undoButton).toHaveTextContent("1");
    expect(onDocUpdated).toHaveBeenCalledTimes(1);

    stream.send({
      seq: 6,
      ts: ISO,
      stage: "done",
      facts_added: 2,
      edits_applied: 1,
    });
    expect(await screen.findByText("Done")).toBeInTheDocument();

    stream.send({ seq: 7, ts: ISO, stage: "run_ended", status: "done" });
    stream.close();
    expect(
      await screen.findByRole("button", { name: "Run" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(onRunComplete).toHaveBeenCalledTimes(1));
  });

  it("surfaces llm turn failures and run-level error events", async () => {
    const stream = installTransport();
    render(<MemoryRunPanel layer="L2" docKey="chat" />);
    await screen.findByText("GLM-4.6");

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("button", { name: "Cancel" });

    stream.send({
      seq: 1,
      ts: ISO,
      stage: "llm_io_start",
      turn: 1,
      system_prompt: "SYS",
      user_prompt: "USER",
    });
    expect(await screen.findByText("Streaming…")).toBeInTheDocument();

    stream.send({
      seq: 2,
      ts: ISO,
      stage: "llm_io_end",
      turn: 1,
      error: "model timeout",
    });
    expect(await screen.findByText("model timeout")).toBeInTheDocument();
    expect(screen.queryByText("Streaming…")).not.toBeInTheDocument();

    stream.send({ seq: 3, ts: ISO, stage: "error", message: "run aborted" });
    expect(await screen.findByText("run aborted")).toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();

    stream.send({ seq: 4, ts: ISO, stage: "run_ended", status: "error" });
    stream.close();
    expect(await screen.findByRole("button", { name: "Run" })).toBeInTheDocument();
  });

  it("presents start failures inline in the trace", async () => {
    installTransport({
      startResponse: () => new Response("boom: budget rejected", { status: 500 }),
    });
    render(<MemoryRunPanel layer="L2" docKey="chat" />);
    await screen.findByText("GLM-4.6");

    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("boom: budget rejected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeEnabled();
  });

  it("posts a cancel request for the active run and shows the cancelled state", async () => {
    const stream = installTransport();
    const onRunComplete = vi.fn();
    render(<MemoryRunPanel layer="L2" docKey="chat" onRunComplete={onRunComplete} />);
    await screen.findByText("GLM-4.6");

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("button", { name: "Cancel" });

    stream.send({ seq: 1, ts: ISO, stage: "run_started", mode: "update" });
    await screen.findByText("Run started");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(postsTo("/api/memory/runs/run-1/cancel").length).toBe(1),
    );

    stream.send({ seq: 2, ts: ISO, stage: "cancelled" });
    stream.send({ seq: 3, ts: ISO, stage: "run_ended", status: "cancelled" });
    stream.close();
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Run" })).toBeInTheDocument();
    await waitFor(() => expect(onRunComplete).toHaveBeenCalledTimes(1));
  });

  it("undo posts to the run undo endpoint and renders the undo event", async () => {
    const stream = installTransport();
    const onDocUpdated = vi.fn();
    render(<MemoryRunPanel layer="L2" docKey="chat" onDocUpdated={onDocUpdated} />);
    await screen.findByText("GLM-4.6");

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    stream.send({ seq: 1, ts: ISO, stage: "run_started", mode: "update" });
    stream.send({
      seq: 2,
      ts: ISO,
      stage: "doc_updated",
      action: "replace",
      undo_depth: 1,
    });
    stream.send({ seq: 3, ts: ISO, stage: "run_ended", status: "done" });
    stream.close();
    await screen.findByRole("button", { name: "Run" });

    const undoButton = screen.getByRole("button", {
      name: "Undo last memory edit",
    });
    expect(undoButton).toBeEnabled();
    fireEvent.click(undoButton);

    expect(await screen.findByText("Undo applied")).toBeInTheDocument();
    await waitFor(() =>
      expect(postsTo("/api/memory/runs/run-1/undo").length).toBe(1),
    );
    // The undo_applied event reports undo_depth 0 → badge and affordance go.
    expect(undoButton).toBeDisabled();
    expect(undoButton).not.toHaveTextContent("1");
    expect(onDocUpdated).toHaveBeenCalledTimes(2);
  });

  it("reset requires confirmation and clears the local trace on success", async () => {
    installTransport();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onDocUpdated = vi.fn();
    render(<MemoryRunPanel layer="L2" docKey="chat" onDocUpdated={onDocUpdated} />);
    await screen.findByText("GLM-4.6");

    const resetButton = screen.getByRole("button", { name: /Reset memory/ });
    fireEvent.click(resetButton);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(postsTo("/api/memory/doc/L2/chat/reset").length).toBe(0);

    confirmSpy.mockReturnValue(true);
    fireEvent.click(resetButton);
    await waitFor(() =>
      expect(postsTo("/api/memory/doc/L2/chat/reset").length).toBe(1),
    );
    expect(await screen.findByText(/Pick a mode and click Run/)).toBeInTheDocument();
    expect(onDocUpdated).toHaveBeenCalledTimes(1);
  });

  it("switches modes with per-mode inputs and clamps typed values", async () => {
    installTransport();
    render(<MemoryRunPanel layer="L2" docKey="chat" />);
    await screen.findByText("GLM-4.6");

    const budget = screen.getByLabelText("Budget");
    fireEvent.change(budget, { target: { value: "999" } });
    expect(budget).toHaveValue(200);

    fireEvent.click(screen.getByRole("button", { name: "Dedup" }));
    expect(screen.getByLabelText("Iter")).toHaveValue(2);

    fireEvent.click(screen.getByRole("button", { name: "Audit memory" }));
    expect(screen.getByLabelText("Budget")).toHaveValue(8);

    // The typed update-budget override survives the round trip.
    fireEvent.click(screen.getByRole("button", { name: "Update memory" }));
    expect(screen.getByLabelText("Budget")).toHaveValue(200);
  });

  it("marks the model picker unavailable when options fail to load", async () => {
    installTransport();
    fetchLLMOptions.mockRejectedValue(new Error("offline"));
    render(<MemoryRunPanel layer="L2" docKey="chat" />);

    const pill = await screen.findByRole("button", {
      name: /Models unavailable/,
    });
    expect(pill).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run" })).toBeEnabled();
  });
});
