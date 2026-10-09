import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSettingsPresets, type SettingsPresetsPayload } from "@/lib/settings-presets";

const api = vi.hoisted(() => ({
  apiFetch: vi.fn<() => Promise<Response>>(),
  apiUrl: vi.fn((path: string) => path),
}));

vi.mock("@/lib/api", () => api);

const payload: SettingsPresetsPayload = {
  schema_version: "deeptutor.settings-presets/v1",
  presets: [
    {
      id: "deep-parse",
      label: "Deep parsing",
      description: "Full document parsing",
      parser: "deep",
      resource_cost: "high",
      credentials: ["key-a"],
      prerequisites: ["gpu"],
      unlocked_features: ["tables"],
    },
  ],
};

function okResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  api.apiFetch.mockResolvedValue(okResponse(payload));
});

describe("fetchSettingsPresets", () => {
  it("fetches the presets endpoint and returns the parsed payload", async () => {
    await expect(fetchSettingsPresets()).resolves.toEqual(payload);
    expect(api.apiUrl).toHaveBeenCalledWith("/api/settings/presets");
    expect(api.apiFetch).toHaveBeenCalledTimes(1);
    expect(api.apiFetch).toHaveBeenCalledWith("/api/settings/presets");
  });

  it("throws a status-bearing error when the server rejects the request", async () => {
    api.apiFetch.mockResolvedValue(new Response("boom", { status: 500 }));

    await expect(fetchSettingsPresets()).rejects.toThrow(
      "Settings presets failed: HTTP 500",
    );
  });

  it("reports missing presets endpoints with their HTTP status", async () => {
    api.apiFetch.mockResolvedValue(new Response("missing", { status: 404 }));

    await expect(fetchSettingsPresets()).rejects.toThrow(
      "Settings presets failed: HTTP 404",
    );
  });

  it("propagates network failures from the API client without retrying", async () => {
    api.apiFetch.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(fetchSettingsPresets()).rejects.toThrow("Failed to fetch");
    expect(api.apiFetch).toHaveBeenCalledTimes(1);
  });
});
