import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { McpSurface } from "@/components/mcp/surface";
import { useMcpServers } from "@/hooks/useMcpServers";
import type {
  McpServerConfig,
  McpStatusRow,
  McpStoreState,
  McpUserView,
} from "@/lib/mcp-api";

/**
 * The hook is tested at its API boundary: the surface read/write helpers, the
 * OAuth authorize call, the workspace usage probe and the error describer are
 * all module mocks, so no request layer is involved and the hook's own state
 * machine is what the assertions see.
 */
const fx = vi.hoisted(() => ({
  loadMcpSurface: vi.fn(),
  writeMcpSurface: vi.fn(),
  deleteMcpSurfaceServer: vi.fn(),
  authorizeSpaceMcpServer: vi.fn(),
  resourceUsage: vi.fn(),
  describeMcpError: vi.fn(),
  t: (key: string, params?: Record<string, unknown>) =>
    key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
      String(params?.[name] ?? ""),
    ),
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fx.t }) }));
vi.mock("@/components/mcp/surface", () => ({
  loadMcpSurface: fx.loadMcpSurface,
  writeMcpSurface: fx.writeMcpSurface,
  deleteMcpSurfaceServer: fx.deleteMcpSurfaceServer,
}));
vi.mock("@/lib/mcp-api", () => ({
  authorizeSpaceMcpServer: fx.authorizeSpaceMcpServer,
}));
vi.mock("@/lib/mcp-store", () => ({ describeMcpError: fx.describeMcpError }));
vi.mock("@/lib/workspaces-api", () => ({ resourceUsage: fx.resourceUsage }));

const registrySurface: McpSurface = {
  basePath: "/api/settings/mcp",
  transports: ["stdio"],
  writes: "registry",
};

const spaceSurface: McpSurface = {
  basePath: "/api/space/mcp",
  transports: ["sse", "streamableHttp"],
  writes: "per-server",
};

function makeCfg(overrides: Partial<McpServerConfig> = {}): McpServerConfig {
  return {
    type: "stdio",
    command: "uvx",
    args: [],
    env: {},
    cwd: "",
    url: "",
    headers: {},
    tool_timeout: 30,
    enabled_tools: [],
    disabled_tools: [],
    enabled: true,
    auth: "",
    catalog_entry: "",
    ...overrides,
  };
}

function statusRow(
  name: string,
  status: McpStatusRow["status"],
): McpStatusRow {
  return { name, transport: "stdio", status, error: "", tools: [] };
}

const baseServers = {
  alpha: makeCfg(),
  beta: makeCfg({
    type: "sse",
    command: "",
    url: "https://mcp.example/sse",
    enabled: false,
  }),
};

const registryState: McpStoreState = {
  servers: baseServers,
  status: [statusRow("alpha", "connected")],
  user: null,
};

const userView: McpUserView = {
  configuredSecrets: { alpha: ["headers.Authorization"] },
  rejected: [],
  deployment: { servers: [], status: [] },
  maxServers: 3,
  oauth: {},
};

const spaceState: McpStoreState = {
  servers: baseServers,
  status: [statusRow("alpha", "needs_auth")],
  user: userView,
};

function lastWrittenNext(): Record<string, McpServerConfig> {
  const calls = fx.writeMcpSurface.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][2] as Record<string, McpServerConfig>;
}

async function renderLoaded(surface: McpSurface, state: McpStoreState) {
  fx.loadMcpSurface.mockResolvedValue(state);
  const utils = renderHook(() => useMcpServers(surface));
  await waitFor(() =>
    expect(utils.result.current.servers).toEqual(state.servers),
  );
  return utils;
}

beforeEach(() => {
  fx.loadMcpSurface.mockReset();
  fx.writeMcpSurface.mockReset();
  fx.deleteMcpSurfaceServer.mockReset();
  fx.authorizeSpaceMcpServer.mockReset();
  fx.resourceUsage.mockReset();
  fx.describeMcpError
    .mockReset()
    .mockImplementation(
      (err: unknown) => (err instanceof Error ? err.message : String(err)),
    );
});

describe("useMcpServers", () => {
  it("loads the surface on mount and maps status rows by name", async () => {
    const { result } = await renderLoaded(spaceSurface, spaceState);

    expect(fx.loadMcpSurface).toHaveBeenCalledWith(spaceSurface);
    expect(result.current.servers).toEqual(baseServers);
    expect(result.current.serverNames).toEqual(["alpha", "beta"]);
    expect(result.current.userView).toBe(userView);
    expect(result.current.statusByName.get("alpha")).toEqual(
      statusRow("alpha", "needs_auth"),
    );
    expect(result.current.loadError).toBeNull();
  });

  it("reports a load error and keeps the list empty when the read fails", async () => {
    fx.loadMcpSurface.mockRejectedValue(new Error("surface read failed"));

    const { result } = renderHook(() => useMcpServers(registrySurface));

    await waitFor(() =>
      expect(result.current.loadError).toBe("surface read failed"),
    );
    expect(result.current.servers).toBeNull();
    expect(result.current.serverNames).toEqual([]);
  });

  it("renders an empty registry as an empty, non-null list", async () => {
    const empty: McpStoreState = { servers: {}, status: [], user: null };

    const { result } = await renderLoaded(registrySurface, empty);

    expect(result.current.servers).toEqual({});
    expect(result.current.serverNames).toEqual([]);
    expect(result.current.loadError).toBeNull();
  });

  it("reload re-reads the surface and adopts the fresh snapshot", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    const refreshed: McpStoreState = {
      servers: { gamma: makeCfg({ command: "npx" }) },
      status: [statusRow("gamma", "connecting")],
      user: null,
    };
    fx.loadMcpSurface.mockResolvedValue(refreshed);

    await act(async () => {
      await result.current.reload();
    });

    expect(fx.loadMcpSurface).toHaveBeenCalledTimes(2);
    expect(result.current.servers).toEqual(refreshed.servers);
    expect(result.current.serverNames).toEqual(["gamma"]);
    expect(result.current.statusByName.get("gamma")?.status).toBe("connecting");
  });

  it("toggleEnabled writes the flipped config and adopts the reported state", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    const written: McpStoreState = {
      servers: { ...baseServers, alpha: makeCfg({ enabled: false }) },
      status: [statusRow("alpha", "disabled")],
      user: null,
    };
    fx.writeMcpSurface.mockResolvedValue(written);

    await act(async () => {
      await result.current.toggleEnabled("alpha");
    });

    expect(fx.writeMcpSurface).toHaveBeenCalledTimes(1);
    const [calledSurface, previous, next] = fx.writeMcpSurface.mock.calls[0];
    expect(calledSurface).toBe(registrySurface);
    expect(previous).toBe(baseServers);
    expect(
      (next as Record<string, McpServerConfig>).alpha?.enabled,
    ).toBe(false);
    expect(
      (next as Record<string, McpServerConfig>).beta,
    ).toBe(baseServers.beta);
    expect(result.current.servers).toEqual(written.servers);
    expect(result.current.statusByName.get("alpha")?.status).toBe("disabled");
    expect(result.current.saving).toBe(false);
    expect(result.current.saveError).toBeNull();
  });

  it("toggleEnabled is a no-op for a name the registry does not hold", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    await act(async () => {
      await result.current.toggleEnabled("ghost");
    });

    expect(fx.writeMcpSurface).not.toHaveBeenCalled();
    expect(result.current.saveError).toBeNull();
  });

  it("ignores a toggle while a save is still in flight", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    let release!: (state: McpStoreState) => void;
    const gate = new Promise<McpStoreState>((resolve) => {
      release = resolve;
    });
    fx.writeMcpSurface.mockReturnValue(gate);

    let first!: Promise<void>;
    await act(async () => {
      first = result.current.toggleEnabled("alpha");
    });
    await waitFor(() => expect(result.current.saving).toBe(true));

    await act(async () => {
      await result.current.toggleEnabled("beta");
    });

    expect(fx.writeMcpSurface).toHaveBeenCalledTimes(1);

    release({
      servers: { ...baseServers, alpha: makeCfg({ enabled: false }) },
      status: [],
      user: null,
    });
    await act(async () => {
      await first;
    });

    expect(result.current.saving).toBe(false);
    expect(result.current.servers).toEqual({
      ...baseServers,
      alpha: makeCfg({ enabled: false }),
    });
  });

  it("save adds a new server, closes the editor and reports success", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    act(() => {
      result.current.startAdding();
    });
    expect(result.current.editingKey).toBe("");

    const cfg = makeCfg({ type: "sse", command: "", url: "https://x/sse" });
    fx.writeMcpSurface.mockResolvedValue({
      servers: { ...baseServers, gamma: cfg },
      status: registryState.status,
      user: null,
    });

    let ok!: boolean;
    await act(async () => {
      ok = await result.current.save("", "gamma", cfg);
    });

    expect(ok).toBe(true);
    expect(result.current.editingKey).toBeNull();
    expect(Object.keys(lastWrittenNext()).sort()).toEqual([
      "alpha",
      "beta",
      "gamma",
    ]);
    expect(result.current.servers).toEqual({
      ...baseServers,
      gamma: cfg,
    });
  });

  it("save renames by dropping the old key and carrying the config through", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    act(() => {
      result.current.toggleEditing("alpha");
    });
    expect(result.current.editingKey).toBe("alpha");

    const renamed = makeCfg({ enabled: false, command: "pipx" });
    fx.writeMcpSurface.mockResolvedValue({
      servers: { ...baseServers, alpha: renamed },
      status: registryState.status,
      user: null,
    });

    let ok!: boolean;
    await act(async () => {
      ok = await result.current.save("alpha", "alpha2", renamed);
    });

    expect(ok).toBe(true);
    const next = lastWrittenNext();
    expect(next).not.toHaveProperty("alpha");
    expect(next.alpha2).toBe(renamed);
    expect(result.current.editingKey).toBeNull();
  });

  it("a refused save surfaces the error, re-reads the surface and returns false", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    fx.writeMcpSurface.mockRejectedValue(new Error("write refused"));

    let ok!: boolean;
    await act(async () => {
      ok = await result.current.save("", "gamma", makeCfg());
    });

    expect(ok).toBe(false);
    expect(result.current.saveError).toBe("write refused");
    expect(fx.loadMcpSurface).toHaveBeenCalledTimes(2);
    expect(result.current.servers).toEqual(registryState.servers);
    expect(result.current.saving).toBe(false);
  });

  it("remove confirms with workspace impact, persists the deletion and closes the editor", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    act(() => {
      result.current.toggleEditing("alpha");
    });
    fx.resourceUsage.mockResolvedValue(["WS A", "WS B"]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    fx.writeMcpSurface.mockResolvedValue({
      servers: { beta: baseServers.beta },
      status: [],
      user: null,
    });

    await act(async () => {
      await result.current.remove("alpha");
    });

    expect(fx.resourceUsage).toHaveBeenCalledWith("mcp", "deployment:alpha");
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    const prompt = String(confirmSpy.mock.calls[0][0]);
    expect(prompt).toContain('Delete MCP server "alpha"?');
    expect(prompt).toContain("Used by workspaces: WS A, WS B");
    expect(Object.keys(lastWrittenNext())).toEqual(["beta"]);
    expect(result.current.servers).toEqual({ beta: baseServers.beta });
    expect(result.current.editingKey).toBeNull();
    expect(result.current.saving).toBe(false);
  });

  it("remove writes nothing when the confirmation is declined", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    fx.resourceUsage.mockResolvedValue([]);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    await act(async () => {
      await result.current.remove("alpha");
    });

    expect(fx.resourceUsage).toHaveBeenCalledTimes(1);
    expect(fx.writeMcpSurface).not.toHaveBeenCalled();
    expect(result.current.saveError).toBeNull();
    expect(result.current.servers).toEqual(baseServers);
  });

  it("remove reports a usage probe failure instead of deleting", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);

    fx.resourceUsage.mockRejectedValue(new Error("usage probe failed"));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    await act(async () => {
      await result.current.remove("alpha");
    });

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(fx.writeMcpSurface).not.toHaveBeenCalled();
    expect(result.current.saveError).toBe("usage probe failed");
  });

  it("removeRejected is a no-op on a registry surface", async () => {
    const { result } = await renderLoaded(registrySurface, registryState);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    await act(async () => {
      await result.current.removeRejected("ghost");
    });

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(fx.deleteMcpSurfaceServer).not.toHaveBeenCalled();
    expect(result.current.saving).toBe(false);
  });

  it("removeRejected deletes directly on a per-server surface after confirmation", async () => {
    const { result } = await renderLoaded(spaceSurface, spaceState);

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const afterDelete: McpStoreState = {
      servers: { beta: baseServers.beta },
      status: [],
      user: userView,
    };
    fx.deleteMcpSurfaceServer.mockResolvedValue(afterDelete);

    await act(async () => {
      await result.current.removeRejected("alpha");
    });

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(fx.deleteMcpSurfaceServer).toHaveBeenCalledWith(
      spaceSurface,
      "alpha",
    );
    expect(result.current.servers).toEqual(afterDelete.servers);
    expect(result.current.saving).toBe(false);
  });

  it("authorize opens the provider URL in a new tab", async () => {
    const { result } = await renderLoaded(spaceSurface, spaceState);

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    fx.authorizeSpaceMcpServer.mockResolvedValue(
      "https://idp.example/authorize",
    );

    await act(async () => {
      await result.current.authorize("alpha");
    });

    expect(fx.authorizeSpaceMcpServer).toHaveBeenCalledWith(
      spaceSurface.basePath,
      "alpha",
    );
    expect(openSpy).toHaveBeenCalledWith(
      "https://idp.example/authorize",
      "_blank",
      "noopener",
    );
    expect(result.current.saving).toBe(false);
    expect(result.current.saveError).toBeNull();
  });

  it("authorize reports an error when no authorization URL comes back", async () => {
    const { result } = await renderLoaded(spaceSurface, spaceState);

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    fx.authorizeSpaceMcpServer.mockResolvedValue("");

    await act(async () => {
      await result.current.authorize("alpha");
    });

    expect(openSpy).not.toHaveBeenCalled();
    expect(result.current.saveError).toBe("no authorization URL");
    expect(result.current.saving).toBe(false);
  });
});
