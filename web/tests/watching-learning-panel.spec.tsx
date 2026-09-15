import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WatchingProvider } from "@/context/WatchingContext";
import { WatchingSurface } from "@/components/watching/WatchingWorkspace";

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (key: string) => (key === "video" ? "video" : null), has: () => false }),
  useParams: () => ({}),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/components/watching/WatchingPane", () => ({
  WATCHING_ASK_EVENT: "dt:watching-ask",
  WatchingPane: ({ learningPanelPosition }: { learningPanelPosition: string }) => (
    <output data-testid="learning-panel-position">{learningPanelPosition}</output>
  ),
}));

describe("Watching learning panel position", () => {
  it("defaults below, persists right, and falls back below outside Focus", () => {
    localStorage.clear();
    const view = render(
      <WatchingProvider><WatchingSurface pane="focus" /></WatchingProvider>,
    );
    expect(screen.getByTestId("learning-panel-position")).toHaveTextContent("below");
    fireEvent.click(screen.getByRole("radio", { name: "Right of video" }));
    expect(screen.getByTestId("learning-panel-position")).toHaveTextContent("right");
    expect(localStorage.getItem("dt:watching:learning-panel-position")).toBe("right");
    view.rerender(
      <WatchingProvider><WatchingSurface pane="activity" /></WatchingProvider>,
    );
    expect(screen.getByTestId("learning-panel-position")).toHaveTextContent("below");
  });
});
