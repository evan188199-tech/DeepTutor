import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import McpServerRow from "@/components/mcp/McpServerRow";
import {
  emptyMcpServerConfig,
  type McpServerConfig,
  type McpStatusRow,
} from "@/lib/mcp-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? key.replace(/{{(\w+)}}/g, (_, name) => String(opts[name] ?? ""))
        : key,
  }),
}));

function cfg(patch: Partial<McpServerConfig> = {}): McpServerConfig {
  return { ...emptyMcpServerConfig(), ...patch };
}

function statusRow(patch: Partial<McpStatusRow> = {}): McpStatusRow {
  return {
    name: "search",
    transport: "streamableHttp",
    status: "connected",
    error: "",
    tools: [{ name: "search_web", description: "run a web search" }],
    ...patch,
  };
}

function renderRow(
  props: Partial<Parameters<typeof McpServerRow>[0]> & { name: string },
) {
  const handlers = {
    onToggleExpanded: vi.fn(),
    onToggleEnabled: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
  };
  const view = render(
    <McpServerRow
      cfg={cfg()}
      status={undefined}
      isExpanded={false}
      saving={false}
      {...handlers}
      {...props}
    />,
  );
  return { ...view, handlers };
}

it("renders the name, live transport badge, endpoint and tool count", () => {
  renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
    status: statusRow(),
  });
  expect(screen.getByText("search")).toBeInTheDocument();
  // The badge uppercases via CSS, so the DOM text keeps the raw transport id.
  expect(screen.getByText("streamableHttp")).toBeInTheDocument();
  expect(screen.getByText(/https:\/\/api\.example\.com\/mcp/)).toBeInTheDocument();
  expect(screen.getByText(/1 tools/)).toBeInTheDocument();
});

it("resolves the transport from the URL when no status row exists yet", () => {
  renderRow({
    name: "events",
    cfg: cfg({ url: "https://api.example.com/events/sse" }),
    status: undefined,
  });
  expect(screen.getByText("sse")).toBeInTheDocument();
  // No live row yet: enabled + missing status reads as connecting, not broken.
  expect(screen.getByText("Connecting")).toBeInTheDocument();
});

it("keeps a disabled server labelled Disabled even with a connected status row", () => {
  renderRow({
    name: "search",
    cfg: cfg({ enabled: false, url: "https://api.example.com/mcp" }),
    status: statusRow({ status: "connected" }),
  });
  expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
});

it("surfaces the live error message for a failed server", () => {
  renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
    status: statusRow({ status: "error", error: "handshake refused" }),
  });
  expect(screen.getByText("Error")).toBeInTheDocument();
  // Once inline under the row, once as the badge's tooltip text.
  expect(screen.getAllByText("handshake refused").length).toBe(2);
});

it("labels a server with no command or URL Not configured", () => {
  renderRow({ name: "empty", cfg: cfg() });
  expect(screen.getByText(/Not configured/)).toBeInTheDocument();
  expect(screen.getByText(/0 tools/)).toBeInTheDocument();
});

it("lists stored secret fields as configured markers", () => {
  renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
    secretFields: ["api_key"],
  });
  expect(screen.getByText("api_key")).toBeInTheDocument();
  expect(screen.getAllByText("configured").length).toBeGreaterThan(0);
});

it("offers Connect to an ungranted OAuth server and forwards the grant", () => {
  const onAuthorize = vi.fn();
  renderRow({
    name: "search",
    cfg: cfg({ auth: "oauth", url: "https://api.example.com/mcp" }),
    onAuthorize,
    oauthAuthorized: false,
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(onAuthorize).toHaveBeenCalledOnce();
});

it("switches the OAuth affordance to Reauthorize once granted", () => {
  renderRow({
    name: "search",
    cfg: cfg({ auth: "oauth", url: "https://api.example.com/mcp" }),
    onAuthorize: vi.fn(),
    oauthAuthorized: true,
  });
  expect(
    screen.getByRole("button", { name: "Reauthorize" }),
  ).toBeInTheDocument();
});

it("offers no OAuth affordance on a plain server", () => {
  renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
    onAuthorize: vi.fn(),
  });
  expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
});

it("mirrors the enabled state in the switch and fires on toggle", () => {
  const { handlers, rerender } = renderRow({
    name: "search",
    cfg: cfg({ enabled: true, url: "https://api.example.com/mcp" }),
  });
  const as = (enabled: boolean) => (
    <McpServerRow
      name="search"
      cfg={cfg({ enabled, url: "https://api.example.com/mcp" })}
      status={undefined}
      isExpanded={false}
      saving={false}
      onToggleExpanded={handlers.onToggleExpanded}
      onToggleEnabled={handlers.onToggleEnabled}
      onEdit={handlers.onEdit}
      onDelete={handlers.onDelete}
    />
  );
  const on = screen.getByRole("switch", { name: "Enabled" });
  expect(on).toHaveAttribute("aria-checked", "true");
  fireEvent.click(on);
  expect(handlers.onToggleEnabled).toHaveBeenCalledOnce();
  rerender(as(false));
  const off = screen.getByRole("switch", { name: "Disabled" });
  expect(off).toHaveAttribute("aria-checked", "false");
});

it("expands the row through the summary button", () => {
  const { container, handlers } = renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
  });
  const summary = container.querySelector("button[aria-expanded]");
  expect(summary).not.toBeNull();
  expect(summary).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(summary!);
  expect(handlers.onToggleExpanded).toHaveBeenCalledOnce();
});

it("forwards edit and delete from the icon buttons", () => {
  const { handlers } = renderRow({
    name: "search",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(handlers.onEdit).toHaveBeenCalledOnce();
  expect(handlers.onDelete).toHaveBeenCalledOnce();
});

it("locks every inline action while saving", () => {
  renderRow({
    name: "search",
    cfg: cfg({ auth: "oauth", url: "https://api.example.com/mcp" }),
    onAuthorize: vi.fn(),
    saving: true,
  });
  expect(screen.getByRole("switch", { name: "Enabled" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
});

it("prefers the catalog entry's brand mark and falls back to the plug", () => {
  const plain = renderRow({
    name: "private-helper",
    cfg: cfg({ url: "https://api.example.com/mcp" }),
  });
  expect(screen.queryByTitle("Brave")).toBeNull();
  plain.unmount();
  renderRow({
    name: "renamed-by-installer",
    cfg: cfg({ catalog_entry: "brave-search", url: "https://api.example.com/mcp" }),
  });
  expect(screen.getByTitle("Brave")).toBeInTheDocument();
});
