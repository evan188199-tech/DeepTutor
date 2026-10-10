import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WatchingMarksPanel } from "@/components/watching/WatchingMarksPanel";
import type {
  VideoLearningMark,
  VideoMarkSuggestion,
} from "@/lib/video-learning-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function makeMark(overrides: Partial<VideoLearningMark> = {}): VideoLearningMark {
  return {
    mark_id: "mark-1",
    kind: "key_point",
    start_seconds: 10,
    end_seconds: 40,
    start_locator: 1,
    end_locator: 4,
    quote: "anchor sentence",
    note: "",
    author: "user",
    created_at: "2026-10-10T00:00:00Z",
    updated_at: "2026-10-10T00:00:00Z",
    ...overrides,
  };
}

function makeSuggestion(
  overrides: Partial<VideoMarkSuggestion> = {},
): VideoMarkSuggestion {
  return {
    kind: "question",
    start_seconds: 15,
    end_seconds: 45,
    start_locator: 2,
    end_locator: 5,
    quote: "suggested quote",
    note: "",
    author: "assistant",
    ...overrides,
  };
}

function renderPanel(
  overrides: Partial<Parameters<typeof WatchingMarksPanel>[0]> = {},
) {
  const props = {
    marks: [] as VideoLearningMark[],
    suggestions: [] as VideoMarkSuggestion[],
    onSeek: vi.fn(),
    onDelete: vi.fn(),
    onReview: vi.fn(),
    onSaveSuggestion: vi.fn(),
    ...overrides,
  };
  const view = render(<WatchingMarksPanel {...props} />);
  return { ...view, props };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WatchingMarksPanel", () => {
  it("renders marks ordered by start time with labels, quotes and notes", () => {
    const { container } = renderPanel({
      marks: [
        makeMark({
          mark_id: "mark-review",
          kind: "review",
          start_seconds: 60,
          end_seconds: 90,
          quote: "revisit this part",
          note: "revisit chapter",
        }),
        makeMark({
          mark_id: "mark-first",
          kind: "key_point",
          start_seconds: 10,
          end_seconds: 40,
          quote: "anchor sentence",
        }),
        makeMark({
          mark_id: "mark-question",
          kind: "question",
          start_seconds: 120,
          end_seconds: 126,
          quote: "why does this hold?",
        }),
      ],
    });

    const order = Array.from(
      container.querySelectorAll("article[data-testid]"),
    ).map((node) => node.getAttribute("data-testid"));
    expect(order).toEqual([
      "watching-mark-key_point",
      "watching-mark-review",
      "watching-mark-question",
    ]);
    expect(
      within(
        container.querySelector('[data-testid="watching-mark-key_point"]')!,
      ).getByText("Key point"),
    ).toBeInTheDocument();
    expect(
      within(
        container.querySelector('[data-testid="watching-mark-review"]')!,
      ).getByText("Review later"),
    ).toBeInTheDocument();
    expect(
      within(
        container.querySelector('[data-testid="watching-mark-question"]')!,
      ).getByText("Question"),
    ).toBeInTheDocument();
    expect(screen.getByText("anchor sentence")).toBeInTheDocument();
    expect(screen.getByText("why does this hold?")).toBeInTheDocument();
    expect(screen.getByText("revisit chapter")).toBeInTheDocument();
  });

  it("shows the empty state when there are no marks and no suggestions", () => {
    renderPanel();
    expect(screen.getByText("No marks yet.")).toBeInTheDocument();
  });

  it("formats single-point, ranged and hour-long timestamps", () => {
    renderPanel({
      marks: [
        makeMark({ mark_id: "m-point", start_seconds: 130, end_seconds: 130 }),
        makeMark({ mark_id: "m-range", start_seconds: 31, end_seconds: 65 }),
        makeMark({ mark_id: "m-hour", start_seconds: 3605, end_seconds: 3670 }),
      ],
    });
    expect(screen.getByText("02:10")).toBeInTheDocument();
    expect(screen.getByText("00:31 - 01:05")).toBeInTheDocument();
    expect(screen.getByText("1:00:05 - 1:01:10")).toBeInTheDocument();
  });

  it("seeks to a mark start through its timestamp button", () => {
    const { props } = renderPanel({
      marks: [
        makeMark({ mark_id: "m-range", start_seconds: 31, end_seconds: 65 }),
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "00:31 - 01:05" }));
    expect(props.onSeek).toHaveBeenCalledTimes(1);
    expect(props.onSeek).toHaveBeenCalledWith(31);
  });

  it("seeks to a suggestion start and renders its quote", () => {
    const { props } = renderPanel({
      suggestions: [makeSuggestion()],
    });
    expect(screen.getByText("suggested quote")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "00:15 - 00:45" }));
    expect(props.onSeek).toHaveBeenCalledTimes(1);
    expect(props.onSeek).toHaveBeenCalledWith(15);
  });

  it("filters marks by kind and keeps the pressed state", () => {
    const { container } = renderPanel({
      marks: [
        makeMark({ mark_id: "m-kp", kind: "key_point" }),
        makeMark({ mark_id: "m-q", kind: "question" }),
        makeMark({ mark_id: "m-r", kind: "review" }),
      ],
    });

    const group = screen.getByRole("group", { name: "Filter marks" });
    const allButton = within(group).getByRole("button", { name: "All" });
    const questionButton = within(group).getByRole("button", {
      name: "Question",
    });
    expect(allButton).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(questionButton);
    expect(questionButton).toHaveAttribute("aria-pressed", "true");
    expect(allButton).toHaveAttribute("aria-pressed", "false");
    expect(
      container.querySelector('[data-testid="watching-mark-question"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-testid="watching-mark-key_point"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="watching-mark-review"]'),
    ).toBeNull();

    fireEvent.click(allButton);
    expect(
      container.querySelector('[data-testid="watching-mark-key_point"]'),
    ).not.toBeNull();
  });

  it("deletes a mark through the delete callback", () => {
    const { props } = renderPanel({
      marks: [
        makeMark({ mark_id: "m-a" }),
        makeMark({ mark_id: "m-b", start_seconds: 200, end_seconds: 260 }),
      ],
    });
    const deleteButtons = screen.getAllByRole("button", {
      name: "Delete mark",
    });
    expect(deleteButtons).toHaveLength(2);
    fireEvent.click(deleteButtons[0]);
    expect(props.onDelete).toHaveBeenCalledTimes(1);
    expect(props.onDelete).toHaveBeenCalledWith("m-a");
  });

  it("disables mark actions while busy", () => {
    const { props } = renderPanel({
      marks: [makeMark({ mark_id: "m-a" })],
      suggestions: [makeSuggestion()],
      busy: true,
      onDismissSuggestion: vi.fn(),
    });
    const deleteButton = screen.getByRole("button", { name: "Delete mark" });
    expect(deleteButton).toBeDisabled();
    fireEvent.click(deleteButton);
    expect(props.onDelete).not.toHaveBeenCalled();

    const suggestionArticle = screen
      .getAllByRole("article")
      .find((article) => within(article).queryByText("suggested quote"));
    expect(suggestionArticle).toBeDefined();
    const articleButtons = within(suggestionArticle!).getAllByRole("button");
    expect(
      articleButtons.filter((button) => button.hasAttribute("disabled")),
    ).toHaveLength(2);
    expect(
      within(suggestionArticle!).queryByRole("button", { name: "Save" }),
    ).toBeNull();
  });

  it("saves a suggestion and hides dismiss without a handler", () => {
    const suggestion = makeSuggestion();
    const { props } = renderPanel({ suggestions: [suggestion] });
    expect(
      screen.queryByRole("button", { name: "Dismiss suggestion" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSaveSuggestion).toHaveBeenCalledTimes(1);
    expect(props.onSaveSuggestion).toHaveBeenCalledWith(suggestion);
  });

  it("dismisses a suggestion when a dismiss handler is provided", () => {
    const suggestion = makeSuggestion();
    const onDismissSuggestion = vi.fn();
    renderPanel({ suggestions: [suggestion], onDismissSuggestion });
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss suggestion" }),
    );
    expect(onDismissSuggestion).toHaveBeenCalledTimes(1);
    expect(onDismissSuggestion).toHaveBeenCalledWith(suggestion);
  });

  it("offers review only for unreviewed review marks and shows reviewed state", () => {
    const pending = makeMark({
      mark_id: "m-review",
      kind: "review",
      start_seconds: 60,
      end_seconds: 90,
    });
    const reviewed = makeMark({
      mark_id: "m-review-done",
      kind: "review",
      start_seconds: 300,
      end_seconds: 330,
      reviewed_at: "2026-10-10T01:00:00Z",
    });
    const { props } = renderPanel({
      marks: [pending, reviewed],
    });

    const reviewButton = screen.getByRole("button", {
      name: "Mark as reviewed",
    });
    fireEvent.click(reviewButton);
    expect(props.onReview).toHaveBeenCalledTimes(1);
    expect(props.onReview).toHaveBeenCalledWith(pending);

    expect(screen.getByText("Reviewed")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Mark as reviewed" }),
    ).toHaveLength(1);
  });

  it("highlights the mark covering the current playback time", () => {
    const { container } = renderPanel({
      marks: [
        makeMark({ mark_id: "m-inside", start_seconds: 10, end_seconds: 40 }),
        makeMark({
          mark_id: "m-outside",
          kind: "question",
          start_seconds: 200,
          end_seconds: 260,
        }),
      ],
      currentTime: 20,
    });

    const active = Array.from(
      container.querySelectorAll("article[data-testid]"),
    ).filter((node) => node.className.includes("border-blue-500/40"));
    expect(active).toHaveLength(1);
    expect(active[0].getAttribute("data-testid")).toBe(
      "watching-mark-key_point",
    );
    expect(
      container.querySelector('[data-testid="watching-mark-question"]'),
    ).not.toBeNull();
  });

  it("surfaces the error banner with an alert role", () => {
    renderPanel({ error: "Save failed" });
    expect(screen.getByRole("alert")).toHaveTextContent("Save failed");
  });
});
