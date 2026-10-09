import React, { useEffect } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import CapabilitiesSettingsPage from "@/features/settings/sections/CapabilitiesSettingsSection";
import ToolsSettingsPage from "@/features/settings/sections/ToolsSettingsSection";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// t must be referentially stable: the sections close over it in their
// register/load callbacks, and a fresh identity per render would re-stage
// pending payloads the provider just cleared.
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t }),
}));
vi.mock("@/lib/theme", () => ({ setTheme: vi.fn() }));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "github",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));
vi.mock("@/lib/llm-options", () => ({
  invalidateLLMOptionsCache: vi.fn(),
  listLLMOptions: vi.fn(async () => ({ active: null, options: [] })),
}));

// ── Fixtures ───────────────────────────────────────────────────────────────
// Capability numbers are pairwise distinct so rows are addressable by value.

const baseCapabilities = {
  chat: {
    temperature: 0.7,
    max_rounds: 6,
    stage_budgets: { exploring: 4096, responding: 8192 },
  },
  solve: { temperature: 0.2, max_tokens: 1024, max_rounds: 3, max_replans: 1 },
  research: {
    temperature: 0.3,
    max_tokens: 3072,
    researching: {
      note_agent_mode: "auto",
      tool_timeout: 120,
      tool_max_retries: 2,
      paper_search_years_limit: 10,
    },
  },
  question: {
    temperature: 0.4,
    max_tokens: 2048,
    exploring: {
      max_iterations: 4,
      tool_summarizer: { enabled: true, max_tokens: 512 },
    },
  },
  co_writer: { temperature: 0.5, max_tokens: 1536 },
  vision_solver: { temperature: 0.6, max_tokens: 2560 },
  math_animator: { temperature: 0.8, max_tokens: 3584 },
  visualize: { temperature: 0.9, max_tokens: 4608 },
};

type FixtureTool = Record<string, unknown> & {
  name: string;
  hints: Record<string, unknown>;
};

function makeTool(overrides: Partial<FixtureTool>): FixtureTool {
  return {
    name: "tool",
    description: "base description",
    parameters: [],
    hints: {
      en: {
        short_description: "short",
        when_to_use: "when to use it",
        input_format: "text in",
        guideline: "be careful",
        note: "",
        phase: "any",
        aliases: [],
      },
      zh: {
        short_description: "简介",
        when_to_use: "使用时机",
        input_format: "文本",
        guideline: "注意",
        note: "",
        phase: "任意",
        aliases: [],
      },
    },
    aliases: [],
    toggleable: true,
    enabled: false,
    available: true,
    unavailable_reason: null,
    ...overrides,
  } as FixtureTool;
}

const baseTools: FixtureTool[] = [
  makeTool({
    name: "web_search",
    toggleable: true,
    parameters: [
      {
        name: "query",
        type: "string",
        description: "search text",
        required: true,
        default: "",
        enum: null,
      },
    ],
  }),
  makeTool({ name: "imagegen", toggleable: true }),
  makeTool({ name: "videogen", toggleable: true, coming_soon: true }),
  makeTool({
    name: "paper_search",
    toggleable: true,
    available: false,
    unavailable_reason: "search_provider_not_configured",
  }),
  makeTool({ name: "rag", toggleable: false }),
  makeTool({ name: "solve_plan", toggleable: false, capability: "solve" }),
];

// ── Stateful mock backend ──────────────────────────────────────────────────

let capabilitiesStore: Record<string, unknown>;
let toolsStore: { tools: FixtureTool[]; enabled_optional_tools: string[] };
let failCapabilitiesPut: boolean;
let failToolsPut: boolean;
let capabilitiesGetError: "none" | "network" | "http";

let settings: ReturnType<typeof useSettings>;

function reply(value: unknown, ok = true, status = ok ? 200 : 500) {
  return { ok, status, json: async () => value };
}

beforeEach(() => {
  capabilitiesStore = structuredClone(baseCapabilities);
  toolsStore = {
    tools: structuredClone(baseTools),
    enabled_optional_tools: ["web_search"],
  };
  failCapabilitiesPut = false;
  failToolsPut = false;
  capabilitiesGetError = "none";
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/settings") {
      return reply({
        catalog: defaultCatalog(),
        ui: { theme: "snow", language: "en", response_language: "en" },
      });
    }
    if (url === "/api/settings/draft") {
      if (method === "PUT") return reply({ draft: JSON.parse(String(init?.body)) });
      return reply({ draft: null });
    }
    if (url === "/api/settings/apply") return reply({ catalog: defaultCatalog() });
    if (url === "/api/system/status") {
      return reply({ backend: { status: "ok", timestamp: "2026-10-09T00:00:00Z" } });
    }
    if (url === "/api/capabilities/settings") {
      if (method === "PUT") {
        if (failCapabilitiesPut) return reply({ detail: "backend refused" }, false);
        capabilitiesStore = JSON.parse(String(init?.body));
      }
      if (capabilitiesGetError === "network") throw new Error("network down");
      if (capabilitiesGetError === "http") return reply({ detail: "missing" }, false);
      return reply(capabilitiesStore);
    }
    if (url === "/api/tools") {
      return reply({
        tools: toolsStore.tools,
        enabled_optional_tools: [...toolsStore.enabled_optional_tools].sort(),
      });
    }
    if (url === "/api/settings/enabled-tools" && method === "PUT") {
      if (failToolsPut) return reply({ detail: "backend refused" }, false);
      toolsStore.enabled_optional_tools = JSON.parse(String(init?.body)).enabled_tools;
      return reply({ enabled_optional_tools: toolsStore.enabled_optional_tools });
    }
    throw new Error(`Unexpected fetch: ${method} ${url}`);
  });
});

// ── Harness ────────────────────────────────────────────────────────────────

function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}

function App({ page }: { page: "capabilities" | "tools" }) {
  return (
    <SettingsProvider>
      <Capture />
      {page === "capabilities" ? <CapabilitiesSettingsPage /> : <ToolsSettingsPage />}
    </SettingsProvider>
  );
}

async function renderPage(page: "capabilities" | "tools", waitForContent = true) {
  const view = render(<App page={page} />);
  await waitFor(() => expect(settings.settingsLoading).toBe(false));
  // The provider being ready is not the page being ready: both sections
  // fetch their own state after mount.
  if (waitForContent && page === "capabilities") {
    await screen.findByDisplayValue("0.7");
  }
  if (waitForContent && page === "tools") {
    await screen.findByText("Experience Enhancement");
  }
  return view;
}

// The capabilities ToggleRow carries no aria-label; scope by row title.
function summarizerToggle() {
  const row = screen
    .getByText("Tool summarizer enabled")
    .closest("div.flex") as HTMLElement;
  return within(row).getByRole("switch");
}

const calls = (url: string, method = "PUT") =>
  mocks.fetch.mock.calls.filter(
    ([u, init]) => u === url && ((init as RequestInit | undefined)?.method ?? "GET") === method,
  );

// ── CapabilitiesSettingsSection ────────────────────────────────────────────

describe("CapabilitiesSettingsSection", () => {
  it("renders every capability section with the server values", async () => {
    await renderPage("capabilities");
    expect(screen.getByText("Capabilities")).toBeTruthy();
    for (const section of [
      "Chat",
      "Solve",
      "Question",
      "Research",
      "Math animator",
      "Visualize",
      "Co-writer",
    ]) {
      expect(screen.getByText(section)).toBeTruthy();
    }
    for (const value of [
      "0.7", "6", "4096", "8192",
      "0.2", "1024", "3", "1",
      "0.4", "2048", "4", "512",
      "0.3", "3072", "120", "2", "10",
      "0.8", "3584",
      "0.9", "4608",
      "0.5", "1536",
    ]) {
      expect(screen.getByDisplayValue(value)).toBeTruthy();
    }
    expect(summarizerToggle().getAttribute("aria-checked")).toBe("true");
    expect(calls("/api/capabilities/settings", "PUT")).toHaveLength(0);
  });

  it("shows the load error with its message and recovers via Retry", async () => {
    capabilitiesGetError = "network";
    await renderPage("capabilities", false);
    expect(screen.getByText("Couldn't load capability settings")).toBeTruthy();
    expect(screen.getByText("network down")).toBeTruthy();
    expect(screen.queryByDisplayValue("0.7")).toBeNull();
    capabilitiesGetError = "none";
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByDisplayValue("0.7");
    expect(screen.queryByText("Couldn't load capability settings")).toBeNull();
  });

  it("distinguishes an HTTP failure from a malformed payload across retries", async () => {
    capabilitiesGetError = "http";
    await renderPage("capabilities", false);
    expect(screen.getByText(/Failed to load capability settings/)).toBeTruthy();
    capabilitiesGetError = "none";
    capabilitiesStore = {};
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText(/unexpected payload/);
    capabilitiesStore = structuredClone(baseCapabilities);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByDisplayValue("0.7");
  });

  it("stages edits without writing, then Apply PUTs the edited payload once", async () => {
    await renderPage("capabilities");
    fireEvent.change(screen.getByDisplayValue("0.7"), {
      target: { value: "1.5" },
    });
    fireEvent.click(summarizerToggle());
    expect(summarizerToggle().getAttribute("aria-checked")).toBe("false");
    expect(settings.hasUnsavedChanges).toBe(true);
    expect(calls("/api/capabilities/settings", "PUT")).toHaveLength(0);

    await act(async () => {
      await settings.applyCatalog();
    });
    const puts = calls("/api/capabilities/settings", "PUT");
    expect(puts).toHaveLength(1);
    const body = JSON.parse(String(puts[0][1]?.body));
    expect(body.chat.temperature).toBe(1.5);
    expect(body.question.exploring.tool_summarizer.enabled).toBe(false);
    expect(settings.draftState).toBe("clean");
    expect(settings.hasUnsavedChanges).toBe(false);
    // The revision bump after Apply refetches from the mock backend, which
    // now holds the saved payload — the saved values must survive it.
    expect(screen.getByDisplayValue("1.5")).toBeTruthy();
    expect(summarizerToggle().getAttribute("aria-checked")).toBe("false");
  });

  it("keeps the edit pending on a failed save and rolls back after Discard", async () => {
    await renderPage("capabilities");
    fireEvent.change(screen.getByDisplayValue("1024"), {
      target: { value: "9999" },
    });
    expect(settings.hasUnsavedChanges).toBe(true);
    failCapabilitiesPut = true;
    await act(async () => {
      await settings.applyCatalog();
    });
    expect(settings.toast).toContain("Could not apply");
    expect(calls("/api/capabilities/settings", "PUT")).toHaveLength(1);
    // The failed edit stays on screen for retry instead of being lost.
    expect(screen.getByDisplayValue("9999")).toBeTruthy();
    expect(settings.hasUnsavedChanges).toBe(true);

    await act(async () => {
      await settings.discardDraft();
    });
    // Draft discard bumps the revision; the page re-reads the server copy.
    await waitFor(() => expect(screen.getByDisplayValue("1024")).toBeTruthy());
    expect(screen.queryByDisplayValue("9999")).toBeNull();
    expect(settings.hasUnsavedChanges).toBe(false);
  });
});

// ── ToolsSettingsSection ───────────────────────────────────────────────────

describe("ToolsSettingsSection", () => {
  it("buckets tools into experience, built-in and capability sections with correct toggle states", async () => {
    await renderPage("tools");
    expect(screen.getByText("Tools")).toBeTruthy();
    expect(screen.getByText("Experience Enhancement")).toBeTruthy();
    expect(screen.getByText("Built-in Tools")).toBeTruthy();
    expect(screen.getByText("Deep Solve · Capability Tools")).toBeTruthy();
    expect(screen.getByText("solve_plan")).toBeTruthy();

    expect(screen.getByRole("switch", { name: "On" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("switch", { name: "Off" }).getAttribute("aria-checked")).toBe("false");
    // rag and solve_plan are both non-toggleable: a locked "Always on" note,
    // never a switch.
    const lockedNotes = screen.getAllByRole("note");
    expect(lockedNotes).toHaveLength(2);
    for (const note of lockedNotes) expect(note).toHaveTextContent("Always on");

    const comingSoon = screen.getAllByText("Coming soon");
    expect(comingSoon).toHaveLength(1);
    const lockedSoon = screen.getByRole("switch", { name: "Coming soon" });
    expect(lockedSoon.hasAttribute("disabled")).toBe(true);
    fireEvent.click(lockedSoon);
    expect(lockedSoon.getAttribute("aria-checked")).toBe("false");

    const notConfigured = screen.getByRole("switch", { name: "Not configured" });
    expect(notConfigured.hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByText("Choose a provider in Search settings first. DuckDuckGo needs no API key."),
    ).toBeTruthy();
    expect(screen.getByText("Open settings")).toBeTruthy();
    fireEvent.click(notConfigured);
    expect(notConfigured.getAttribute("aria-checked")).toBe("false");
    expect(calls("/api/settings/enabled-tools", "PUT")).toHaveLength(0);
  });

  it("expands a tool row to reveal hints and parameters", async () => {
    await renderPage("tools");
    expect(screen.queryByText("When to use")).toBeNull();
    fireEvent.click(screen.getByText("web_search").closest("button")!);
    expect(screen.getByText("web_search").closest("button")!.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("When to use")).toBeTruthy();
    expect(screen.getByText("Input format")).toBeTruthy();
    expect(screen.getByText("Guideline")).toBeTruthy();
    expect(screen.getByText("Parameters")).toBeTruthy();
    expect(screen.getByText("query")).toBeTruthy();
    fireEvent.click(screen.getByText("web_search").closest("button")!);
    expect(screen.queryByText("When to use")).toBeNull();
  });

  it("filters tools by query, reports no-match and restores via Clear", async () => {
    await renderPage("tools");
    fireEvent.change(screen.getByLabelText("Search tools"), {
      target: { value: "paper_search" },
    });
    expect(screen.getByText("paper_search")).toBeTruthy();
    expect(screen.queryByText("rag")).toBeNull();
    expect(screen.queryByText("web_search")).toBeNull();

    fireEvent.change(screen.getByLabelText("Search tools"), {
      target: { value: "zzz-nothing" },
    });
    expect(screen.getByText(/No tools match/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/No tools match/)).toBeNull();
    expect(screen.getByText("rag")).toBeTruthy();
    expect(screen.getByText("web_search")).toBeTruthy();
  });

  it("stages a toggle without writing, then Apply PUTs the enabled-tools payload", async () => {
    await renderPage("tools");
    fireEvent.click(screen.getByRole("switch", { name: "Off" }));
    expect(screen.getAllByRole("switch", { name: "On" })).toHaveLength(2);
    expect(settings.hasUnsavedChanges).toBe(true);
    expect(calls("/api/settings/enabled-tools", "PUT")).toHaveLength(0);

    await act(async () => {
      await settings.applyCatalog();
    });
    const puts = calls("/api/settings/enabled-tools", "PUT");
    expect(puts).toHaveLength(1);
    expect(JSON.parse(String(puts[0][1]?.body))).toEqual({
      enabled_tools: ["imagegen", "web_search"],
    });
    expect(settings.draftState).toBe("clean");
    // The post-apply revision bump refetches /api/tools; the mock backend
    // holds the saved set so the toggle survives it.
    expect(calls("/api/tools", "GET").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("switch", { name: "On" })).toHaveLength(2);
  });

  it("keeps a failed toggle pending and rolls back to the server state after Discard", async () => {
    await renderPage("tools");
    fireEvent.click(screen.getByRole("switch", { name: "On" }));
    expect(screen.getAllByRole("switch", { name: "Off" })).toHaveLength(2);
    failToolsPut = true;
    const getsBefore = calls("/api/tools", "GET").length;

    await act(async () => {
      await settings.applyCatalog();
    });
    expect(settings.toast).toContain("Could not apply");
    expect(calls("/api/settings/enabled-tools", "PUT")).toHaveLength(1);
    expect(settings.hasUnsavedChanges).toBe(true);
    // The off state is still on screen, waiting to be retried.
    expect(screen.getAllByRole("switch", { name: "Off" })).toHaveLength(2);

    await act(async () => {
      await settings.discardDraft();
    });
    await waitFor(() =>
      expect(calls("/api/tools", "GET").length).toBeGreaterThan(getsBefore),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "On" })).toBeTruthy(),
    );
    expect(screen.getByRole("switch", { name: "Off" })).toBeTruthy();
    expect(settings.hasUnsavedChanges).toBe(false);
  });

  it("shows the load failure instead of tool rows when /api/tools fails", async () => {
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url === "/api/settings") {
        return reply({
          catalog: defaultCatalog(),
          ui: { theme: "snow", language: "en", response_language: "en" },
        });
      }
      if (url === "/api/settings/draft") return reply({ draft: null });
      if (url === "/api/system/status") return reply({ backend: { status: "ok" } });
      if (url === "/api/tools") return reply({ detail: "boom" }, false);
      throw new Error(`Unexpected fetch: ${url}`);
    });
    await renderPage("tools", false);
    await screen.findByText(/Failed to load tools/);
    expect(screen.queryByText("Experience Enhancement")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
