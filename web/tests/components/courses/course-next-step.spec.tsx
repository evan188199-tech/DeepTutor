import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CourseNextStep from "@/components/courses/CourseNextStep";
import { initI18n } from "@/i18n/init";
import type { CourseState } from "@/lib/courses-api";

initI18n("en");

const fixture = vi.hoisted(() => ({
  push: vi.fn(),
  setPendingPrompt: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: fixture.push }),
}));

vi.mock("@/lib/pending-prompt", () => ({
  setPendingPrompt: fixture.setPendingPrompt,
}));

function makeState(overrides: Partial<CourseState> = {}): CourseState {
  return {
    course: {
      id: "course-1",
      name: "Linear Algebra",
      description: "",
      color: "#C65D2E",
      created_at: 1,
      updated_at: 1,
      instructions: "",
      agent_notes: "",
      default_capability: "",
      default_persona: "",
      resources: [],
      syllabus: [],
      status: "active",
      archived_at: 0,
    },
    resources: [
      {
        id: "res-1",
        kind: "book",
        ref_id: "book-1",
        label: "Textbook",
        position: 0,
        added_at: 1,
        available: true,
        detail: {},
      },
    ],
    sessions: { active: 0, archived: 0, recent: [] },
    mastery: { paths: [] },
    question_bank: { total: 0, wrong: 0, weak_categories: [] },
    reading: { workspaces: [] },
    syllabus: { total: 0, covered: 0, next: null, units: [] },
    ...overrides,
  };
}

beforeEach(() => {
  fixture.push.mockClear();
  fixture.setPendingPrompt.mockClear();
});

describe("CourseNextStep", () => {
  it("shows the empty hint with no action when the state has not loaded", () => {
    render(<CourseNextStep state={null} courseId="course-1" />);

    expect(
      screen.getByText("This course has nothing to work with yet"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the empty hint with no action when no resource is attached", () => {
    const state = makeState({ resources: [] });
    render(<CourseNextStep state={state} courseId="course-1" />);

    expect(
      screen.getByText("This course has nothing to work with yet"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("points at the weakest question category first", () => {
    const state = makeState({
      question_bank: {
        total: 10,
        wrong: 4,
        weak_categories: [{ name: "Eigenvalues", wrong: 4 }],
      },
      mastery: {
        paths: [
          {
            path_id: "path-1",
            name: "Core path",
            objectives_total: 5,
            objectives_mastered: 2,
            stage: "active",
            weak_points: ["Determinants"],
          },
        ],
      },
    });
    render(<CourseNextStep state={state} courseId="course-1" />);

    expect(
      screen.getByText("Eigenvalues is where you are losing marks"),
    ).toBeInTheDocument();
    expect(screen.getByText("4 questions wrong in this area")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Work through them" }),
    ).toBeInTheDocument();
  });

  it("hands the opening prompt to the chat surface and navigates there", () => {
    const state = makeState({
      question_bank: {
        total: 6,
        wrong: 2,
        weak_categories: [{ name: "Integrals", wrong: 2 }],
      },
    });
    render(<CourseNextStep state={state} courseId="course-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Work through them" }));

    expect(fixture.setPendingPrompt).toHaveBeenCalledWith(
      "Take me through my Integrals mistakes one at a time.",
      "chat",
    );
    expect(fixture.push).toHaveBeenCalledWith(
      `/chat?course=${encodeURIComponent("course-1")}&capability=course_study`,
    );
  });

  it("resumes a stalled mastery path when the bank has nothing wrong", () => {
    const state = makeState({
      mastery: {
        paths: [
          {
            path_id: "path-9",
            name: "Vectors",
            objectives_total: 8,
            objectives_mastered: 3,
            stage: "active",
            weak_points: ["Basis change"],
          },
        ],
      },
    });
    render(<CourseNextStep state={state} courseId="course-1" />);

    expect(
      screen.getByText("Vectors: 3 of 8 objectives cleared"),
    ).toBeInTheDocument();
    expect(screen.getByText("Basis change")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep going" })).toBeInTheDocument();
  });

  it("sends the learner back to open reading when no path is stalled", () => {
    const state = makeState({
      mastery: {
        paths: [
          {
            path_id: "path-9",
            name: "Vectors",
            objectives_total: 8,
            objectives_mastered: 8,
            stage: "done",
            weak_points: [],
          },
        ],
      },
      reading: {
        workspaces: [{ workspace_id: "ws-2", title: "Chapter 4", materials: 3 }],
      },
    });
    render(<CourseNextStep state={state} courseId="course-1" />);

    expect(
      screen.getByText("Chapter 4 is open and waiting"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("3 materials in this reading workspace"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read on" })).toBeInTheDocument();
  });

  it("offers to plan the course when material exists but nothing was built", () => {
    render(<CourseNextStep state={makeState()} courseId="course-1" />);

    expect(screen.getByText("The material is in place")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Plan this course" }),
    ).toBeInTheDocument();
  });

  it("disables the action and shows the opening state while navigating", () => {
    const state = makeState({
      mastery: {
        paths: [
          {
            path_id: "path-9",
            name: "Vectors",
            objectives_total: 8,
            objectives_mastered: 3,
            stage: "active",
            weak_points: ["Basis change"],
          },
        ],
      },
    });
    render(<CourseNextStep state={state} courseId="course-1" />);

    const button = screen.getByRole("button", { name: "Keep going" });
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(screen.getByText("Opening")).toBeInTheDocument();
    expect(fixture.push).toHaveBeenCalledTimes(1);
  });
});
