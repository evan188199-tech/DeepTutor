import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  importVisualizer,
  installBundledVisualizer,
  listVisualizers,
  setVisualizerEnabled,
  uninstallVisualizer,
  type VisualizerCatalogItem,
} from "@/lib/visualizers-api";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

const apiFetchMock = vi.mocked(apiFetch);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function catalogItem(
  overrides: Partial<VisualizerCatalogItem> = {},
): VisualizerCatalogItem {
  return {
    id: "chartjs",
    version: "1.2.0",
    display_name: "Chart.js",
    description: "Render data charts",
    render_target: "native",
    native_renderer: "chartjs",
    origin: "core",
    installed: true,
    enabled: true,
    uninstallable: false,
    agentic: false,
    ...overrides,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("visualizers api", () => {
  it("lists visualizers from the catalog endpoint without caching", async () => {
    const catalog = [
      catalogItem(),
      catalogItem({ id: "mermaid", native_renderer: "mermaid" }),
    ];
    apiFetchMock.mockResolvedValue(jsonResponse({ visualizers: catalog }));

    await expect(listVisualizers()).resolves.toEqual(catalog);
    expect(apiFetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/visualizers/list",
      { cache: "no-store" },
    );
  });

  it("surfaces the backend detail message when the catalog request fails", async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ detail: "catalog is unavailable" }, 503),
    );

    await expect(listVisualizers()).rejects.toThrow("catalog is unavailable");
  });

  it("falls back to a status message when the error body has no detail", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ error: "boom" }, 500));

    await expect(listVisualizers()).rejects.toThrow("Request failed (500)");
  });

  it("tolerates a non-JSON error body and reports the status", async () => {
    apiFetchMock.mockResolvedValue(new Response("Bad Gateway", { status: 502 }));

    await expect(listVisualizers()).rejects.toThrow("Request failed (502)");
  });

  it("posts to the encoded bundled install endpoint", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await expect(
      installBundledVisualizer("space viz/v2"),
    ).resolves.toBeUndefined();
    expect(apiFetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/visualizers/bundled/space%20viz%2Fv2/install",
      { method: "POST" },
    );
  });

  it("reports install conflicts for bundled visualizers", async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ detail: "already installed" }, 409),
    );

    await expect(installBundledVisualizer("chartjs")).rejects.toThrow(
      "already installed",
    );
  });

  it("posts enable and disable to the matching endpoints", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await setVisualizerEnabled("mermaid", true);
    await setVisualizerEnabled("mermaid", false);

    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(apiFetchMock.mock.calls[0]).toEqual([
      "/api/visualizers/mermaid/enable",
      { method: "POST" },
    ]);
    expect(apiFetchMock.mock.calls[1]).toEqual([
      "/api/visualizers/mermaid/disable",
      { method: "POST" },
    ]);
  });

  it("propagates errors when toggling a visualizer fails", async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ detail: "visualizer is locked" }, 409),
    );

    await expect(setVisualizerEnabled("geogebra", true)).rejects.toThrow(
      "visualizer is locked",
    );
  });

  it("sends DELETE to the encoded uninstall endpoint", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await expect(uninstallVisualizer("user viz#1")).resolves.toBeUndefined();
    expect(apiFetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/visualizers/user%20viz%231",
      { method: "DELETE" },
    );
  });

  it("reports unknown visualizers on uninstall", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ detail: "not found" }, 404));

    await expect(uninstallVisualizer("ghost")).rejects.toThrow("not found");
  });

  it("uploads the imported package file as multipart form data", async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    const file = new File(["<svg />"], "viz.svg", {
      type: "image/svg+xml",
    });

    await expect(importVisualizer(file)).resolves.toBeUndefined();
    expect(apiFetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/visualizers/import",
      { method: "POST", body: expect.any(FormData) },
    );
    const body = apiFetchMock.mock.calls[0][1]?.body as FormData;
    expect(body.get("file")).toBe(file);
  });

  it("surfaces the rejection reason for an invalid import", async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ detail: "package too large" }, 413),
    );
    const file = new File(["junk"], "viz.zip", { type: "application/zip" });

    await expect(importVisualizer(file)).rejects.toThrow("package too large");
  });
});
