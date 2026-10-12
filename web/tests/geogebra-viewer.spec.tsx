import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Geogebra from "@/components/Geogebra";

const GGB_SCRIPT_SRC = "https://www.geogebra.org/apps/deployggb.js";

const fixture = vi.hoisted(() => ({
  t: (key: string, opts?: Record<string, unknown>) =>
    opts
      ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
          String(opts[name] ?? ""),
        )
      : key,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

type MockApi = {
  evalCommand: ReturnType<typeof vi.fn>;
  setCoordSystem: ReturnType<typeof vi.fn>;
};

class MockGGBApplet {
  static instances: MockGGBApplet[] = [];

  config: Record<string, unknown>;

  inject: (containerId: string) => void;

  constructor(config: Record<string, unknown>) {
    this.config = config;
    this.inject = vi.fn();
    MockGGBApplet.instances.push(this);
  }
}

function makeApi(overrides: Partial<MockApi> = {}): MockApi {
  return {
    evalCommand: vi.fn(() => true),
    setCoordSystem: vi.fn(),
    ...overrides,
  };
}

function runAppletOnLoad(instance: MockGGBApplet, api: MockApi): Promise<void> {
  return act(async () => {
    (instance.config.appletOnLoad as (api: MockApi) => void)(api);
  });
}

function findScript(): HTMLScriptElement | null {
  return document.querySelector<HTMLScriptElement>(
    `script[src="${GGB_SCRIPT_SRC}"]`,
  );
}

function setWindowGgbApplet(value: unknown): void {
  (window as unknown as { GGBApplet?: unknown }).GGBApplet = value;
}

function deleteWindowGgbApplet(): void {
  delete (window as unknown as { GGBApplet?: unknown }).GGBApplet;
}

async function loadSubject(): Promise<typeof Geogebra> {
  vi.resetModules();
  const mod = await import("@/components/Geogebra");
  return mod.default;
}

beforeEach(() => {
  deleteWindowGgbApplet();
  MockGGBApplet.instances.length = 0;
  document
    .querySelectorAll<HTMLScriptElement>(`script[src="${GGB_SCRIPT_SRC}"]`)
    .forEach((node) => node.remove());
});

afterEach(() => {
  deleteWindowGgbApplet();
});

it("shows the loading placeholder before the embed script resolves", async () => {
  const GeogebraComponent = await loadSubject();
  render(<GeogebraComponent script="A=(1,2)" />);

  expect(screen.getByText("Loading GeoGebra...")).toBeInTheDocument();
  expect(findScript()).not.toBeNull();
  expect(MockGGBApplet.instances).toHaveLength(0);
});

it("mounts the applet into its container and hides the loading state", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(<GeogebraComponent script="A=(1,2)" />);

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  const instance = MockGGBApplet.instances[0];
  const containerId = document.querySelector(".ggb-applet-container")!.id;
  expect(containerId).toMatch(/^ggb-/);
  await runAppletOnLoad(instance, api);

  expect(instance.inject).toHaveBeenCalledWith(containerId);
  expect(api.setCoordSystem).not.toHaveBeenCalled();
  expect(screen.queryByText("Loading GeoGebra...")).not.toBeInTheDocument();
});

it("evaluates payload commands and filters blank entries", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(
    <GeogebraComponent payload={{ commands: ["A=(1,2)", "   ", "B=(3,4)"] }} />,
  );

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.evalCommand.mock.calls.map((call) => call[0])).toEqual([
    "A=(1,2)",
    "B=(3,4)",
  ]);
});

it("strips comments and blank lines from the raw script", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(
    <GeogebraComponent script={"# a comment\n\nA=(1,2)\n   \nB=(3,4)\n"} />,
  );

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.evalCommand.mock.calls.map((call) => call[0])).toEqual([
    "A=(1,2)",
    "B=(3,4)",
  ]);
});

it("prefers payload commands over the raw script", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(
    <GeogebraComponent
      script={"# ignored\nS=(9,9)"}
      payload={{ commands: ["P=(1,1)"] }}
    />,
  );

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.evalCommand).toHaveBeenCalledTimes(1);
  expect(api.evalCommand).toHaveBeenCalledWith("P=(1,1)");
  expect(api.evalCommand).not.toHaveBeenCalledWith("S=(9,9)");
});

it("applies the payload view bounds via setCoordSystem", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(
    <GeogebraComponent
      script="A=(1,2)"
      payload={{
        commands: ["A=(1,2)"],
        view: { x_min: -5, x_max: 5, y_min: -2, y_max: 8 },
      }}
    />,
  );

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.setCoordSystem).toHaveBeenCalledWith(-5, 5, -2, 8);
});

it("renders the provided title above the applet", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(<GeogebraComponent script="A=(1,2)" title="Triangle demo" />);

  expect(screen.getByText("Triangle demo")).toBeInTheDocument();

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);
  expect(screen.getByText("Triangle demo")).toBeInTheDocument();
});

it("mounts an empty applet without evaluating any command", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  render(<GeogebraComponent />);

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.evalCommand).not.toHaveBeenCalled();
  expect(MockGGBApplet.instances[0].inject).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText("Loading GeoGebra...")).not.toBeInTheDocument();
});

it("lists commands rejected by evalCommand in an alert", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi({
    evalCommand: vi.fn((cmd: string) => cmd !== "A=(9,9)"),
  });
  render(<GeogebraComponent script={"A=(1,2)\nA=(9,9)\nB=(3,4)"} />);

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(api.evalCommand).toHaveBeenCalledTimes(3);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByText(/GeoGebra rejected 1 command/)).toBeInTheDocument();
  expect(screen.getByText("A=(9,9)")).toBeInTheDocument();
  expect(screen.queryByText("Loading GeoGebra...")).not.toBeInTheDocument();
});

it("lists commands that threw during evaluation", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi({
    evalCommand: vi.fn((cmd: string) => {
      if (cmd === "B=(boom)") throw new Error("syntax error");
      return true;
    }),
  });
  render(<GeogebraComponent script={"A=(1,2)\nB=(boom)"} />);

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);

  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByText(/GeoGebra rejected 1 command/)).toBeInTheDocument();
  expect(screen.getByText("B=(boom)")).toBeInTheDocument();
});

it("shows an error when the embed script fails to load", async () => {
  const GeogebraComponent = await loadSubject();
  render(<GeogebraComponent script="A=(1,2)" />);

  const script = findScript();
  expect(script).not.toBeNull();
  await act(async () => {
    script!.onerror?.(new Event("error"));
  });

  expect(screen.getByText(/Failed to load GeoGebra/)).toBeInTheDocument();
  expect(
    screen.getByText(/GeoGebra script failed to load/),
  ).toBeInTheDocument();
  expect(screen.queryByText("Loading GeoGebra...")).not.toBeInTheDocument();
});

it("shows an error when the script loads but GGBApplet is missing", async () => {
  const GeogebraComponent = await loadSubject();
  render(<GeogebraComponent script="A=(1,2)" />);

  const script = findScript();
  expect(script).not.toBeNull();
  await act(async () => {
    script!.onload?.(new Event("load"));
  });

  expect(screen.getByText(/Failed to load GeoGebra/)).toBeInTheDocument();
  expect(
    screen.getByText(/GGBApplet global missing after script load/),
  ).toBeInTheDocument();
  expect(MockGGBApplet.instances).toHaveLength(0);
});

it("shares a single embed script between multiple instances", async () => {
  const GeogebraComponent = await loadSubject();
  render(
    <>
      <GeogebraComponent script="A=(1,2)" />
      <GeogebraComponent script="B=(3,4)" />
    </>,
  );

  expect(
    document.querySelectorAll(`script[src="${GGB_SCRIPT_SRC}"]`),
  ).toHaveLength(1);

  setWindowGgbApplet(MockGGBApplet);
  const script = findScript();
  await act(async () => {
    script!.onload?.(new Event("load"));
  });

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(2));
  for (const instance of MockGGBApplet.instances) {
    await runAppletOnLoad(instance, makeApi());
  }
  expect(screen.queryByText("Loading GeoGebra...")).not.toBeInTheDocument();
  expect(
    document.querySelectorAll(`script[src="${GGB_SCRIPT_SRC}"]`),
  ).toHaveLength(1);
});

it("clears the applet container on unmount", async () => {
  const GeogebraComponent = await loadSubject();
  setWindowGgbApplet(MockGGBApplet);
  const api = makeApi();
  const { container, unmount } = render(<GeogebraComponent script="A=(1,2)" />);

  await waitFor(() => expect(MockGGBApplet.instances).toHaveLength(1));
  await runAppletOnLoad(MockGGBApplet.instances[0], api);
  const appletContainer = container.querySelector(".ggb-applet-container")!;
  appletContainer.appendChild(document.createElement("div"));
  expect(appletContainer.childElementCount).toBe(1);

  unmount();

  expect(appletContainer.childElementCount).toBe(0);
});

it("ignores script resolution after unmount", async () => {
  const GeogebraComponent = await loadSubject();
  const { unmount } = render(<GeogebraComponent script="A=(1,2)" />);

  const script = findScript();
  expect(script).not.toBeNull();
  unmount();

  setWindowGgbApplet(MockGGBApplet);
  await act(async () => {
    script!.onload?.(new Event("load"));
  });

  expect(MockGGBApplet.instances).toHaveLength(0);
  expect(
    document.querySelector(".ggb-applet-container"),
  ).not.toBeInTheDocument();
});
