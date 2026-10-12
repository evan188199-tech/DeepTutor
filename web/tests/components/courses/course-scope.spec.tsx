import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CourseScopeChip, useCourseScope, type CourseScope } from "@/components/courses/CourseScope";
import { initI18n } from "@/i18n/init";
import type { StudyCourse } from "@/lib/courses-api";

initI18n("en");

const fixture = vi.hoisted(() => ({
  searchParams: "",
  pathname: "/learning/practice",
  replace: vi.fn(),
  listCourses: vi.fn(),
  attachCourseResource: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(fixture.searchParams),
  usePathname: () => fixture.pathname,
  useRouter: () => ({ replace: fixture.replace }),
}));

vi.mock("@/lib/courses-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/courses-api")>()),
  listCourses: (...args: unknown[]) => fixture.listCourses(...args),
  attachCourseResource: (...args: unknown[]) =>
    fixture.attachCourseResource(...args),
}));

const captured: { scope: CourseScope | null } = { scope: null };

function Harness() {
  const scope = useCourseScope();
  captured.scope = scope;
  return scope ? <CourseScopeChip scope={scope} /> : null;
}

function makeCourse(): StudyCourse {
  return {
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
    resources: [
      {
        id: "res-1",
        kind: "notebook",
        ref_id: "nb-1",
        label: "Lecture notes",
        position: 0,
        added_at: 1,
      },
      {
        id: "res-2",
        kind: "book",
        ref_id: "book-1",
        label: "Textbook",
        position: 1,
        added_at: 2,
      },
    ],
    syllabus: [],
    status: "active",
    archived_at: 0,
  };
}

async function renderResolved(): Promise<void> {
  fixture.listCourses.mockResolvedValue([makeCourse()]);
  render(<Harness />);
  await screen.findByText("Linear Algebra");
}

beforeEach(() => {
  fixture.searchParams = "?course=course-1";
  fixture.replace.mockClear();
  fixture.listCourses.mockReset();
  fixture.attachCourseResource.mockReset();
});

describe("useCourseScope", () => {
  it("returns no scope and renders nothing when the URL carries no course", async () => {
    fixture.searchParams = "";
    render(<Harness />);

    expect(captured.scope).toBeNull();
    expect(screen.queryByText("This course")).not.toBeInTheDocument();
    expect(fixture.listCourses).not.toHaveBeenCalled();
  });

  it("resolves the course from the id and shows its name in the chip", async () => {
    await renderResolved();

    expect(captured.scope?.id).toBe("course-1");
    expect(captured.scope?.course?.name).toBe("Linear Algebra");
  });

  it("links the chip back to the course page", async () => {
    await renderResolved();

    expect(screen.getByRole("link", { name: /Linear Algebra/ })).toHaveAttribute(
      "href",
      "/courses/course-1",
    );
  });

  it("falls back to This course when the course cannot be read", async () => {
    fixture.listCourses.mockRejectedValue(new Error("offline"));
    render(<Harness />);

    expect(await screen.findByText("This course")).toBeInTheDocument();
    expect(captured.scope?.course).toBeNull();
  });

  it("falls back to This course when the id matches no course", async () => {
    fixture.listCourses.mockResolvedValue([]);
    render(<Harness />);

    expect(await screen.findByText("This course")).toBeInTheDocument();
    expect(captured.scope?.course).toBeNull();
  });

  it("lists only the reference ids of the requested kind", async () => {
    await renderResolved();

    expect(captured.scope?.refIds("notebook")).toEqual(["nb-1"]);
    expect(captured.scope?.refIds("book")).toEqual(["book-1"]);
    expect(captured.scope?.refIds("reading_workspace")).toEqual([]);
  });

  it("attaches a created resource to the course", async () => {
    await renderResolved();
    fixture.attachCourseResource.mockResolvedValue(undefined);

    await act(async () => {
      await captured.scope?.attach("notebook", "nb-2", "Problem set");
    });

    expect(fixture.attachCourseResource).toHaveBeenCalledWith("course-1", {
      kind: "notebook",
      ref_id: "nb-2",
      label: "Problem set",
    });
  });

  it("swallows attach failures so the creation itself survives", async () => {
    await renderResolved();
    fixture.attachCourseResource.mockRejectedValue(new Error("attach failed"));

    await act(async () => {
      await expect(
        captured.scope?.attach("notebook", "nb-2", "Problem set"),
      ).resolves.toBeUndefined();
    });
  });

  it("ignores attach calls without a reference id", async () => {
    await renderResolved();

    await act(async () => {
      await captured.scope?.attach("notebook", "", "Untitled");
    });

    expect(fixture.attachCourseResource).not.toHaveBeenCalled();
  });

  it("returns to the unscoped surface when the chip is dismissed", async () => {
    await renderResolved();

    fireEvent.click(
      screen.getByRole("button", { name: "Show every course" }),
    );

    expect(fixture.replace).toHaveBeenCalledWith("/learning/practice");
  });
});
