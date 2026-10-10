import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ComponentProps, ReactNode } from "react";

import CourseResources from "@/components/courses/CourseResources";
import type { CourseResourceState } from "@/lib/courses-api";

vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: Omit<ComponentProps<"a">, "children"> & { children?: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts === "object" && opts !== null
        ? key.replace(/\{\{(\w+)\}\}/g, (_, name) => String(opts[name] ?? ""))
        : key,
  }),
}));

const fixture = vi.hoisted(() => ({
  listCandidates: vi.fn(),
}));

vi.mock("@/lib/courses-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/courses-api")>()),
  listCourseResourceCandidates: (...args: unknown[]) =>
    fixture.listCandidates(...args),
}));

function makeResource(
  overrides: Partial<CourseResourceState> = {},
): CourseResourceState {
  return {
    id: "res-1",
    kind: "knowledge_base",
    ref_id: "kb-1",
    label: "Graphs KB",
    position: 0,
    added_at: 1,
    available: true,
    detail: {},
    ...overrides,
  };
}

const onAttach = vi.fn();
const onDetach = vi.fn();

beforeEach(() => {
  fixture.listCandidates.mockReset();
  onAttach.mockReset();
  onDetach.mockReset();
});

it("shows the empty attach state when the course references nothing", () => {
  render(
    <CourseResources
      courseId="course-1"
      resources={[]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  expect(screen.getByRole("heading", { name: "Materials" })).toBeInTheDocument();
  expect(
    screen.getByText(/Nothing attached yet\./),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove from course" })).toBeNull();
  // the picker stays closed and idle until asked for
  expect(fixture.listCandidates).not.toHaveBeenCalled();
});

it("renders one row per attached resource with its kind, unavailable marker and remove action", () => {
  render(
    <CourseResources
      courseId="course-1"
      resources={[
        makeResource(),
        makeResource({
          id: "res-2",
          kind: "book",
          ref_id: "book-9",
          label: "OSTEP",
          available: false,
        }),
      ]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  expect(screen.getByText("Graphs KB")).toBeInTheDocument();
  expect(screen.getByText("OSTEP")).toBeInTheDocument();
  expect(screen.getByText("Knowledge base")).toBeInTheDocument();
  expect(screen.getByText("Book")).toBeInTheDocument();
  // a dead pointer stays visible as unavailable instead of vanishing
  expect(screen.getByText(/Unavailable/)).toBeInTheDocument();
  const removeButtons = screen.getAllByRole("button", {
    name: "Remove from course",
  });
  expect(removeButtons).toHaveLength(2);
});

it("detaches by resource id when remove is clicked", () => {
  render(
    <CourseResources
      courseId="course-1"
      resources={[makeResource()]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Remove from course" }));
  expect(onDetach).toHaveBeenCalledWith("res-1");
});

it("loads the candidate catalogue on demand and attaches the picked row", async () => {
  onAttach.mockResolvedValue(undefined);
  fixture.listCandidates.mockResolvedValue({
    knowledge_base: [{ ref_id: "kb-1", label: "Graphs KB" }],
    book: [{ ref_id: "book-9", label: "OSTEP" }],
    notebook: [],
  });
  render(
    <CourseResources
      courseId="course-1"
      resources={[makeResource()]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(fixture.listCandidates).toHaveBeenCalledWith({ force: true });
  expect(fixture.listCandidates).toHaveBeenCalledTimes(1);

  // the already-attached candidate is offered but disabled and marked
  const attachedChip = await screen.findByRole("button", { name: "✓ Graphs KB" });
  expect(attachedChip).toBeDisabled();

  fireEvent.click(screen.getByRole("button", { name: "OSTEP" }));
  await waitFor(() =>
    expect(onAttach).toHaveBeenCalledWith({
      kind: "book",
      ref_id: "book-9",
      label: "OSTEP",
    }),
  );
});

it("keeps the picker usable when the catalogue cannot be read", async () => {
  fixture.listCandidates.mockRejectedValue(new Error("offline"));
  render(
    <CourseResources
      courseId="course-1"
      resources={[makeResource()]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(
    await screen.findByText(/Nothing made yet to attach\./),
  ).toBeInTheDocument();
  // the attached list above the picker still renders
  expect(screen.getByText("Graphs KB")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("links each create route back to this course, encoded", async () => {
  fixture.listCandidates.mockResolvedValue({});
  render(
    <CourseResources
      courseId="course 1"
      resources={[]}
      onAttach={onAttach}
      onDetach={onDetach}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  const mastery = await screen.findByRole("link", { name: "New mastery path" });
  expect(mastery).toHaveAttribute("href", "/learning/mastery?course=course%201");
  expect(
    screen.getByRole("link", { name: "New reading collection" }),
  ).toHaveAttribute("href", "/learning/reading?course=course%201");
  expect(screen.getByRole("link", { name: "New notebook" })).toHaveAttribute(
    "href",
    "/notebooks?course=course%201",
  );
  expect(
    screen.getByRole("link", { name: "New knowledge base" }),
  ).toHaveAttribute("href", "/knowledge-bases");
  // an empty catalogue on every kind still offers these
  expect(screen.getByText(/Nothing made yet to attach\./)).toBeInTheDocument();
});
