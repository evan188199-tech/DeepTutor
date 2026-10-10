import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import CourseDialog from "@/components/courses/CourseDialog";
import { DEFAULT_COURSE_COLORS, type StudyCourse } from "@/lib/courses-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts === "object" && opts !== null
        ? key.replace(/\{\{(\w+)\}\}/g, (_, name) => String(opts[name] ?? ""))
        : key,
  }),
}));

function makeCourse(overrides: Partial<StudyCourse> = {}): StudyCourse {
  return {
    id: "course-1",
    name: "Operating Systems",
    description: "Processes, memory, files",
    color: "#3F6F8F",
    created_at: 1,
    updated_at: 1,
    instructions: "",
    agent_notes: "",
    default_capability: "course_study",
    default_persona: "Socratic tutor",
    resources: [],
    syllabus: [],
    status: "active",
    archived_at: 0,
    ...overrides,
  };
}

const onClose = vi.fn();
const onSave = vi.fn();

beforeEach(() => {
  onClose.mockReset();
  onSave.mockReset();
});

it("renders nothing until opened", () => {
  render(<CourseDialog open={false} onClose={onClose} onSave={onSave} />);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("seeds every field from the course when opening in edit mode", async () => {
  render(
    <CourseDialog
      open
      course={makeCourse()}
      onClose={onClose}
      onSave={onSave}
    />,
  );

  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent("Edit course");
  expect(
    (screen.getByPlaceholderText("e.g. Operating Systems") as HTMLInputElement)
      .value,
  ).toBe("Operating Systems");
  expect(
    (
      screen.getByPlaceholderText(
        "What are you learning in this course?",
      ) as HTMLTextAreaElement
    ).value,
  ).toBe("Processes, memory, files");
  expect(
    (screen.getByLabelText("Choose color #3F6F8F") as HTMLButtonElement)
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    (screen.getByRole("combobox") as HTMLSelectElement).value,
  ).toBe("course_study");
  expect(
    (screen.getByPlaceholderText("Default") as HTMLInputElement).value,
  ).toBe("Socratic tutor");
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
});

it("keeps submit disabled until the name has non-whitespace content", () => {
  render(
    <CourseDialog open onClose={onClose} onSave={onSave} />,
  );

  const submit = screen.getByRole("button", { name: "Create course" });
  expect(submit).toBeDisabled();

  const name = screen.getByPlaceholderText("e.g. Operating Systems");
  fireEvent.change(name, { target: { value: "   " } });
  expect(submit).toBeDisabled();

  fireEvent.change(name, { target: { value: "Linear Algebra" } });
  expect(submit).toBeEnabled();
});

it("trims name, description and persona and passes the whole payload to onSave before closing", async () => {
  onSave.mockResolvedValue(undefined);
  render(
    <CourseDialog open onClose={onClose} onSave={onSave} />,
  );

  fireEvent.change(screen.getByPlaceholderText("e.g. Operating Systems"), {
    target: { value: "  Operating Systems  " },
  });
  fireEvent.change(
    screen.getByPlaceholderText("What are you learning in this course?"),
    { target: { value: "  Processes and memory  " },
  });
  fireEvent.change(screen.getByPlaceholderText("Default"), {
    target: { value: "  patient coach  " },
  });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "deep_question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Choose color #4F7655" }));

  fireEvent.click(screen.getByRole("button", { name: "Create course" }));

  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(onSave).toHaveBeenCalledWith({
    name: "Operating Systems",
    description: "Processes and memory",
    color: "#4F7655",
    default_capability: "deep_question",
    default_persona: "patient coach",
  });
});

it("shows the save error, stays open and resets busy when onSave rejects", async () => {
  onSave.mockRejectedValue(new Error("storage offline"));
  render(
    <CourseDialog open course={makeCourse()} onClose={onClose} onSave={onSave} />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("storage offline");
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  // busy state is reset: cancel and submit are interactive again
  expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
});

it("falls back to a generic message when onSave rejects without an Error", async () => {
  onSave.mockRejectedValue("boom");
  render(
    <CourseDialog open onClose={onClose} onSave={onSave} />,
  );

  fireEvent.change(screen.getByPlaceholderText("e.g. Operating Systems"), {
    target: { value: "Compilers" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create course" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn't save this course.",
  );
  expect(onClose).not.toHaveBeenCalled();
});

it("keeps the first palette color selected by default in create mode", () => {
  render(<CourseDialog open onClose={onClose} onSave={onSave} />);
  expect(DEFAULT_COURSE_COLORS.length).toBeGreaterThan(1);
  expect(
    screen
      .getByRole("button", { name: `Choose color ${DEFAULT_COURSE_COLORS[0]}` })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    screen
      .getByRole("button", { name: `Choose color ${DEFAULT_COURSE_COLORS[1]}` })
      .getAttribute("aria-pressed"),
  ).toBe("false");
});
