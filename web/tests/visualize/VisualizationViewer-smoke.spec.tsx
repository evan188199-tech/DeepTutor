import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VisualizationViewer from "@/components/visualize/VisualizationViewer";
import type {
  VisualizeCanvasResult,
  VisualizeResult,
} from "@/lib/visualize-types";

const fixture = vi.hoisted(() => ({
  t: (key: string, opts?: Record<string, unknown>) =>
    opts
      ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
          String(opts[name] ?? ""),
        )
      : key,
  chartConfigs: [] as Array<Record<string, unknown>>,
  destroyedCharts: 0,
  failChartConstructor: false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/components/Mermaid", () => ({
  Mermaid: (props: { chart: string }) =>
    React.createElement(
      "div",
      { "data-testid": "mermaid-stub" },
      props.chart,
    ),
}));

// The constructor throws a non-Error value on demand so the viewer's
// non-Error fallback branch ("Failed to render chart") stays reachable.
vi.mock("chart.js/auto", () => ({
  default: class MockChart {
    constructor(_el: unknown, config: Record<string, unknown>) {
      if (fixture.failChartConstructor) {
        // A non-Error throw keeps the viewer's generic fallback branch live.
        throw "chart engine exploded";
      }
      fixture.chartConfigs.push(config);
    }
    destroy() {
      fixture.destroyedCharts += 1;
    }
  },
}));

vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (
      loader: () => Promise<{ default: React.ComponentType<unknown> }>,
    ) => {
      const Loaded = React.lazy(loader);
      const DynamicComponent = (props: Record<string, unknown>) =>
        React.createElement(
          React.Suspense,
          { fallback: null },
          React.createElement(Loaded, props),
        );
      return DynamicComponent;
    },
  };
});

vi.mock("@/components/math-animator/MathAnimatorViewer", async () => {
  const React = await import("react");
  return {
    default: () =>
      React.createElement("div", { "data-testid": "math-animator-stub" }),
  };
});

vi.mock("@/components/Geogebra", async () => {
  const React = await import("react");
  return {
    default: (props: { title?: string }) =>
      React.createElement("div", { "data-testid": "geogebra-stub" }, props.title ?? ""),
  };
});

function canvasResult(
  overrides: Partial<VisualizeCanvasResult> = {},
): VisualizeCanvasResult {
  return {
    schema_version: "deeptutor.visualization/v1",
    response: "",
    render_type: "mermaid",
    renderer: {
      id: "mermaid",
      version: "1.0.0",
      target: "native",
      native_renderer: "mermaid",
      entry_url: "",
    },
    payload: { format: "text/plain", data: "graph TD;A-->B" },
    presentation: {
      title: "Flow",
      description: "",
      alt_text: "",
      aspect_ratio: "",
    },
    interaction: { events: [] },
    fallback: {},
    code: { language: "mermaid", content: "graph TD;A-->B" },
    analysis: {
      render_type: "mermaid",
      description: "",
      data_description: "",
      chart_type: "flowchart",
      visual_elements: [],
      rationale: "",
    },
    review: { optimized_code: "", changed: false, review_notes: "" },
    ...overrides,
  };
}

function chartjsResult(config: string): VisualizeResult {
  return canvasResult({
    render_type: "chartjs",
    renderer: {
      id: "chartjs",
      version: "1.0.0",
      target: "native",
      native_renderer: "chartjs",
      entry_url: "",
    },
    analysis: {
      render_type: "chartjs",
      description: "",
      data_description: "",
      chart_type: "bar",
      visual_elements: [],
      rationale: "",
    },
    code: { language: "json", content: config },
  });
}

beforeEach(() => {
  fixture.chartConfigs.length = 0;
  fixture.destroyedCharts = 0;
  fixture.failChartConstructor = false;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("VisualizationViewer smoke coverage", () => {
  it("destroys the previous chartjs instance when the config changes", async () => {
    const view = render(<VisualizationViewer result={chartjsResult('{"type":"bar"}')} />);
    await waitFor(() => expect(fixture.chartConfigs).toHaveLength(1));

    view.rerender(
      <VisualizationViewer result={chartjsResult('{"type":"line"}')} />,
    );
    await waitFor(() => expect(fixture.chartConfigs).toHaveLength(2));

    expect(fixture.destroyedCharts).toBe(1);
    expect(fixture.chartConfigs[0]).toEqual({ type: "bar" });
    expect(fixture.chartConfigs[1]).toEqual({ type: "line" });
  });

  it("shows the generic chart error card when the chart engine throws a non-Error", async () => {
    fixture.failChartConstructor = true;

    render(<VisualizationViewer result={chartjsResult('{"type":"bar"}')} />);

    expect(await screen.findByText("Chart rendering error")).toBeInTheDocument();
    expect(screen.getByText("Failed to render chart")).toBeInTheDocument();
    expect(fixture.chartConfigs).toHaveLength(0);
  });

  it("leaves the copy button intact when the clipboard write rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    try {
      render(<VisualizationViewer result={canvasResult()} />);
      fireEvent.click(screen.getByRole("button", { name: "Copy code" }));

      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(screen.queryByText("Copied")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("closes the fullscreen overlay through its close button", () => {
    render(<VisualizationViewer result={canvasResult()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(
      screen.queryByRole("button", { name: "Close" }),
    ).not.toBeInTheDocument();
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("posts the render payload into the plugin iframe on load", () => {
    render(
      <VisualizationViewer
        result={canvasResult({
          render_type: "desmos",
          renderer: {
            id: "desmos-plugin",
            version: "1.0.0",
            target: "iframe",
            native_renderer: "",
            entry_url: "https://plugins.example/render",
          },
          presentation: {
            title: "Sorting demo",
            description: "",
            alt_text: "",
            aspect_ratio: "",
          },
        })}
      />,
    );
    const iframe = screen.getByTitle("Sorting demo") as HTMLIFrameElement;
    const postMessage = vi.spyOn(
      iframe.contentWindow as Window,
      "postMessage",
    );

    fireEvent.load(iframe);

    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "deeptutor:visualization:render",
        schema_version: "deeptutor.visualization/v1",
        renderer: expect.objectContaining({ id: "desmos-plugin" }),
      }),
      "*",
    );
  });

  it("keeps review notes hidden until the review actually changed the output", () => {
    const view = render(<VisualizationViewer result={canvasResult()} />);
    expect(screen.queryByText(/^Review:/)).not.toBeInTheDocument();

    view.rerender(
      <VisualizationViewer
        result={canvasResult({
          review: {
            optimized_code: "",
            changed: true,
            review_notes: "labels rotated",
          },
        })}
      />,
    );
    expect(screen.getByText("Review: labels rotated")).toBeInTheDocument();
  });

  it("renders the html renderer for empty content without crashing", () => {
    render(
      <VisualizationViewer
        result={canvasResult({
          render_type: "html",
          renderer: {
            id: "html",
            version: "1.0.0",
            target: "native",
            native_renderer: "html",
            entry_url: "",
          },
          code: { language: "html", content: "" },
        })}
      />,
    );
    const iframe = screen.getByTitle("HTML visualization") as HTMLIFrameElement;
    expect(iframe).toBeInTheDocument();
    expect(iframe.getAttribute("srcdoc")?.length ?? 0).toBeGreaterThan(0);
    expect(
      screen.queryByText("Chart rendering error"),
    ).not.toBeInTheDocument();
  });
});
