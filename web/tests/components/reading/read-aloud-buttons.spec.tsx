import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  PageToolButtons,
  ReadAloudButton,
} from "@/components/reading/workspace/ReadAloudButton";
import {
  ReadingActionsContext,
  type ReadingActionEntry,
  type ReadingActionsValue,
} from "@/components/reading/reading-actions-context";
import type { ReadingExtensionManifest } from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function makeEntry(
  key: string,
  overrides: Partial<ReadingActionEntry> = {},
): ReadingActionEntry {
  const manifest = {
    id: `ext-${key}`,
    actions: [{ id: "run" }],
  } as unknown as ReadingExtensionManifest;
  return {
    key,
    extension: manifest,
    action: manifest.actions[0],
    label: `label-${key}`,
    needsSelection: false,
    ...overrides,
  };
}

function makeValue(overrides: Partial<ReadingActionsValue> = {}) {
  const run = vi.fn().mockResolvedValue(undefined);
  const stopSpeaking = vi.fn();
  const value: ReadingActionsValue = {
    ageMode: "default",
    actions: [makeEntry("read_aloud:read")],
    cards: [],
    speaking: false,
    busyKey: "",
    run,
    stopSpeaking,
    dismiss: vi.fn(),
    ...overrides,
  };
  return { run, stopSpeaking, value };
}

function renderWith(
  ui: React.ReactElement,
  value: ReadingActionsValue | null,
) {
  return value === null
    ? render(ui)
    : render(
        <ReadingActionsContext.Provider value={value}>
          {ui}
        </ReadingActionsContext.Provider>,
      );
}

describe("ReadAloudButton", () => {
  it("renders nothing outside a reading workspace", () => {
    const { container } = renderWith(<ReadAloudButton />, null);
    expect(container).toBeEmptyDOMElement();
  });

  it("steps aside for young-learner mode", () => {
    const { value } = makeValue({ ageMode: "young" });
    const { container } = renderWith(<ReadAloudButton />, value);
    expect(container).toBeEmptyDOMElement();
  });

  it("starts reading via the shared run action", () => {
    const { run, value } = makeValue();
    renderWith(<ReadAloudButton />, value);

    const button = screen.getByRole("button", {
      name: "Read this page aloud",
    });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toBeEnabled();

    fireEvent.click(button);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run.mock.calls[0][0].key).toBe("read_aloud:read");
    expect(value.stopSpeaking).not.toHaveBeenCalled();
  });

  it("stops reading while speaking", () => {
    const { run, stopSpeaking, value } = makeValue({ speaking: true });
    renderWith(<ReadAloudButton />, value);

    const button = screen.getByRole("button", { name: "Stop reading aloud" });
    expect(button).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(button);
    expect(stopSpeaking).toHaveBeenCalledTimes(1);
    expect(run).not.toHaveBeenCalled();
  });

  it("disables the toggle while the read action is busy", () => {
    const { value } = makeValue({ busyKey: "read_aloud:read" });
    renderWith(<ReadAloudButton />, value);
    expect(
      screen.getByRole("button", { name: "Read this page aloud" }),
    ).toBeDisabled();
  });

  it("honors the disabled prop", () => {
    const { value } = makeValue();
    renderWith(<ReadAloudButton disabled />, value);
    expect(
      screen.getByRole("button", { name: "Read this page aloud" }),
    ).toBeDisabled();
  });
});

describe("PageToolButtons", () => {
  it("renders nothing outside a reading workspace", () => {
    const { container } = renderWith(
      <PageToolButtons onQuiz={() => {}} />,
      null,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing in young-learner mode", () => {
    const { value } = makeValue({ ageMode: "early" });
    const { container } = renderWith(
      <PageToolButtons onQuiz={() => {}} />,
      value,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("fires the quiz callback from the page tool", () => {
    const onQuiz = vi.fn();
    const { value } = makeValue();
    renderWith(<PageToolButtons onQuiz={onQuiz} />, value);

    fireEvent.click(
      screen.getByRole("button", { name: "Quiz me on this page" }),
    );
    expect(onQuiz).toHaveBeenCalledTimes(1);
  });

  it("exposes selection-free extensions but hides read-aloud and selection tools", () => {
    const { value } = makeValue({
      actions: [
        makeEntry("read_aloud:read"),
        makeEntry("translate", { needsSelection: true }),
        makeEntry("summarize", { label: "label-summarize" }),
      ],
    });
    renderWith(<PageToolButtons onQuiz={() => {}} />, value);

    expect(
      screen.queryByRole("button", { name: "Read this page aloud" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "label-translate" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "label-summarize" }),
    ).toBeInTheDocument();
  });

  it("disables every page tool while disabled", () => {
    const { value } = makeValue({
      actions: [makeEntry("summarize")],
    });
    renderWith(<PageToolButtons disabled onQuiz={() => {}} />, value);
    expect(
      screen.getByRole("button", { name: "label-summarize" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Quiz me on this page" }),
    ).toBeDisabled();
  });

  it("disables a running extension and keeps others usable", () => {
    const { run, value } = makeValue({
      actions: [
        makeEntry("summarize", { label: "label-summarize" }),
        makeEntry("outline", { label: "label-outline" }),
      ],
      busyKey: "summarize",
    });
    renderWith(<PageToolButtons onQuiz={() => {}} />, value);

    expect(
      screen.getByRole("button", { name: "label-summarize" }),
    ).toBeDisabled();
    const outline = screen.getByRole("button", { name: "label-outline" });
    expect(outline).toBeEnabled();

    fireEvent.click(outline);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run.mock.calls[0][0].key).toBe("outline");
  });
});
