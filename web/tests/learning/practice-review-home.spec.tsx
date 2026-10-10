import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ReviewHome } from "@/components/learning/practice/ReviewHome";
import { initI18n } from "@/i18n/init";
import * as api from "@/lib/practice-api";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

vi.mock("@/components/learning/practice/PracticeSession", () => ({
  PracticeSession: ({
    questions,
    onClose,
  }: {
    questions?: { id: number }[];
    onClose: () => void;
  }) => (
    <div data-testid="practice-session" data-questions={JSON.stringify(questions ?? [])}>
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
  PracticeInsights: ({
    courseId,
    revision,
    workspaceId,
  }: {
    courseId: string;
    revision: number;
    workspaceId?: string;
  }) => (
    <div
      data-testid="practice-insights"
      data-course={courseId}
      data-revision={revision}
      data-workspace={workspaceId ?? ""}
    />
  ),
}));
vi.mock("@/components/learning/LibraryWorkspace", () => ({
  WorkspaceLabel: ({ row }: { row?: { content_workspace_id?: string } }) => (
    <span data-testid="workspace-label">{row?.content_workspace_id ?? ""}</span>
  ),
  useLearningCreation: () => ({ begin: () => {}, dialog: null }),
}));
vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: (): {
    workspaces: Pick<ChatWorkspaceRegistration, "workspace_id" | "display_name">[];
    error: string;
  } => ({
    workspaces: [{ workspace_id: "ws-1", display_name: "Alpha Lab" }],
    error: "",
  }),
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getPracticeSummary).mockResolvedValue({ ...summaryBase });
  vi.mocked(api.getPracticeQueue).mockResolvedValue([]);
});

it("shows placeholder statistics while the summary request is pending", () => {
  vi.mocked(api.getPracticeSummary).mockReturnValue(new Promise(() => {}));
  render(<ReviewHome />);
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Review scope" })).toHaveValue("*");
});

it("loads review statistics and enables starting when questions are due", async () => {
  render(<ReviewHome />);
  expect(await screen.findByText("3")).toBeInTheDocument();
  expect(screen.getByText("5")).toBeInTheDocument();
  expect(screen.getByText("7")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  expect(api.getPracticeSummary).toHaveBeenCalledWith("", "*");
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeEnabled();
});

it("keeps the start button disabled and the zero counts visible when nothing is due", async () => {
  vi.mocked(api.getPracticeSummary).mockResolvedValue({ ...summaryBase, due: 0 });
  render(<ReviewHome />);
  expect(await screen.findAllByText("10")).toHaveLength(2);
  expect(screen.getByText("0")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start today's review" })).toBeDisabled();
  expect(screen.queryByTestId("practice-session")).not.toBeInTheDocument();
});

it("renders a session from the due queue and refreshes the summary after closing", async () => {
  vi.mocked(api.getPracticeQueue).mockResolvedValue([
    {
      content_workspace_id: "ws-1",
      content_workspace_name: "Alpha Lab",
      entry: { id: 7 } as api.PracticeQuestion["entry"],
      state: { version: 1, review_count: 0, is_mistake: false, due_at: 100 },
    },
  ]);
  render(<ReviewHome />);
  fireEvent.click(await screen.findByRole("button", { name: "Start today's review" }));
  const session = await screen.findByTestId("practice-session");
  expect(JSON.parse(session.getAttribute("data-questions") ?? "[]")).toEqual([
    { id: 7, content_workspace_id: "ws-1", content_workspace_name: "Alpha Lab" },
  ]);
  expect(api.getPracticeQueue).toHaveBeenCalledWith("", "*");
  expect(screen.queryByRole("button", { name: "Import questions" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close session" }));
  expect(await screen.findByRole("button", { name: "Import questions" })).toBeVisible();
  expect(screen.getByTestId("practice-insights")).toHaveAttribute("data-revision", "1");
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("shows the caught-up notice when the due queue turns out to be empty", async () => {
  vi.mocked(api.getPracticeSummary).mockResolvedValue({ ...summaryBase, due: 2 });
  render(<ReviewHome />);
  fireEvent.click(await screen.findByRole("button", { name: "Start today's review" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "You are caught up. Come back when your next reviews are due."
  );
  expect(api.getPracticeQueue).toHaveBeenCalledWith("", "*");
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("surfaces summary failures with a retry that reloads the statistics", async () => {
  vi.mocked(api.getPracticeSummary)
    .mockRejectedValueOnce(new Error("backend offline"))
    .mockResolvedValue({ ...summaryBase });
  render(<ReviewHome />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("backend offline");
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("3")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(api.getPracticeSummary).toHaveBeenCalledTimes(2);
});

it("warns that only available workspaces are shown when one is unavailable", async () => {
  vi.mocked(api.getPracticeSummary).mockResolvedValue({
    ...summaryBase,
    unavailable_workspaces: ["ws-2"],
  });
  render(<ReviewHome />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Some workspaces could not be loaded. Available content is shown."
  );
  expect(screen.getByText("3")).toBeInTheDocument();
});

it("reloads the summary for the chosen workspace when the scope changes", async () => {
  render(<ReviewHome />);
  await screen.findByText("3");
  fireEvent.change(screen.getByRole("combobox", { name: "Review scope" }), {
    target: { value: "ws-1" },
  });
  expect(screen.getByRole("combobox", { name: "Review scope" })).toHaveValue("ws-1");
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  await screen.findByText("3");
  expect(api.getPracticeSummary).toHaveBeenLastCalledWith("", "ws-1");
  expect(screen.getByTestId("practice-insights")).toHaveAttribute("data-workspace", "ws-1");
});
