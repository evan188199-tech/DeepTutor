import React, { useEffect } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WatchingSurface } from "@/components/watching/WatchingWorkspace";

vi.mock("next/navigation", () => ({
  // A ?video= deep link opens the surface straight on the mounted learning
  // layout instead of the video browser.
  useSearchParams: () =>
    new URLSearchParams({ video: "https://youtu.be/learning-layout" }),
  useParams: () => ({}),
}));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("@/context/WatchingContext", () => ({
  useWatching: () => ({ material: null }),
}));
vi.mock("@/components/watching/WatchingBrowser", () => ({
  WatchingBrowser: () => <div>Browser</div>,
}));

let paneMounts = 0;
vi.mock("@/components/watching/WatchingPane", async () => {
  const { useEffect: usePaneEffect } = await import("react");
  return {
    WatchingPane: () => {
      usePaneEffect(() => {
        paneMounts += 1;
      }, []);
      return <div data-testid="watching-pane" />;
    },
    WATCHING_ASK_EVENT: "dt:watching-ask",
  };
});

let chatMounts = 0;
function ChatRuntime() {
  useEffect(() => {
    chatMounts += 1;
  }, []);
  return <div data-testid="chat-runtime">chat runtime</div>;
}

function renderWorkspace() {
  return render(
    <div data-testid="workspace-root" data-watching-workspace="true">
      <WatchingSurface />
      <div className="chat-preview-shell" data-watching-open="true">
        <ChatRuntime />
      </div>
    </div>,
  );
}

const workspaceRoot = () => screen.getByTestId("workspace-root");

describe("Watching learning layout", () => {
  beforeEach(() => {
    paneMounts = 0;
    chatMounts = 0;
    window.localStorage.clear();
  });

  afterEach(() => {
    Object.defineProperty(document, "fullscreenElement", {
      value: undefined,
      configurable: true,
    });
    Object.defineProperty(document, "fullscreenEnabled", {
      value: undefined,
      configurable: true,
    });
  });

  it("switches layouts without remounting the player pane or the chat runtime", () => {
    renderWorkspace();
    const root = workspaceRoot();
    expect(paneMounts).toBe(1);
    expect(chatMounts).toBe(1);

    const learningToggle = screen.getByRole("button", {
      name: "Learning layout",
    });
    fireEvent.click(learningToggle);
    expect(root.dataset.watchingLearning).toBe("true");
    expect(root.style.getPropertyValue("--watching-split")).toBe("60%");

    const separator = screen.getByRole("separator");
    expect(separator).toHaveAttribute("aria-valuenow", "60");
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(separator).toHaveAttribute("aria-valuenow", "62");
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(separator).toHaveAttribute("aria-valuenow", "60");

    fireEvent.click(learningToggle);
    expect(root.dataset.watchingLearning).toBeUndefined();
    expect(root.style.getPropertyValue("--watching-split")).toBe("");

    expect(paneMounts).toBe(1);
    expect(chatMounts).toBe(1);
  });

  it("drags the split within bounds and persists the learning layout", async () => {
    const view = renderWorkspace();
    const root = workspaceRoot();
    vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
      left: 0,
      width: 1000,
    } as DOMRect);

    fireEvent.click(screen.getByRole("button", { name: "Learning layout" }));
    const separator = screen.getByRole("separator");
    fireEvent.pointerDown(separator, {
      button: 0,
      pointerId: 1,
      clientX: 500,
    });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 700 });
    expect(root.style.getPropertyValue("--watching-split")).toBe("70%");
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 2000 });
    expect(root.style.getPropertyValue("--watching-split")).toBe("75%");
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: -500 });
    expect(root.style.getPropertyValue("--watching-split")).toBe("35%");
    fireEvent.pointerUp(separator, { pointerId: 1, clientX: 350 });

    expect(
      JSON.parse(
        window.localStorage.getItem("dt:watching-learning-layout") || "{}",
      ),
    ).toEqual({ learning: true, split: 35 });

    view.unmount();
    paneMounts = 0;
    chatMounts = 0;
    renderWorkspace();
    const restored = workspaceRoot();
    await waitFor(() => {
      expect(restored.dataset.watchingLearning).toBe("true");
      expect(restored.style.getPropertyValue("--watching-split")).toBe("35%");
    });
    expect(paneMounts).toBe(1);
    expect(chatMounts).toBe(1);
  });

  it("requests the browser Fullscreen API and syncs back on exit", async () => {
    Object.defineProperty(document, "fullscreenEnabled", {
      value: true,
      configurable: true,
    });
    renderWorkspace();
    const root = workspaceRoot();
    const request = vi.fn().mockResolvedValue(undefined);
    root.requestFullscreen =
      request as unknown as typeof root.requestFullscreen;

    fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
    await waitFor(() => expect(request).toHaveBeenCalled());

    Object.defineProperty(document, "fullscreenElement", {
      value: root,
      configurable: true,
    });
    fireEvent(document, new Event("fullscreenchange"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Exit fullscreen" }),
      ).toBeTruthy(),
    );
    expect(root.dataset.watchingFullscreenFallback).toBeUndefined();

    const exit = vi.fn().mockResolvedValue(undefined);
    document.exitFullscreen =
      exit as unknown as typeof document.exitFullscreen;
    fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" }));
    await waitFor(() => expect(exit).toHaveBeenCalled());

    Object.defineProperty(document, "fullscreenElement", {
      value: undefined,
      configurable: true,
    });
    fireEvent(document, new Event("fullscreenchange"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Enter fullscreen" }),
      ).toBeTruthy(),
    );
    expect(paneMounts).toBe(1);
    expect(chatMounts).toBe(1);
  });

  it("falls back to a fixed learning viewport when the Fullscreen API is unavailable", () => {
    renderWorkspace();
    const root = workspaceRoot();
    expect(root.requestFullscreen).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
    expect(root.dataset.watchingFullscreenFallback).toBe("true");
    expect(
      screen.getByRole("button", { name: "Exit fullscreen" }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" }));
    expect(root.dataset.watchingFullscreenFallback).toBeUndefined();
    expect(
      screen.getByRole("button", { name: "Enter fullscreen" }),
    ).toBeTruthy();
    expect(paneMounts).toBe(1);
    expect(chatMounts).toBe(1);
  });

  it("stays usable outside a watching workspace without crashing", () => {
    render(<WatchingSurface />);
    fireEvent.click(screen.getByRole("button", { name: "Learning layout" }));
    fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
    expect(
      screen.getByRole("button", { name: "Enter fullscreen" }),
    ).toBeTruthy();
    expect(screen.getByTestId("watching-pane")).toBeTruthy();
    expect(paneMounts).toBe(1);
  });
});
