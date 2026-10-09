import { useState } from "react";
import {
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import QuizConfigPanel from "@/components/quiz/QuizConfigPanel";
import {
  DEFAULT_QUIZ_CONFIG,
  type DeepQuestionFormConfig,
} from "@/lib/quiz-types";

initI18n("en");

interface PanelOptions {
  initial?: Partial<DeepQuestionFormConfig>;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  uploadedPdf?: File | null;
  onUploadPdf?: (file: File | null) => void;
}

/**
 * Controlled harness so interactions flow through real React state the
 * same way the composer drives the panel in production.
 */
function renderPanel(options: PanelOptions = {}) {
  const onChange = vi.fn();
  let lastPayload: DeepQuestionFormConfig | null = null;
  function Harness() {
    const [value, setValue] = useState<DeepQuestionFormConfig>({
      ...DEFAULT_QUIZ_CONFIG,
      ...options.initial,
    });
    return (
      <QuizConfigPanel
        value={value}
        onChange={(next) => {
          onChange(next);
          lastPayload = next;
          setValue(next);
        }}
        uploadedPdf={options.uploadedPdf ?? null}
        onUploadPdf={options.onUploadPdf ?? (() => undefined)}
        collapsed={options.collapsed}
        onToggleCollapsed={options.onToggleCollapsed}
      />
    );
  }
  const view = render(<Harness />);
  return {
    onChange,
    lastPayload: () => lastPayload,
    ...view,
  };
}

function makePdf(name = "paper.pdf"): File {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

function typeTrigger() {
  // The wrapping label's textContent includes the trigger's summary text
  // (e.g. "TypeAuto"), so match the label with a substring query and use
  // the returned control directly.
  return screen.getByLabelText("Type", { exact: false });
}

describe("QuizConfigPanel smoke", () => {
  it("renders custom-mode defaults without the collapsible header (bare form branch)", () => {
    renderPanel();

    // Bare form: no CollapsibleConfigSection header when `collapsed` is
    // omitted.
    expect(screen.queryByText("Settings")).toBeNull();

    // Mode toggle with "Custom" active by default.
    expect(
      screen.getByRole("button", { name: "Custom" }).className,
    ).toContain("bg-[var(--muted)]");
    expect(
      screen.getByRole("button", { name: "Mimic Paper" }),
    ).toBeInTheDocument();

    // Default config fields: count 3, difficulty auto, type trigger "Auto".
    expect(screen.getByLabelText("Count")).toHaveValue(3);
    const difficulty = screen.getByLabelText("Difficulty");
    expect(difficulty).toHaveValue("auto");
    expect(
      within(difficulty).getByRole("option", { name: "Auto" }),
    ).toBeInTheDocument();
    expect(
      within(difficulty).getByRole("option", { name: "Easy" }),
    ).toBeInTheDocument();
    expect(
      within(difficulty).getByRole("option", { name: "Medium" }),
    ).toBeInTheDocument();
    expect(
      within(difficulty).getByRole("option", { name: "Hard" }),
    ).toBeInTheDocument();
    const trigger = typeTrigger();
    expect(trigger).toHaveTextContent("Auto");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Fewer than two selected types hides the ratio bar.
    expect(screen.queryByText("Type Mix")).toBeNull();
  });

  it("switches to mimic mode and renders the paper fields (callback + branch)", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Mimic Paper" }));
    expect(lastPayload()).toEqual(
      expect.objectContaining({ mode: "mimic" }),
    );

    // Rerendered through harness state: custom fields are gone and the
    // no-PDF branch shows the dashed upload affordance.
    expect(screen.queryByLabelText("Count")).toBeNull();
    expect(screen.getByText("Upload PDF")).toBeInTheDocument();
    expect(screen.getByLabelText("Parsed Dir")).toHaveValue("");
    expect(screen.getByLabelText("Max")).toHaveValue(10);
  });

  it("changes difficulty via the select and reports it through onChange", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel();

    await user.selectOptions(screen.getByLabelText("Difficulty"), "hard");
    expect(lastPayload()).toEqual(
      expect.objectContaining({ difficulty: "hard" }),
    );
  });

  it("clamps an out-of-range question count back to the minimum (validation)", () => {
    const { lastPayload } = renderPanel();

    const count = screen.getByLabelText("Count");
    fireEvent.change(count, { target: { value: "0" } });
    expect(lastPayload()).toEqual(
      expect.objectContaining({ num_questions: 1 }),
    );

    fireEvent.change(count, { target: { value: "" } });
    expect(lastPayload()).toEqual(
      expect.objectContaining({ num_questions: 1 }),
    );
  });

  it("clamps the mimic max-question input to the minimum (validation)", () => {
    const { lastPayload } = renderPanel({ initial: { mode: "mimic" } });

    fireEvent.change(screen.getByLabelText("Max"), {
      target: { value: "0" },
    });
    expect(lastPayload()).toEqual(
      expect.objectContaining({ max_questions: 1 }),
    );
  });

  it("uploads a PDF via the file input: forwards the file and clears paper_path", () => {
    const onUploadPdf = vi.fn();
    const { lastPayload } = renderPanel({
      initial: { mode: "mimic", paper_path: "2211asm1" },
      onUploadPdf,
    });

    const input = document.querySelector<HTMLInputElement>(
      'input[type="file"][accept=".pdf,application/pdf"]',
    );
    expect(input).not.toBeNull();
    const pdf = makePdf();
    fireEvent.change(input!, { target: { files: [pdf] } });

    expect(onUploadPdf).toHaveBeenCalledWith(pdf);
    expect(lastPayload()).toEqual(
      expect.objectContaining({ paper_path: "" }),
    );
  });

  it("ignores a dropped non-PDF file but accepts a dropped PDF (validation)", () => {
    const onUploadPdf = vi.fn();
    const { lastPayload } = renderPanel({
      initial: { mode: "mimic" },
      onUploadPdf,
    });

    const dropZone = screen.getByText("Upload PDF").closest("label");
    expect(dropZone).not.toBeNull();

    const txt = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(dropZone!, { dataTransfer: { files: [txt] } });
    expect(onUploadPdf).not.toHaveBeenCalled();
    expect(lastPayload()).toBeNull();

    const pdf = makePdf();
    fireEvent.drop(dropZone!, { dataTransfer: { files: [pdf] } });
    expect(onUploadPdf).toHaveBeenCalledWith(pdf);
    expect(lastPayload()).toEqual(
      expect.objectContaining({ paper_path: "" }),
    );
  });

  it("removes an uploaded PDF through the chip button", async () => {
    const user = userEvent.setup();
    const onUploadPdf = vi.fn();
    renderPanel({
      initial: { mode: "mimic" },
      uploadedPdf: makePdf("exam.pdf"),
      onUploadPdf,
    });

    expect(screen.getByText("exam.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove PDF" }));
    expect(onUploadPdf).toHaveBeenCalledWith(null);
  });

  it("typing a parsed dir clears any uploaded PDF and updates paper_path", async () => {
    const user = userEvent.setup();
    const onUploadPdf = vi.fn();
    const { lastPayload } = renderPanel({
      initial: { mode: "mimic", paper_path: "" },
      onUploadPdf,
    });

    const dir = screen.getByLabelText("Parsed Dir");
    await user.type(dir, "2211");
    expect(onUploadPdf).toHaveBeenCalledWith(null);
    expect(lastPayload()).toEqual(
      expect.objectContaining({ paper_path: "2211" }),
    );
  });

  it("selects question types through the portal menu and shows the ratio bar", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel();

    const trigger = typeTrigger();
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Portal menu rows render into document.body.
    await user.click(
      screen.getByRole("button", { name: "Multiple Choice" }),
    );
    expect(trigger).toHaveTextContent("Multiple Choice");

    await user.click(screen.getByRole("button", { name: "Concept Question" }));
    // Two types with default total 3 rebalance to an even-ish split:
    // remainder lands on the first type.
    expect(lastPayload()).toEqual(
      expect.objectContaining({
        num_questions: 3,
        per_type_counts: { choice: 2, concept: 1 },
      }),
    );

    // The type menu stays open while picking; close it before asserting
    // the legend so menu rows don't collide with legend labels.
    await user.keyboard("{Escape}");

    // Ratio bar with legend and running total.
    expect(screen.getByText("Type Mix")).toBeInTheDocument();
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByText("Multiple Choice")).toBeInTheDocument();
    expect(screen.getByText("Concept Question")).toBeInTheDocument();
  });

  it("auto-bumps the total so every selected type gets at least 1 (validation)", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel({ initial: { num_questions: 1 } });

    await user.click(typeTrigger());
    await user.click(screen.getByRole("button", { name: "Multiple Choice" }));
    await user.click(screen.getByRole("button", { name: "Concept Question" }));
    await user.click(screen.getByRole("button", { name: "Essay" }));

    expect(lastPayload()).toEqual(
      expect.objectContaining({
        num_questions: 3,
        per_type_counts: { choice: 1, concept: 1, written: 1 },
      }),
    );
  });

  it("clears per-type counts when the selection drops below two types", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel({
      initial: {
        question_types: ["choice", "concept"],
        per_type_counts: { choice: 2, concept: 1 },
      },
    });

    await user.click(typeTrigger());
    // Trigger now summarizes "2 types"; the Auto row is the only "Auto"
    // button outside the trigger, and clearing goes through it.
    await user.click(screen.getByRole("button", { name: "Auto" }));

    expect(lastPayload()).toEqual(
      expect.objectContaining({ question_types: [], per_type_counts: {} }),
    );
  });

  it("deselecting one of two types clears per_type_counts via the rebalance effect", async () => {
    const user = userEvent.setup();
    const { lastPayload } = renderPanel({
      initial: {
        question_types: ["choice", "concept"],
        per_type_counts: { choice: 2, concept: 1 },
      },
    });

    await user.click(typeTrigger());
    await user.click(screen.getByRole("button", { name: "Concept Question" }));

    expect(lastPayload()).toEqual(
      expect.objectContaining({
        question_types: ["choice"],
        per_type_counts: {},
      }),
    );
  });

  it("preserves user-set counts on mount when they already sum to the total (default branch)", async () => {
    const { onChange } = renderPanel({
      initial: {
        question_types: ["choice", "concept"],
        per_type_counts: { choice: 2, concept: 1 },
        num_questions: 3,
      },
    });

    // Flush effects/microtasks: a consistent configuration must not
    // trigger any rebalance write-back.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("closes the type menu on Escape", async () => {
    const user = userEvent.setup();
    renderPanel();

    const trigger = typeTrigger();
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: "Multiple Choice" }),
    ).toBeNull();
  });

  it("collapsed section hides the body, shows the config summary, and reports toggles", async () => {
    const user = userEvent.setup();
    const onToggleCollapsed = vi.fn();
    const { unmount } = renderPanel({
      collapsed: true,
      onToggleCollapsed,
      initial: {
        question_types: ["choice", "concept"],
        per_type_counts: { choice: 2, concept: 1 },
      },
    });

    // Collapsed: fields are hidden, the one-line summary is visible.
    expect(screen.queryByLabelText("Count")).toBeNull();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByText(/Custom · 3 questions · Auto · 2 types/),
    ).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /Settings/ });
    await user.click(toggle);
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);

    unmount();

    // Expanded branch: body visible, summary hidden.
    renderPanel({ collapsed: false });
    expect(screen.getByLabelText("Count")).toBeInTheDocument();
    expect(screen.queryByText(/3 questions/)).toBeNull();
  });
});
