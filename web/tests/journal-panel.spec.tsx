import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import JournalSection from "@/components/space/journal/JournalSection";
import {
  fetchLearningJournal,
  type LearningJournalSnapshot,
} from "@/lib/journal-api";
import { initI18n } from "@/i18n/init";

vi.mock("@/lib/journal-api", () => ({
  fetchLearningJournal: vi.fn(),
}));

initI18n("en");

const emptySnapshot: LearningJournalSnapshot = {
  version: 1,
  updated_at: "",
  mission: { topic: "", why: "", level: "", updated_at: "" },
  last_session: { summary: "", next_focus: "", updated_at: "" },
  records: [],
  is_empty: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchLearningJournal).mockResolvedValue(emptySnapshot);
});

it("renders the stored mission, last-session handoff, and records newest first", async () => {
  vi.mocked(fetchLearningJournal).mockResolvedValue({
    version: 1,
    updated_at: "2026-10-01T10:00:00Z",
    mission: {
      topic: "Linear algebra",
      why: "Prepare for graduate school",
      level: "intermediate",
      updated_at: "2026-09-30T08:00:00Z",
    },
    last_session: {
      summary: "Reviewed eigenvalues and eigenvectors",
      next_focus: "SVD applications",
      updated_at: "2026-10-01T09:00:00Z",
    },
    records: [
      { id: "rec-1", title: "Eigen intuition", insight: "Eigenvectors only get scaled", created_at: "2026-09-28T08:00:00Z" },
      { id: "rec-2", title: "Determinant", insight: "Volume scaling factor", created_at: "2026-09-29T08:00:00Z" },
    ],
    is_empty: false,
  });

  render(<JournalSection />);

  expect(await screen.findByText("Linear algebra")).toBeInTheDocument();
  expect(screen.getByText("Prepare for graduate school")).toBeInTheDocument();
  expect(screen.getByText("intermediate")).toBeInTheDocument();
  expect(screen.getByText("Reviewed eigenvalues and eigenvectors")).toBeInTheDocument();
  expect(screen.getByText("SVD applications")).toBeInTheDocument();
  const rendered = screen.getAllByText(/Eigen intuition|Determinant/);
  expect(rendered[0]).toHaveTextContent("Determinant");
  expect(rendered[1]).toHaveTextContent("Eigen intuition");
  expect(screen.queryByText(/No mission yet/i)).not.toBeInTheDocument();
});

it("shows the empty-state hint when the journal has no data", async () => {
  render(<JournalSection />);

  expect(await screen.findByText("No mission yet")).toBeInTheDocument();
  expect(
    screen.getByText(/ask it to set one in a chat/i),
  ).toBeInTheDocument();
  expect(screen.queryByText("Linear algebra")).not.toBeInTheDocument();
});

it("offers a retry when the journal cannot be loaded", async () => {
  vi.mocked(fetchLearningJournal).mockRejectedValue(new Error("boom"));
  render(<JournalSection />);

  expect(await screen.findByText(/Couldn't load the journal/i)).toBeInTheDocument();
  vi.mocked(fetchLearningJournal).mockResolvedValue(emptySnapshot);
  const retry = await waitFor(() => {
    const button = screen.queryByRole("button", { name: "Retry" });
    expect(button).toBeInTheDocument();
    return button!;
  });
  fireEvent.click(retry);
  await waitFor(() =>
    expect(screen.getByText("No mission yet")).toBeInTheDocument(),
  );
});
