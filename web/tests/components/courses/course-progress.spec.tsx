import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CourseProgress from "@/components/courses/CourseProgress";
import { initI18n } from "@/i18n/init";
import type { CourseState } from "@/lib/courses-api";

initI18n("en");

function tile(label: string): HTMLElement {
  const heading = screen.getByText(label);
  return heading.closest("a") as HTMLElement;
}

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
    resources: [],
    sessions: { active: 0, archived: 0, recent: [] },
    mastery: { paths: [] },
    question_bank: { total: 0, wrong: 0, weak_categories: [] },
    reading: { workspaces: [] },
    syllabus: { total: 0, covered: 0, next: null, units: [] },
    ...overrides,
  };
}

describe("CourseProgress", () => {
  it("shows em-dashes and attach hints on every tile when the state is missing", () => {
    render(<CourseProgress state={null} courseId="course-1" />);

    for (const label of [
      "Mastery Path",
      "Question Bank",
      "Immersive Reading",
      "Notebooks",
    ]) {
      expect(tile(label)).toHaveTextContent("—");
    }
    expect(
      screen.getByText("Attach or build a path to track mastery"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Questions you get wrong land here"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Attach a reading workspace to read alongside the tutor",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Attach a notebook to keep this course's notes together",
      ),
    ).toBeInTheDocument();
  });

  it("sums objectives, wrong answers, materials, and notebook counts", () => {
    const state = makeState({
      resources: [
        notebook("nb-1"),
        notebook("nb-2"),
        attached("book", "book-1"),
      ],
      mastery: {
        paths: [
          path("path-1", "Vectors", 3, 2, ["Basis change"]),
          path("path-2", "Matrices", 4, 1, []),
        ],
      },
      question_bank: {
        total: 10,
        wrong: 3,
        weak_categories: [{ name: "Eigenvalues", wrong: 3 }],
      },
      reading: {
        workspaces: [
          { workspace_id: "ws-1", title: "Chapter 1", materials: 2 },
          { workspace_id: "ws-2", title: "Chapter 2", materials: 3 },
        ],
      },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(tile("Mastery Path")).toHaveTextContent("3/7");
    expect(tile("Question Bank")).toHaveTextContent("3");
    expect(tile("Immersive Reading")).toHaveTextContent("5");
    expect(tile("Notebooks")).toHaveTextContent("2");
  });

  it("deep-links a single path and workspace but scopes shared tiles by course", () => {
    const state = makeState({
      resources: [notebook("nb-1")],
      mastery: {
        paths: [path("path-1", "Vectors", 3, 2, [])],
      },
      reading: {
        workspaces: [{ workspace_id: "ws-1", title: "Chapter 1", materials: 2 }],
      },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(tile("Mastery Path")).toHaveAttribute(
      "href",
      "/learning/mastery/path-1",
    );
    expect(tile("Immersive Reading")).toHaveAttribute(
      "href",
      "/learning/reading/ws-1",
    );
    expect(tile("Question Bank")).toHaveAttribute(
      "href",
      "/learning/practice?course=course-1",
    );
    expect(tile("Notebooks")).toHaveAttribute(
      "href",
      "/notebooks?course=course-1",
    );
  });

  it("falls back to the scoped mastery home when several paths exist", () => {
    const state = makeState({
      mastery: {
        paths: [
          path("path-1", "Vectors", 3, 2, []),
          path("path-2", "Matrices", 4, 1, []),
        ],
      },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(tile("Mastery Path")).toHaveAttribute(
      "href",
      "/learning/mastery?course=course-1",
    );
  });

  it("names the weakest mastery point when the course has objectives", () => {
    const state = makeState({
      mastery: {
        paths: [path("path-1", "Vectors", 6, 1, ["Basis change"])],
      },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(
      screen.getByText("6 objectives · weakest Basis change"),
    ).toBeInTheDocument();
  });

  it("names the weakest question category with its totals", () => {
    const state = makeState({
      question_bank: {
        total: 12,
        wrong: 5,
        weak_categories: [{ name: "Eigenvalues", wrong: 5 }],
      },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(
      screen.getByText("wrong of 12 · weakest Eigenvalues"),
    ).toBeInTheDocument();
  });

  it("falls back to a plain wrong-of-total detail without a weak category", () => {
    const state = makeState({
      question_bank: { total: 9, wrong: 2, weak_categories: [] },
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(screen.getByText("wrong of 9")).toBeInTheDocument();
  });

  it("counts only notebook-kind resources as notebooks", () => {
    const state = makeState({
      resources: [
        notebook("nb-1"),
        attached("book", "book-1"),
        attached("knowledge_base", "kb-1"),
      ],
    });
    render(<CourseProgress state={state} courseId="course-1" />);

    expect(tile("Notebooks")).toHaveTextContent("1");
  });
});

function path(
  pathId: string,
  name: string,
  objectivesTotal: number,
  objectivesMastered: number,
  weakPoints: string[],
): CourseState["mastery"]["paths"][number] {
  return {
    path_id: pathId,
    name,
    objectives_total: objectivesTotal,
    objectives_mastered: objectivesMastered,
    stage: "active",
    weak_points: weakPoints,
  };
}

function notebook(refId: string): CourseState["resources"][number] {
  return attached("notebook", refId);
}

function attached(
  kind: CourseState["resources"][number]["kind"],
  refId: string,
): CourseState["resources"][number] {
  return {
    id: `${kind}-${refId}`,
    kind,
    ref_id: refId,
    label: refId,
    position: 0,
    added_at: 1,
    available: true,
    detail: {},
  };
}
