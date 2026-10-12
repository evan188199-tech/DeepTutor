import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsTourOverlay } from "@/components/settings/SettingsTourOverlay";
import {
  TOUR_STEPS,
  type SettingsContextValue,
} from "@/features/settings/store/SettingsStore";

const fixture = vi.hoisted(() => ({
  pathname: "/settings/status",
  tourStepIndex: 0,
  advanceTour: vi.fn(),
  goBackTour: vi.fn(),
  skipTour: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => fixture.pathname,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "en" } }),
}));

function translate(key: string, options?: Record<string, unknown>) {
  if (!options) return key;
  return key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
    String(options[name]),
  );
}

vi.mock("@/features/settings/store/SettingsStore", async importOriginal => ({
  ...(await importOriginal<
    typeof import("@/features/settings/store/SettingsStore")
  >()),
  useSettings: (): Pick<
    SettingsContextValue,
    "tourStepIndex" | "advanceTour" | "goBackTour" | "skipTour"
  > => ({
    tourStepIndex: fixture.tourStepIndex,
    advanceTour: fixture.advanceTour,
    goBackTour: fixture.goBackTour,
    skipTour: fixture.skipTour,
  }),
}));

const TOTAL = TOUR_STEPS.length;
const LAST = TOUR_STEPS[TOTAL - 1];
const settle = (ms: number) =>
  new Promise(resolve => setTimeout(resolve, ms));

function mountTourTarget(target: string) {
  const el = document.createElement("div");
  el.setAttribute("data-tour", target);
  el.getBoundingClientRect = () =>
    ({ left: 40, top: 60, width: 120, height: 40 }) as DOMRect;
  document.body.appendChild(el);
  return el;
}

function renderOverlay() {
  return render(<SettingsTourOverlay />);
}

beforeEach(() => {
  fixture.pathname = "/settings/status";
  fixture.tourStepIndex = 0;
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  document
    .querySelectorAll("[data-tour]")
    .forEach(el => el.remove());
});

describe("SettingsTourOverlay – normal branches", () => {
  it("resolves the current step target and shows the step dialog", async () => {
    mountTourTarget("tour-status");
    renderOverlay();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(`Step 1 of ${TOTAL}`);
    expect(dialog).toHaveTextContent("settingsTour.status.title");
    expect(dialog).toHaveTextContent("settingsTour.status.desc");
    expect(screen.getByRole("button", { name: "Next" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
  });

  it("advances with the Next button", async () => {
    mountTourTarget("tour-status");
    renderOverlay();
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(fixture.advanceTour).toHaveBeenCalledTimes(1);
  });

  it("goes back with the Back button once past the first step", async () => {
    fixture.pathname = "/settings/appearance";
    fixture.tourStepIndex = 1;
    mountTourTarget("tour-page-heading");
    renderOverlay();
    const back = await screen.findByRole("button", { name: "Back" });
    expect(back).toBeEnabled();
    fireEvent.click(back);
    expect(fixture.goBackTour).toHaveBeenCalledTimes(1);
  });

  it("labels the final step with Got it", async () => {
    fixture.pathname = LAST.route;
    fixture.tourStepIndex = TOTAL - 1;
    mountTourTarget(LAST.target);
    renderOverlay();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(`Step ${TOTAL} of ${TOTAL}`);
    const gotIt = screen.getByRole("button", { name: "Got it" });
    fireEvent.click(gotIt);
    expect(fixture.advanceTour).toHaveBeenCalledTimes(1);
  });

  it("re-resolves the highlight when the tour moves to another route", async () => {
    mountTourTarget("tour-status");
    const view = renderOverlay();
    await screen.findByRole("dialog");
    fixture.tourStepIndex = 1;
    fixture.pathname = "/settings/appearance";
    mountTourTarget("tour-page-heading");
    await act(async () => {
      view.rerender(<SettingsTourOverlay />);
    });
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toHaveTextContent(
        "settingsTour.appearance.title",
      );
    });
    expect(screen.getByRole("dialog")).toHaveTextContent(`Step 2 of ${TOTAL}`);
  });

  it("navigates and skips with the keyboard", async () => {
    mountTourTarget("tour-status");
    renderOverlay();
    await screen.findByRole("dialog");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(fixture.advanceTour).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Enter" });
    expect(fixture.advanceTour).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(fixture.skipTour).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(fixture.goBackTour).not.toHaveBeenCalled();
  });

  it("allows ArrowLeft to go back after leaving the first step", async () => {
    fixture.pathname = "/settings/appearance";
    fixture.tourStepIndex = 1;
    mountTourTarget("tour-page-heading");
    renderOverlay();
    await screen.findByRole("dialog");
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(fixture.goBackTour).toHaveBeenCalledTimes(1);
  });
});

describe("SettingsTourOverlay – skip branches", () => {
  it("skips from both the close button and the footer link", async () => {
    mountTourTarget("tour-status");
    renderOverlay();
    await screen.findByRole("dialog");
    const skipButtons = screen.getAllByRole("button", { name: "Skip tour" });
    expect(skipButtons).toHaveLength(2);
    fireEvent.click(skipButtons[0]);
    fireEvent.click(skipButtons[1]);
    expect(fixture.skipTour).toHaveBeenCalledTimes(2);
  });
});

describe("SettingsTourOverlay – empty branches", () => {
  it("renders nothing before the tour starts", () => {
    fixture.tourStepIndex = -1;
    const { container } = renderOverlay();
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing when the step index is out of range", () => {
    fixture.tourStepIndex = TOTAL + 3;
    const { container } = renderOverlay();
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("SettingsTourOverlay – failure branches", () => {
  it("stays hidden while the step route has not loaded yet", async () => {
    fixture.tourStepIndex = 0;
    fixture.pathname = "/settings/appearance";
    mountTourTarget("tour-status");
    renderOverlay();
    await settle(250);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays hidden when the step target never appears", async () => {
    fixture.tourStepIndex = 0;
    fixture.pathname = "/settings/status";
    renderOverlay();
    await settle(800);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
