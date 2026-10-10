import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ToolPicker from "@/components/partners/ToolPicker";
import type { ToolOptions } from "@/lib/partners-api";

vi.mock("@/components/common/McpToolGroups", async () => {
  const { toggleToolName } = (await import("@/lib/mcp-tool-groups")) as {
    toggleToolName: (selected: string[], name: string) => string[];
  };
  return {
    default: ({
      tools,
      selected,
      onChange,
      renderTool,
    }: {
      tools: { name: string; description: string }[];
      selected: string[];
      onChange: (next: string[]) => void;
      renderTool: (args: {
        tool: { name: string; description: string };
        checked: boolean;
        onToggle: () => void;
      }) => ReactNode;
    }) => (
      <div data-testid="mcp-groups">
        {tools.map((tool) =>
          renderTool({
            tool,
            checked: selected.includes(tool.name),
            onToggle: () => onChange(toggleToolName(selected, tool.name)),
          }),
        )}
      </div>
    ),
  };
});
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const options: ToolOptions = {
  tools: [
    { name: "web_search", description: "Search the web with citations" },
    { name: "imagegen", description: "Generate images" },
  ],
  builtin_tools: [{ name: "rag", description: "Knowledge base retrieval" }],
  mcp_tools: [
    {
      name: "wiki_read",
      description: "Read wiki pages",
      provider_id: "deepwiki",
      server: "deepwiki",
      kind: "mcp",
    },
    {
      name: "wiki_search",
      description: "Search wiki pages",
      provider_id: "deepwiki",
      server: "deepwiki",
      kind: "mcp",
    },
  ],
};

const noop = () => {};

function renderPicker(overrides: {
  options?: ToolOptions | null;
  enabledTools?: string[];
  builtinTools?: string[];
  mcpTools?: string[];
  onChangeEnabledTools?: (next: string[]) => void;
  onChangeBuiltinTools?: (next: string[]) => void;
  onChangeMcpTools?: (next: string[]) => void;
} = {}) {
  return render(
    <ToolPicker
      options={overrides.options === undefined ? options : overrides.options}
      enabledTools={overrides.enabledTools ?? []}
      builtinTools={overrides.builtinTools ?? []}
      mcpTools={overrides.mcpTools ?? []}
      onChangeEnabledTools={overrides.onChangeEnabledTools ?? noop}
      onChangeBuiltinTools={overrides.onChangeBuiltinTools ?? noop}
      onChangeMcpTools={overrides.onChangeMcpTools ?? noop}
    />,
  );
}

it("shows a loading placeholder while tool options are null", () => {
  renderPicker({ options: null });
  expect(screen.getByText("Loading tools…")).toBeInTheDocument();
  expect(screen.queryByText("System tools")).not.toBeInTheDocument();
});

it("renders system tools with their descriptions unchecked by default", () => {
  renderPicker();
  expect(screen.getByRole("checkbox", { name: /web_search/ })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /imagegen/ })).not.toBeChecked();
  expect(screen.getByText("Search the web with citations")).toBeInTheDocument();
});

it("echoes the incoming whitelist as checked boxes", () => {
  renderPicker({ enabledTools: ["imagegen"] });
  expect(screen.getByRole("checkbox", { name: /imagegen/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /web_search/ })).not.toBeChecked();
});

it("toggling an unchecked system tool grants it", () => {
  const onChangeEnabledTools = vi.fn();
  renderPicker({ onChangeEnabledTools });
  fireEvent.click(screen.getByRole("checkbox", { name: /web_search/ }));
  expect(onChangeEnabledTools).toHaveBeenCalledWith(["web_search"]);
});

it("toggling a whitelisted system tool revokes it", () => {
  const onChangeEnabledTools = vi.fn();
  renderPicker({ enabledTools: ["web_search"], onChangeEnabledTools });
  fireEvent.click(screen.getByRole("checkbox", { name: /web_search/ }));
  expect(onChangeEnabledTools).toHaveBeenCalledWith([]);
});

it("system tools All and None select everything or nothing", () => {
  const onChangeEnabledTools = vi.fn();
  renderPicker({ onChangeEnabledTools });
  const section = screen.getByRole("heading", { name: "System tools" })
    .parentElement as HTMLElement;
  fireEvent.click(within(section).getByRole("button", { name: "All" }));
  expect(onChangeEnabledTools).toHaveBeenCalledWith(["web_search", "imagegen"]);
  fireEvent.click(within(section).getByRole("button", { name: "None" }));
  expect(onChangeEnabledTools).toHaveBeenLastCalledWith([]);
});

it("hides the built-in tools section when there are none", () => {
  renderPicker({ options: { ...options, builtin_tools: [] } });
  expect(screen.queryByText("Built-in tools")).not.toBeInTheDocument();
});

it("renders built-in tools with grant and deny controls", () => {
  const onChangeBuiltinTools = vi.fn();
  renderPicker({ builtinTools: ["rag"], onChangeBuiltinTools });
  expect(screen.getByRole("checkbox", { name: /rag/ })).toBeChecked();
  const section = screen.getByRole("heading", { name: "Built-in tools" })
    .parentElement as HTMLElement;
  fireEvent.click(within(section).getByRole("button", { name: "None" }));
  expect(onChangeBuiltinTools).toHaveBeenCalledWith([]);
  fireEvent.click(within(section).getByRole("button", { name: "All" }));
  expect(onChangeBuiltinTools).toHaveBeenLastCalledWith(["rag"]);
});

it("always documents the built-in memory surface", () => {
  renderPicker();
  expect(
    screen.getByText(
      "Always on and built in — not configurable. partner_read sees the owner's shared memory plus the partner's own; partner_memorize writes only the partner's own memory; partner_search keyword-searches past conversations.",
    ),
  ).toBeInTheDocument();
});

it("hides the MCP tools section when no MCP servers are configured", () => {
  renderPicker({ options: { ...options, mcp_tools: [] } });
  expect(screen.queryByText("MCP tools")).not.toBeInTheDocument();
  expect(screen.queryByTestId("mcp-groups")).not.toBeInTheDocument();
});

it("grants an individual MCP tool through the grouped rows", () => {
  const onChangeMcpTools = vi.fn();
  renderPicker({ mcpTools: [], onChangeMcpTools });
  expect(screen.getByTestId("mcp-groups")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /wiki_search/ }));
  expect(onChangeMcpTools).toHaveBeenCalledWith(["wiki_search"]);
});

it("revokes an individual MCP tool through the grouped rows", () => {
  const onChangeMcpTools = vi.fn();
  renderPicker({ mcpTools: ["wiki_read", "wiki_search"], onChangeMcpTools });
  expect(screen.getByRole("checkbox", { name: /wiki_read/ })).toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: /wiki_read/ }));
  expect(onChangeMcpTools).toHaveBeenCalledWith(["wiki_search"]);
});

it("MCP tools All and None grant every tool or clear the whitelist", () => {
  const onChangeMcpTools = vi.fn();
  renderPicker({ onChangeMcpTools });
  const section = screen.getByRole("heading", { name: "MCP tools" })
    .parentElement as HTMLElement;
  fireEvent.click(within(section).getByRole("button", { name: "All" }));
  expect(onChangeMcpTools).toHaveBeenCalledWith(["wiki_read", "wiki_search"]);
  fireEvent.click(within(section).getByRole("button", { name: "None" }));
  expect(onChangeMcpTools).toHaveBeenLastCalledWith([]);
});
