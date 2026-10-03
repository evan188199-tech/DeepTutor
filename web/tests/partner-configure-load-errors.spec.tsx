import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PartnerConfigure from "@/components/partners/PartnerConfigure";
import type { PartnerInfo } from "@/lib/partners-api";

const api = vi.hoisted(() => ({
  soul: vi.fn(),
  assets: vi.fn(),
  toolOptions: vi.fn(),
  llmOptions: vi.fn(),
  partnerWorkspaces: vi.fn(),
  workspaces: vi.fn(),
}));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "en" } }),
}));
vi.mock("@/lib/partners-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/partners-api")>()),
  getPartnerSoul: api.soul,
  getPartnerAssets: api.assets,
  getToolOptions: api.toolOptions,
  getPartnerWorkspaces: api.partnerWorkspaces,
}));
vi.mock("@/lib/llm-options", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/llm-options")>()),
  listLLMOptions: api.llmOptions,
}));
vi.mock("@/lib/workspaces-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspaces-api")>()),
  listWorkspaces: api.workspaces,
}));

const emptyAssets = { knowledge_bases: [], skills: [], notebooks: [] };
const toolOptions = {
  tools: [{ name: "web_search", description: "Search the web" }],
  builtin_tools: [],
  mcp_tools: [],
};

function makePartner(): PartnerInfo {
  return {
    partner_id: "ada",
    name: "Ada",
    description: "",
    channels: [],
    running: false,
    started_at: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  api.soul.mockResolvedValue("");
  api.assets.mockResolvedValue(emptyAssets);
  api.toolOptions.mockResolvedValue(toolOptions);
  api.llmOptions.mockResolvedValue({ options: [], active: null });
  api.partnerWorkspaces.mockResolvedValue([]);
  api.workspaces.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("does not report an error when the asset library is genuinely empty", async () => {
  render(
    <PartnerConfigure partner={makePartner()} onToast={vi.fn()} onUpdated={vi.fn()} />,
  );
  expect(
    await screen.findByText("web_search"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Nothing assigned yet — this partner only knows what you tell it.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows a visible error instead of an empty library when assets fail to load", async () => {
  api.assets.mockRejectedValue(new Error("boom"));
  render(
    <PartnerConfigure partner={makePartner()} onToast={vi.fn()} onUpdated={vi.fn()} />,
  );
  expect(
    await screen.findByText(
      "Could not load this partner's assets — assigned items, if any, are not shown.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(
      "Nothing assigned yet — this partner only knows what you tell it.",
    ),
  ).toBeNull();
  // The rest of the panel still loads.
  expect(await screen.findByText("web_search")).toBeInTheDocument();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
});

it("shows a visible error instead of an eternal loading state when tool options fail to load", async () => {
  api.toolOptions.mockRejectedValue(new Error("boom"));
  render(
    <PartnerConfigure partner={makePartner()} onToast={vi.fn()} onUpdated={vi.fn()} />,
  );
  expect(
    await screen.findByText(
      "Could not load tool options — tool settings cannot be edited right now.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("Loading tools…")).toBeNull();
  // Assets still load and a genuinely empty library is reported as empty.
  expect(
    await screen.findByText(
      "Nothing assigned yet — this partner only knows what you tell it.",
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
});
