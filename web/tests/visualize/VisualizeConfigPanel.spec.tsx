import React, { useState } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VisualizeConfigPanel from "@/components/visualize/VisualizeConfigPanel";
import type { VisualizeFormConfig } from "@/lib/visualize-types";
import type { VisualizerCatalogItem } from "@/lib/visualizers-api";

/**
 * Behavior coverage for the Visualize config panel: reading the stored form
 * config back into the controls, propagating edits to the parent through
 * `onChange`, and the fallbacks that keep a stale/unknown render mode visible
 * instead of silently snapping to another value. The visualizer catalog API
 * is mocked so the panel drives no network traffic.
 */
const fixture = vi.hoisted(() => ({
  listVisualizers: vi.fn<() => Promise<VisualizerCatalogItem[]>>(),
  installBundledVisualizer: vi.fn<() => Promise<void>>(),
  setVisualizerEnabled: vi.fn<() => Promise<void>>(),
  uninstallVisualizer: vi.fn<() => Promise<void>>(),
  importVisualizer: vi.fn<() => Promise<void>>(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/visualizers-api", () => ({
  listVisualizers: fixture.listVisualizers,
  installBundledVisualizer: fixture.installBundledVisualizer,
  setVisualizerEnabled: fixture.setVisualizerEnabled,
  uninstallVisualizer: fixture.uninstallVisualizer,
  importVisualizer: fixture.importVisualizer,
}));

// Keep the real DOM shape (wrapper span around the trigger) so the install
// button's accessible name comes from its own contents, not the Field label.
vi.mock("@/shared/ui/Tooltip", async () => {
  const React = await import("react");
  return {
    default: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("span", null, children),
  };
});

function catalogItem(
  overrides: Partial<VisualizerCatalogItem> = {},
): VisualizerCatalogItem {
  return {
    id: "geogebra",
    version: "1.0.0",
    display_name: "GeoGebra",
    description: "Interactive geometry",
    render_target: "native",
    native_renderer: "geogebra",
    origin: "bundled",
    installed: true,
    enabled: true,
    uninstallable: false,
    agentic: false,
    ...overrides,
  };
}

function baseConfig(
  overrides: Partial<VisualizeFormConfig> = {},
): VisualizeFormConfig {
  return {
    render_mode: "auto",
    quality: "medium",
    style_hint: "",
    ...overrides,
  };
}

/**
 * Controlled harness mirroring the real parent (StandaloneComposer): the
 * panel's `onChange` output feeds back into `value`, so every read-back
 * assertion below checks the round trip, not a static prop.
 */
function renderPanel({
  initial = baseConfig(),
  collapsed,
}: {
  initial?: VisualizeFormConfig;
  collapsed?: boolean;
} = {}) {
  const changes: VisualizeFormConfig[] = [];
  const onToggleCollapsed = vi.fn();
  function Harness() {
    const [value, setValue] = useState<VisualizeFormConfig>(initial);
    return (
      <VisualizeConfigPanel
        value={value}
        onChange={(next) => {
          changes.push(next);
          setValue(next);
        }}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
      />
    );
  }
  render(<Harness />);
  return { changes, onToggleCollapsed };
}

/** Flush the mount-time catalog fetch inside act so no update leaks. */
async function flushCatalog() {
  await act(async () => {});
}

const renderModeSelect = () =>
  screen.getByRole("combobox", { name: "Render Mode" });
const qualitySelect = () => screen.getByRole("combobox", { name: "Quality" });
const styleHintInput = () => screen.getByRole("textbox", { name: "Style Hint" });

beforeEach(() => {
  fixture.listVisualizers.mockResolvedValue([]);
  fixture.installBundledVisualizer.mockResolvedValue();
  fixture.setVisualizerEnabled.mockResolvedValue();
  fixture.uninstallVisualizer.mockResolvedValue();
});

describe("VisualizeConfigPanel config readback", () => {
  it("renders the stored render mode and falls back to the static type list when no catalog is available", async () => {
    renderPanel({
      initial: baseConfig({ render_mode: "svg", quality: "high" }),
    });
    await flushCatalog();

    const mode = renderModeSelect();
    expect(mode).toHaveValue("svg");
    for (const name of ["Chart.js", "SVG", "Mermaid", "Mind map", "Animation"]) {
      expect(within(mode).getByRole("option", { name })).toBeInTheDocument();
    }
    // A non-auto mode with an empty catalog is preserved as an explicitly
    // disabled "Unavailable" entry instead of snapping to another value.
    const stale = within(mode).getByRole("option", {
      name: "svg (Unavailable)",
    });
    expect(stale).toBeDisabled();

    // Manim-only knobs stay hidden for text render types.
    expect(screen.queryByRole("combobox", { name: "Quality" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Style Hint" }),
    ).not.toBeInTheDocument();
  });

  it("lists enabled catalog visualizers as render-mode options", async () => {
    fixture.listVisualizers.mockResolvedValue([
      catalogItem({ id: "geogebra", display_name: "GeoGebra" }),
      catalogItem({
        id: "plotly",
        display_name: "Plotly",
        installed: true,
        enabled: false,
      }),
      catalogItem({
        id: "wordcloud",
        display_name: "Word cloud",
        origin: "bundled",
        installed: false,
        enabled: false,
      }),
    ]);
    renderPanel();
    expect(
      await screen.findByRole("option", { name: "GeoGebra" }),
    ).toBeInTheDocument();

    const mode = renderModeSelect();
    expect(mode).toHaveValue("auto");
    const names = within(mode)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(names).toEqual(["Auto", "GeoGebra"]);

    // Disabled visualizers surface as enable actions, bundled-but-missing
    // ones as install actions.
    expect(
      screen.getByRole("button", { name: "Enable Plotly" }),
    ).toBeInTheDocument();
    // dom-accessibility-api names the Tooltip-wrapped install button from the
    // enclosing Field label (embedded-control quirk), so match it by content.
    expect(
      screen.getByText("+ Word cloud", { selector: "button" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Plotly" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a stale render mode selectable and marks it unavailable next to live catalog options", async () => {
    fixture.listVisualizers.mockResolvedValue([
      catalogItem({ id: "geogebra", display_name: "GeoGebra" }),
    ]);
    renderPanel({ initial: baseConfig({ render_mode: "mindmap" }) });
    expect(
      await screen.findByRole("option", { name: "GeoGebra" }),
    ).toBeInTheDocument();

    const mode = renderModeSelect();
    expect(mode).toHaveValue("mindmap");
    const stale = within(mode).getByRole("option", {
      name: "mindmap (Unavailable)",
    });
    expect(stale).toBeDisabled();
  });
});

describe("VisualizeConfigPanel config writes", () => {
  it("propagates render-mode and quality edits through onChange", async () => {
    const { changes } = renderPanel();
    await flushCatalog();

    fireEvent.change(renderModeSelect(), { target: { value: "manim_video" } });
    expect(changes).toHaveLength(1);
    expect(changes[0]).toEqual({
      render_mode: "manim_video",
      quality: "medium",
      style_hint: "",
    });

    // Manim modes reveal the quality knob; editing it keeps the other fields.
    fireEvent.change(await qualitySelect(), { target: { value: "low" } });
    expect(changes).toHaveLength(2);
    expect(changes[1]).toMatchObject({
      render_mode: "manim_video",
      quality: "low",
    });
    expect(renderModeSelect()).toHaveValue("manim_video");
    expect(qualitySelect()).toHaveValue("low");
  });

  it("propagates style-hint edits without touching the other fields", async () => {
    const { changes } = renderPanel({
      initial: baseConfig({ render_mode: "manim_image", quality: "high" }),
    });
    await flushCatalog();

    fireEvent.change(styleHintInput(), { target: { value: "dark theme" } });
    expect(changes).toEqual([
      { render_mode: "manim_image", quality: "high", style_hint: "dark theme" },
    ]);
    expect(renderModeSelect()).toHaveValue("manim_image");
  });

  it("resets the render mode to auto when disabling the selected visualizer", async () => {
    fixture.listVisualizers.mockResolvedValue([
      catalogItem({ id: "geogebra", display_name: "GeoGebra" }),
    ]);
    const { changes } = renderPanel({
      initial: baseConfig({ render_mode: "geogebra" }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Disable selected" }),
    );

    expect(fixture.setVisualizerEnabled).toHaveBeenCalledWith("geogebra", false);
    expect(changes).toEqual([expect.objectContaining({ render_mode: "auto" })]);
    await flushCatalog();
    expect(renderModeSelect()).toHaveValue("auto");
  });

  it("installs a bundled visualizer and refreshes the catalog", async () => {
    fixture.listVisualizers.mockResolvedValue([
      catalogItem({
        id: "wordcloud",
        display_name: "Word cloud",
        installed: false,
        enabled: false,
      }),
    ]);
    const { changes } = renderPanel();
    fireEvent.click(
      await screen.findByText("+ Word cloud", { selector: "button" }),
    );

    expect(fixture.installBundledVisualizer).toHaveBeenCalledWith("wordcloud");
    await flushCatalog();
    // Mount-time load plus the post-mutation refresh.
    expect(fixture.listVisualizers).toHaveBeenCalledTimes(2);
    expect(changes).toHaveLength(0);
  });
});

describe("VisualizeConfigPanel catalog fallbacks", () => {
  it("surfaces catalog load failures inline", async () => {
    fixture.listVisualizers.mockRejectedValue(new Error("catalog offline"));
    renderPanel();

    expect(await screen.findByText("catalog offline")).toBeInTheDocument();
  });
});

describe("VisualizeConfigPanel collapsible section", () => {
  it("hides the body when collapsed and reports the one-line summary", async () => {
    const { onToggleCollapsed } = renderPanel({
      initial: baseConfig({ render_mode: "svg" }),
      collapsed: true,
    });
    await flushCatalog();

    expect(
      screen.queryByRole("combobox", { name: "Render Mode" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/— SVG$/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);
  });

  it("summarizes manim modes with their quality tier", async () => {
    renderPanel({
      initial: baseConfig({ render_mode: "manim_video", quality: "high" }),
      collapsed: true,
    });
    await flushCatalog();

    expect(screen.getByText(/— Animation · High$/)).toBeInTheDocument();
  });
});
