import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PracticePage } from "@/components/learning/practice/PracticePage";
import { initI18n } from "@/i18n/init";
import * as api from "@/lib/practice-api";

let searchValue = "";
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchValue),
  useRouter: () => ({ replace }),
}));
vi.mock("@/components/learning/practice/PracticeSession", () => ({
  PracticeSession: ({
    ids,
    onClose,
    backLabel,
  }: {
    ids?: number[];
    onClose: () => void;
    backLabel?: string;
  }) => (
    <div data-testid="practice-session" data-ids={JSON.stringify(ids ?? [])}>
      {backLabel && <span>{backLabel}</span>}
      <button onClick={onClose}>Close session</button>
    </div>
  ),
}));
vi.mock("@/components/learning/practice/PracticeImport", () => ({
  PracticeImport: ({
    courseId,
    initialTarget,
    onClose,
    onImported,
  }: {
    courseId: string;
    initialTarget: string;
    onClose: () => void;
    onImported: (message: string) => void;
  }) => (
    <div data-testid="practice-import" data-course={courseId} data-target={initialTarget}>
      <button onClick={() => onImported("5 questions imported")}>Finish import</button>
      <button onClick={onClose}>Cancel import</button>
    </div>
  ),
}));
vi.mock("@/components/learning/practice/PracticeInsights", () => ({
  PracticeInsights: ({ courseId, revision }: { courseId: string; revision: number }) => (
    <div data-testid="practice-insights" data-course={courseId} data-revision={revision} />
  ),
}));
vi.mock("@/components/space/question-bank", () => ({
  QuestionBankSection: ({
    mistakesOnly,
    onPractice,
  }: {
    mistakesOnly: boolean;
    onPractice?: (ids: number[]) => void;
  }) => (
    <div data-testid="question-bank" data-mistakes-only={String(mistakesOnly)}>
      {onPractice && <button onClick={() => onPractice([21, 22])}>Practice this page</button>}
    </div>
  ),
}));
vi.mock("@/components/learning/LibraryWorkspace", () => ({
  WorkspaceLabel: ({ row }: { row?: { content_workspace_id?: string } }) => (
    <span data-testid="workspace-label">{row?.content_workspace_id ?? ""}</span>
  ),
  useLearningCreation: () => ({ begin: () => {}, dialog: null }),
}));
vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof api>()),
  getPracticeSummary: vi.fn(),
  getPracticeQueue: vi.fn(),
  getPracticeAnalytics: vi.fn(),
}));
initI18n("en");

const summaryBase = {
  total: 10,
  mistakes: 4,
  due: 3,
  overdue: 2,
  reviewed_today: 5,
  next_due_at: null,
  day_end: 100,
  timezone: "UTC",
};

function renderScoped(search: string) {
  searchValue = search;
  return render(<PracticePage />);
}

beforeEach(() => {
  vi.clearAllMocks();
  searchValue = "";
  vi.mocked(api.getPracticeSummary).mockResolvedValue({ ...summaryBase });
  vi.mocked(api.getPracticeQueue).mockResolvedValue([]);
});

it("renders the review home when no course or question is scoped", async () => {
  render(<PracticePage />);
  expect(
    await screen.findByText("A little recall today. Remember more tomorrow.")
  ).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Review scope" })).toBeVisible();
  expect(api.getPracticeSummary).toHaveBeenCalledWith("", "*");
});

it("loads the scoped summary and shows today's due counts on the bank tabs", async () => {
  renderScoped("course=course-a");
  expect(await screen.findByText("3 questions are ready to revisit.")).toBeInTheDocument();
  expect(screen.getByText("5 reviewed today · 2 overdue")).toBeInTheDocument();
  expect(api.getPracticeSummary).toHaveBeenCalledWith("course-a");
  expect(screen.getByRole("tab", { name: "Question Bank10" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.getByRole("tab", { name: "Mistakes4" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeEnabled();
  expect(screen.getByTestId("question-bank")).toHaveAttribute("data-mistakes-only", "false");
});

it("starts a review from the due queue and refreshes after closing the session", async () => {
  vi.mocked(api.getPracticeQueue).mockResolvedValue([
    {
      entry: { id: 11 } as api.PracticeQuestion["entry"],
      state: { version: 1, review_count: 0, is_mistake: false, due_at: 100 },
    },
    {
      entry: { id: 12 } as api.PracticeQuestion["entry"],
      state: { version: 1, review_count: 0, is_mistake: false, due_at: 200 },
    },
  ]);
  renderScoped("course=course-a");
  fireEvent.click(await screen.findByRole("button", { name: "Start today's review" }));
  const session = await screen.findByTestId("practice-session");
  expect(JSON.parse(session.getAttribute("data-ids") ?? "[]")).toEqual([11, 12]);
  expect(api.getPracticeQueue).toHaveBeenCalledWith("course-a");
  expect(screen.queryByTestId("question-bank")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close session" }));
  expect(await screen.findByTestId("question-bank")).toBeVisible();
  expect(screen.getByTestId("practice-insights")).toHaveAttribute("data-revision", "1");
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("shows the caught-up notice instead of a session when the review queue is empty", async () => {
  renderScoped("course=course-a");
  fireEvent.click(await screen.findByRole("button", { name: "Start today's review" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "You are caught up. Come back when your next reviews are due."
  );
  expect(screen.queryByTestId("practice-session")).not.toBeInTheDocument();
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("shows an error state with a working retry when the summary request fails", async () => {
  vi.mocked(api.getPracticeSummary)
    .mockRejectedValueOnce(new Error("backend offline"))
    .mockResolvedValue({ ...summaryBase });
  renderScoped("course=course-a");
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("backend offline");
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("3 questions are ready to revisit.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("opens a manual session with the ids picked from the collection", async () => {
  renderScoped("course=course-a");
  fireEvent.click(await screen.findByRole("button", { name: "Practice this page" }));
  const session = await screen.findByTestId("practice-session");
  expect(JSON.parse(session.getAttribute("data-ids") ?? "[]")).toEqual([21, 22]);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("switches bank and mistakes tabs through the router with keyboard support", async () => {
  renderScoped("course=course-a");
  await screen.findByRole("tab", { name: "Question Bank10" });
  fireEvent.click(screen.getByRole("tab", { name: "Mistakes4" }));
  expect(replace).toHaveBeenLastCalledWith("/learning/practice?course=course-a&view=mistakes", {
    scroll: false,
  });
  fireEvent.keyDown(screen.getByRole("tab", { name: "Question Bank10" }), { key: "ArrowRight" });
  expect(replace).toHaveBeenLastCalledWith("/learning/practice?course=course-a&view=mistakes", {
    scroll: false,
  });
  fireEvent.keyDown(screen.getByRole("tab", { name: "Mistakes4" }), { key: "ArrowLeft" });
  expect(replace).toHaveBeenLastCalledWith("/learning/practice?course=course-a&view=bank", {
    scroll: false,
  });
});

it("renders the mistakes view from the scoped URL", async () => {
  renderScoped("course=course-a&view=mistakes");
  expect(await screen.findByTestId("question-bank")).toHaveAttribute(
    "data-mistakes-only",
    "true"
  );
  expect(screen.getByRole("tab", { name: "Mistakes4" })).toHaveAttribute("aria-selected", "true");
});

it("renders the library shell without daily review panels in library mode", async () => {
  searchValue = "course=course-a";
  render(<PracticePage mode="library" />);
  expect(await screen.findByRole("heading", { level: 1, name: "Question Bank" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Today's review" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("practice-insights")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "All workspaces" })).not.toBeInTheDocument();
});

it("opens the import panel and surfaces the imported notice after committing", async () => {
  renderScoped("course=course-a");
  fireEvent.click(await screen.findByRole("button", { name: "Import questions" }));
  const panel = screen.getByTestId("practice-import");
  expect(panel).toHaveAttribute("data-course", "course-a");
  expect(panel).toHaveAttribute("data-target", "bank");
  fireEvent.click(screen.getByRole("button", { name: "Finish import" }));
  expect(await screen.findByRole("status")).toHaveTextContent("5 questions imported");
  expect(screen.queryByTestId("practice-import")).not.toBeInTheDocument();
  expect(screen.getByTestId("practice-insights")).toHaveAttribute("data-revision", "1");
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});
