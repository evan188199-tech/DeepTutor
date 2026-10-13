import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import McpStoreSection from "@/components/space/McpStoreSection";
import {
  emptyMcpServerConfig,
  type McpServerConfig,
  type McpStatusRow,
  type McpUserView,
} from "@/lib/mcp-api";

const fixtures = vi.hoisted(() => ({
  auth: vi.fn(),
  mcp: vi.fn(),
  applyState: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? key.replace(/{{(\w+)}}/g, (_, name) => String(opts[name] ?? ""))
        : key,
  }),
}));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => fixtures.auth(),
}));
vi.mock("@/hooks/useMcpServers", () => ({
  useMcpServers: () => fixtures.mcp(),
}));
vi.mock("@/components/mcp/McpAdminRegistry", () => ({
  default: () => <div data-testid="admin-registry" />,
}));
vi.mock("@/components/mcp/McpCatalogBrowser", () => ({
  default: (props: {
    surface: { basePath: string };
    installedServers: Record<string, McpServerConfig> | null;
    atCapacity: boolean;
    onInstalled: (state: unknown) => void;
  }) => (
    <div
      data-testid="catalog-browser"
      data-surface={props.surface.basePath}
      data-installed={
        props.installedServers
          ? Object.keys(props.installedServers).join(",")
          : "null"
      }
      data-at-capacity={String(props.atCapacity)}
    >
      <button type="button" onClick={() => props.onInstalled("applied")}>
        catalog-installed
      </button>
    </div>
  ),
}));
vi.mock("@/components/mcp/McpServerList", () => ({
  default: (props: {
    names: string[];
    statusByName: Record<string, unknown>;
    configuredSecrets?: Record<string, string[]>;
    oauth?: Record<string, unknown>;
    saving: boolean;
    editingName: string | null;
  }) => (
    <div
      data-testid="server-list"
      data-names={props.names.join(",")}
      data-status={Object.keys(props.statusByName).join(",")}
      data-secrets={Object.keys(props.configuredSecrets ?? {}).join(",")}
      data-oauth={Object.keys(props.oauth ?? {}).join(",")}
      data-saving={String(props.saving)}
      data-editing={props.editingName ?? ""}
    />
  ),
}));
vi.mock("@/components/mcp/McpServerForm", () => ({
  default: (props: { originalName: string; existingNames: string[] }) => (
    <div
      data-testid="server-form"
      data-original={props.originalName}
      data-existing={props.existingNames.join(",")}
    />
  ),
}));
vi.mock("@/components/mcp/McpDeploymentList", () => ({
  default: (props: { names: string[]; statusRows: McpStatusRow[] }) => (
    <div
      data-testid="deployment-list"
      data-names={props.names.join(",")}
      data-status-count={String(props.statusRows.length)}
    />
  ),
}));

function cfg(patch: Partial<McpServerConfig> = {}): McpServerConfig {
  return { ...emptyMcpServerConfig(), ...patch };
}

function userView(patch: Partial<McpUserView> = {}): McpUserView {
  return {
    configuredSecrets: { alpha: ["api_key"] },
    rejected: [],
    deployment: {
      servers: ["shared-deploy"],
      status: [
        {
          name: "shared-deploy",
          transport: "streamableHttp",
          status: "connected",
          error: "",
          tools: [],
        },
      ],
    },
    maxServers: 0,
    oauth: { alpha: { required: true, authorized: false } },
    ...patch,
  };
}

function mcpState(patch: Record<string, unknown> = {}) {
  const servers = {
    alpha: cfg({ url: "https://alpha.example.com/mcp" }),
    beta: cfg({ url: "https://beta.example.com/sse" }),
  };
  return {
    servers,
    serverNames: ["alpha", "beta"],
    statusByName: { alpha: { status: "connected" } },
    userView: userView(),
    loadError: null,
    saveError: null,
    saving: false,
    expanded: null,
    editingKey: "",
    applyState: fixtures.applyState,
    toggleExpanded: vi.fn(),
    toggleEnabled: vi.fn(),
    toggleEditing: vi.fn(),
    startAdding: vi.fn(),
    cancelEditing: vi.fn(),
    remove: vi.fn(),
    removeRejected: vi.fn().mockResolvedValue(true),
    save: vi.fn().mockResolvedValue(true),
    authorize: vi.fn().mockResolvedValue(true),
    ...patch,
  };
}

beforeEach(() => {
  fixtures.auth.mockReset().mockReturnValue({ isAdmin: false, loading: false });
  fixtures.mcp.mockReset().mockReturnValue(mcpState());
  fixtures.applyState.mockReset();
});

it("shows the loading spinner and nothing else before the first load", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({ servers: null, serverNames: [], userView: null }),
  );
  const { container } = render(<McpStoreSection />);
  expect(container.querySelector(".animate-spin")).not.toBeNull();
  expect(screen.queryByTestId("server-list")).toBeNull();
  expect(screen.queryByTestId("server-form")).toBeNull();
  expect(screen.queryByTestId("deployment-list")).toBeNull();
});

it("assembles the installed list from the loaded state", () => {
  render(<McpStoreSection />);
  const list = screen.getByTestId("server-list");
  expect(list).toHaveAttribute("data-names", "alpha,beta");
  expect(list).toHaveAttribute("data-status", "alpha");
  expect(list).toHaveAttribute("data-secrets", "alpha");
  expect(list).toHaveAttribute("data-oauth", "alpha");
  expect(list).toHaveAttribute("data-saving", "false");
});

it("counts usage against the cap in the header meta", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({ userView: userView({ maxServers: 3 }) }),
  );
  render(<McpStoreSection />);
  expect(screen.getByText("2 / 3 connected")).toBeInTheDocument();
  // The Installed tab carries the same count as its badge.
  expect(screen.getByRole("button", { name: /Installed/ })).toHaveTextContent(
    "2",
  );
});

it("counts without a cap when the backend reports none", () => {
  render(<McpStoreSection />);
  expect(screen.getByText("2 connected")).toBeInTheDocument();
});

it("keeps the empty installed state usable", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({
      servers: {},
      serverNames: [],
      statusByName: {},
      userView: userView({ maxServers: 5 }),
    }),
  );
  render(<McpStoreSection />);
  expect(screen.getByText("0 / 5 connected")).toBeInTheDocument();
  expect(screen.getByTestId("server-list")).toHaveAttribute("data-names", "");
  // Nothing installed yet, so the add form is offered immediately.
  expect(screen.getByTestId("server-form")).toBeInTheDocument();
});

it("hands the store tab the space surface, installs and capacity wiring", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({ userView: userView({ maxServers: 2 }) }),
  );
  render(<McpStoreSection />);
  fireEvent.click(screen.getByRole("button", { name: /Store/ }));
  const browser = screen.getByTestId("catalog-browser");
  expect(browser).toHaveAttribute("data-surface", "/api/space/mcp");
  expect(browser).toHaveAttribute("data-installed", "alpha,beta");
  expect(browser).toHaveAttribute("data-at-capacity", "true");
  // A catalog install flows back through applyState.
  fireEvent.click(screen.getByRole("button", { name: "catalog-installed" }));
  expect(fixtures.applyState).toHaveBeenCalledWith("applied");
  // And back to the installed tab.
  fireEvent.click(screen.getByRole("button", { name: /Installed/ }));
  expect(screen.getByTestId("server-list")).toBeInTheDocument();
});

it("surfaces a load failure instead of an empty list", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({
      servers: null,
      serverNames: [],
      userView: null,
      loadError: "backend unreachable",
    }),
  );
  render(<McpStoreSection />);
  expect(
    screen.getByText(/Failed to load MCP servers: backend unreachable/),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("server-list")).toBeNull();
});

it("surfaces a save failure alongside the list", () => {
  fixtures.mcp.mockReturnValue(mcpState({ saveError: "name already taken" }));
  render(<McpStoreSection />);
  expect(screen.getByText(/Failed to save: name already taken/)).toBeInTheDocument();
});

it("offers the inline add form while no row is being edited", () => {
  render(<McpStoreSection />);
  const form = screen.getByTestId("server-form");
  expect(form).toHaveAttribute("data-original", "");
  expect(form).toHaveAttribute("data-existing", "alpha,beta");
});

it("swaps the form for the add/browse row while editing, then wires both", () => {
  fixtures.mcp.mockReturnValue(mcpState({ editingKey: "alpha" }));
  render(<McpStoreSection />);
  expect(screen.queryByTestId("server-form")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Add a server by URL/ }));
  expect(fixtures.mcp().startAdding).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Browse the store/ }));
  expect(screen.getByTestId("catalog-browser")).toBeInTheDocument();
});

it("blocks adding at capacity and says why", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({
      editingKey: "alpha",
      userView: userView({ maxServers: 2 }),
    }),
  );
  render(<McpStoreSection />);
  const add = screen.getByRole("button", { name: /Add a server by URL/ });
  expect(add).toBeDisabled();
  expect(
    screen.getByText(
      "You have reached your MCP server limit. Remove one first.",
    ),
  ).toBeInTheDocument();
});

it("lists rejected servers with their reason and removes them", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({
      userView: userView({
        rejected: [{ name: "broken", reason: "unsupported transport" }],
      }),
    }),
  );
  render(<McpStoreSection />);
  expect(screen.getByText("Not connected")).toBeInTheDocument();
  expect(screen.getByText("broken")).toBeInTheDocument();
  expect(screen.getByText("unsupported transport")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(fixtures.mcp().removeRejected).toHaveBeenCalledWith("broken");
});

it("locks rejected-row removal while saving", () => {
  fixtures.mcp.mockReturnValue(
    mcpState({
      saving: true,
      userView: userView({
        rejected: [{ name: "broken", reason: "unsupported transport" }],
      }),
    }),
  );
  render(<McpStoreSection />);
  expect(screen.getByRole("button", { name: "Remove" })).toBeDisabled();
});

it("gates the bottom block on the admin role", () => {
  fixtures.auth.mockReturnValue({ isAdmin: false, loading: true });
  const loading = render(<McpStoreSection />);
  expect(screen.queryByTestId("admin-registry")).toBeNull();
  expect(screen.queryByTestId("deployment-list")).toBeNull();
  loading.unmount();

  fixtures.auth.mockReturnValue({ isAdmin: true, loading: false });
  const admin = render(<McpStoreSection />);
  expect(screen.getByTestId("admin-registry")).toBeInTheDocument();
  expect(screen.queryByTestId("deployment-list")).toBeNull();
  admin.unmount();

  fixtures.auth.mockReturnValue({ isAdmin: false, loading: false });
  render(<McpStoreSection />);
  const deployment = screen.getByTestId("deployment-list");
  expect(deployment).toHaveAttribute("data-names", "shared-deploy");
  expect(deployment).toHaveAttribute("data-status-count", "1");
  expect(screen.queryByTestId("admin-registry")).toBeNull();
});

it("names the per-account storage location", () => {
  render(<McpStoreSection />);
  expect(
    screen.getByText("data/system/user-mcp/<your account>.json"),
  ).toBeInTheDocument();
});
