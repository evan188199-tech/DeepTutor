import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import CourseSyllabus from "@/components/courses/CourseSyllabus";
import type { CourseState } from "@/lib/courses-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts === "object" && opts !== null
        ? key.replace(/\{\{(\w+)\}\}/g, (_, name) => String(opts[name] ?? ""))
        : key,
  }),
}));

function makeState(
  units: CourseState["syllabus"]["units"],
  next: CourseState["syllabus"]["next"] = null,
): CourseState {
  const covered = units.filter((unit) => unit.covered).length;
  return {
    course: {
      id: "course-1",
      name: "Operating Systems",
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
    syllabus: { total: units.length, covered, next, units },
  };
}

const onSave = vi.fn();
const onToggle = vi.fn();

beforeEach(() => {
  onSave.mockReset();
  onToggle.mockReset();
});

it("reads a null state as an empty syllabus with an add affordance", () => {
  render(<CourseSyllabus state={null} onSave={onSave} onToggle={onToggle} />);

  expect(screen.getByRole("heading", { name: "Syllabus" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
  expect(
    screen.getByText(
      "What this course should cover. Without it, progress has no denominator.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).toBeNull();
});

it("renders each unit with its number, topics and the covered fraction", () => {
  render(
    <CourseSyllabus
      state={makeState(
        [
          {
            id: "u1",
            position: 0,
            title: "Processes and threads",
            topics: ["context switch", "scheduling"],
            covered: true,
            wrong_questions: 0,
          },
          {
            id: "u2",
            position: 1,
            title: "Virtual memory",
            topics: ["address translation"],
            covered: true,
            wrong_questions: 0,
          },
          {
            id: "u3",
            position: 2,
            title: "File systems",
            topics: [],
            covered: false,
            wrong_questions: 3,
          },
        ],
        { id: "u3", title: "File systems", position: 2 },
      )}
      onSave={onSave}
      onToggle={onToggle}
    />,
  );

  expect(screen.getByText("2 of 3 units covered")).toBeInTheDocument();
  const bar = screen.getByRole("progressbar");
  expect(bar).toHaveAttribute("aria-valuenow", "67");
  expect(screen.getByText("1. Processes and threads")).toBeInTheDocument();
  expect(screen.getByText("2. Virtual memory")).toBeInTheDocument();
  expect(screen.getByText("3. File systems")).toBeInTheDocument();
  expect(screen.getByText("context switch · scheduling")).toBeInTheDocument();
  // evidence next to the checkbox, not a computed verdict
  expect(screen.getByText("3 wrong")).toBeInTheDocument();
  expect(screen.queryByText(/0 wrong/)).toBeNull();
});

it("toggles coverage through the unit checkbox", () => {
  render(
    <CourseSyllabus
      state={makeState([
        {
          id: "u1",
          position: 0,
          title: "Processes and threads",
          topics: [],
          covered: false,
          wrong_questions: 0,
        },
      ])}
      onSave={onSave}
      onToggle={onToggle}
    />,
  );
  onToggle.mockResolvedValue(undefined);

  const box = screen.getByRole("checkbox", {
    name: "1. Processes and threads",
  });
  expect(box).not.toBeChecked();
  fireEvent.click(box);

  expect(onToggle).toHaveBeenCalledWith("u1", true);
});

it("round-trips the editor: seeds one unit per line, keeps ids by title, trims topics and drops blank lines", async () => {
  onSave.mockResolvedValue(undefined);
  render(
    <CourseSyllabus
      state={makeState([
        {
          id: "u1",
          position: 0,
          title: "Processes and threads",
          topics: ["context switch", "scheduling"],
          covered: true,
          wrong_questions: 0,
        },
      ])}
      onSave={onSave}
      onToggle={onToggle}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Edit" }));

  const editor = screen.getByRole("textbox");
  expect(editor).toHaveValue(
    "Processes and threads | context switch, scheduling",
  );

  fireEvent.change(editor, {
    target: {
      value:
        "Processes and threads | context switch, scheduling\n\n  Virtual memory |  address translation ,  page  \nDeadlocks",
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await screen.findByRole("button", { name: "Edit" });
  expect(onSave).toHaveBeenCalledWith([
    {
      id: "u1",
      title: "Processes and threads",
      topics: ["context switch", "scheduling"],
    },
    {
      title: "Virtual memory",
      topics: ["address translation", "page"],
    },
    { title: "Deadlocks", topics: [] },
  ]);
});

it("cancel returns to the list without saving", () => {
  render(
    <CourseSyllabus
      state={makeState([
        {
          id: "u1",
          position: 0,
          title: "Processes and threads",
          topics: [],
          covered: false,
          wrong_questions: 0,
        },
      ])}
      onSave={onSave}
      onToggle={onToggle}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Scratch draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(screen.getByText("1. Processes and threads")).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(onSave).not.toHaveBeenCalled();
});
