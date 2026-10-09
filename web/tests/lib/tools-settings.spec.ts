import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => mocks.apiFetch(...args),
}));

type ToolsSettingsModule = typeof import("@/lib/tools-settings");

function apiResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// The cache lives at module scope, so every test imports a fresh instance.
async function importToolsSettings(): Promise<ToolsSettingsModule> {
  return await import("@/lib/tools-settings");
}

beforeEach(() => {
  vi.resetModules();
  mocks.apiFetch.mockReset();
});

describe("getEnabledOptionalTools", () => {
  it("fetches the enabled optional tools from /api/tools", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch.mockResolvedValue(
      apiResponse({ enabled_optional_tools: ["code", "web_search"] }),
    );

    await expect(getEnabledOptionalTools()).resolves.toEqual([
      "code",
      "web_search",
    ]);
    expect(mocks.apiFetch).toHaveBeenCalledExactlyOnceWith("/api/tools");
  });

  it("shares one network round-trip across callers", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    const pending = deferred<Response>();
    mocks.apiFetch.mockReturnValueOnce(pending.promise);

    const first = getEnabledOptionalTools();
    const second = getEnabledOptionalTools();
    pending.resolve(apiResponse({ enabled_optional_tools: ["mcp"] }));
    const [a, b] = await Promise.all([first, second]);

    const cached = await getEnabledOptionalTools();

    expect(a).toEqual(["mcp"]);
    expect(b).toEqual(["mcp"]);
    expect(cached).toEqual(["mcp"]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1);
  });

  it("returns a fresh copy so callers cannot corrupt the cache", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch.mockResolvedValue(
      apiResponse({ enabled_optional_tools: ["code"] }),
    );

    const first = await getEnabledOptionalTools();
    first.push("mutated");

    const cached = await getEnabledOptionalTools();
    expect(cached).toEqual(["code"]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1);
  });

  it("maps a non-array payload to an empty list", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch.mockResolvedValue(
      apiResponse({ enabled_optional_tools: "code" }),
    );

    await expect(getEnabledOptionalTools()).resolves.toEqual([]);
    expect(
      (await getEnabledOptionalTools({ force: true })) as string[],
    ).toEqual([]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  });

  it("rejects on HTTP errors and retries on the next call", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch
      .mockResolvedValueOnce(apiResponse({}, 503))
      .mockResolvedValueOnce(
        apiResponse({ enabled_optional_tools: ["recovered"] }),
      );

    await expect(getEnabledOptionalTools()).rejects.toThrow("HTTP 503");
    await expect(getEnabledOptionalTools()).resolves.toEqual(["recovered"]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  });

  it("rejects on transport failures and clears the failed cache entry", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(apiResponse({ enabled_optional_tools: [] }));

    await expect(getEnabledOptionalTools()).rejects.toThrow("network down");
    await expect(getEnabledOptionalTools()).resolves.toEqual([]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  });

  it("force refetches and adopts the new payload", async () => {
    const { getEnabledOptionalTools } = await importToolsSettings();
    mocks.apiFetch
      .mockResolvedValueOnce(apiResponse({ enabled_optional_tools: ["old"] }))
      .mockResolvedValueOnce(
        apiResponse({ enabled_optional_tools: ["old", "new"] }),
      );

    await expect(getEnabledOptionalTools()).resolves.toEqual(["old"]);
    await expect(getEnabledOptionalTools({ force: true })).resolves.toEqual([
      "old",
      "new",
    ]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);

    await expect(getEnabledOptionalTools()).resolves.toEqual(["old", "new"]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  });
});

describe("invalidateEnabledOptionalToolsCache", () => {
  it("busts the cache so the next read refetches", async () => {
    const { getEnabledOptionalTools, invalidateEnabledOptionalToolsCache } =
      await importToolsSettings();
    mocks.apiFetch
      .mockResolvedValueOnce(apiResponse({ enabled_optional_tools: ["a"] }))
      .mockResolvedValueOnce(apiResponse({ enabled_optional_tools: ["b"] }));

    await expect(getEnabledOptionalTools()).resolves.toEqual(["a"]);
    invalidateEnabledOptionalToolsCache();
    await expect(getEnabledOptionalTools()).resolves.toEqual(["b"]);
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  });
});
