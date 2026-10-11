import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ObjectiveDetail } from "@/components/space/learning/ObjectiveDetail";
import { initI18n } from "@/i18n/init";
import type {
  LearningEvidence,
  ObjectiveAttempt,
  ObjectiveReport,
  ObjectiveReview,
} from "@/lib/learning-api";

initI18n("en");

const DAY = 86_400;

function attempt(overrides: Partial<ObjectiveAttempt> = {}): ObjectiveAttempt {
  return {
    question_id: "q-1",
    prompt: "Why do vectors span a space?",
    answer: "because any vector is a linear combination of them",
    is_correct: true,
    error_type: "",
    at: 1_700_000_500,
    ...overrides,
  };
}

function review(overrides: Partial<ObjectiveReview> = {}): ObjectiveReview {
  return {
    due_at: null,
    interval_index: 2,
    consecutive_correct: 2,
    consecutive_wrong: 0,
    stability: 3.5,
    retrievability: 0.8,
    desired_retention: 0.9,
    lapse_count: 2,
    forgetting_risk: 0.2,
    reason: "",
    ...overrides,
  };
}

function evidence(overrides: Partial<LearningEvidence> = {}): LearningEvidence {
  return {
    knowledge_point_id: "kp-1",
    timestamp: 1_700_000_000,
    source: "tutor",
    assessment_type: "quiz",
    result: "correct",
    quality: null,
    hints_used: 0,
    attempt_count: 1,
    confidence: null,
    response_time: null,
    session_id: "s-1",
    turn_id: "t-1",
    ...overrides,
  };
}

function report(overrides: Partial<ObjectiveReport> = {}): ObjectiveReport {
  return {
    id: "kp-1",
    name: "Vectors",
    type: "concept",
    module_name: "Foundations",
    status: "learning",
    gate: "qualitative",
    mastered: false,
    assessed_mastered: false,
    mastery_source: "",
    override_note: "",
    mastery: 0,
    threshold: 1,
    attempts: [],
    correct_count: 0,
    explanation: "",
    review: null,
    errors: [],
    ...overrides,
  };
}

describe("ObjectiveDetail evidence trail", () => {
  function visualEvidenceRatio(): string {
    return (
      screen.getByText("Independent visual evidence").parentElement
        ?.textContent ?? ""
    );
  }

  it("schedules the spaced review with its memory and risk figures", () => {
    render(
      <ObjectiveDetail
        report={report({
          review: review({
            due_at: Date.now() / 1000 + 3 * DAY,
            reason: "reviewed early",
          }),
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Spaced review")).toBeInTheDocument();
    expect(screen.getByText(/Due in 3 days/)).toBeInTheDocument();
    expect(
      screen.getByText("memory 80% · stability 3.5 days"),
    ).toBeInTheDocument();
    expect(screen.getByText("risk 20% · 2 lapses")).toBeInTheDocument();
    expect(screen.getByText("reviewed early")).toBeInTheDocument();
  });

  it("says when a review is not scheduled", () => {
    render(<ObjectiveDetail report={report({ review: review() })} zh={false} />);

    expect(screen.getByText("Not scheduled")).toBeInTheDocument();
  });

  it("lists attempts newest first with correct and missed marks", () => {
    const { container } = render(
      <ObjectiveDetail
        report={report({
          attempts: [
            attempt(),
            attempt({
              question_id: "q-2",
              prompt: "",
              answer: "",
              is_correct: false,
              at: 1_700_000_900,
            }),
          ],
          correct_count: 1,
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Attempts (1/2 correct)")).toBeInTheDocument();
    const items = container.querySelectorAll("ul li");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("(prompt unavailable)");
    expect(items[0].textContent).toContain("(blank)");
    expect(items[0].querySelector(".lucide-x")).toBeTruthy();
    expect(items[1].textContent).toContain("Why do vectors span a space?");
    expect(items[1].textContent).toContain(
      "because any vector is a linear combination of them",
    );
    expect(items[1].querySelector(".lucide-check")).toBeTruthy();
  });

  it("diagnoses error types with retries and graduation", () => {
    render(
      <ObjectiveDetail
        report={report({
          errors: [
            {
              id: "err-1",
              error_type: "misconception",
              status: "graduated",
              self_attribution: "",
              retries: 2,
              created_at: 0,
            },
          ],
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Error diagnosis")).toBeInTheDocument();
    const diagnosis = screen
      .getByText("Error diagnosis")
      .parentElement?.textContent;
    expect(diagnosis).toContain("misconception");
    expect(diagnosis).toContain("2 retries");
    expect(diagnosis).toContain("cleared");
  });

  it("shows the learner's recorded explanation for a qualitative gate", () => {
    render(
      <ObjectiveDetail
        report={report({
          explanation: "A basis change is just a relabelling of axes.",
          explained: {
            summary: "Explained basis change in own words.",
            timestamp: 1_700_000_000,
          },
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Your explanation")).toBeInTheDocument();
    expect(
      screen.getByText("A basis change is just a relabelling of axes."),
    ).toBeInTheDocument();
    expect(screen.getByText("Explained")).toBeInTheDocument();
    expect(
      screen.getByText("Explained basis change in own words."),
    ).toBeInTheDocument();
  });

  it("hides the explanation row for quantitative gates", () => {
    render(
      <ObjectiveDetail
        report={report({
          gate: "quantitative",
          explanation: "A basis change is just a relabelling of axes.",
        })}
        zh={false}
      />,
    );

    expect(screen.queryByText("Your explanation")).toBeNull();
  });

  it("tracks required visual evidence and says what is still owed", () => {
    render(
      <ObjectiveDetail
        report={report({
          required_visual_tasks: ["draw-the-transformation", "sketch-eigenspace"],
          demonstrated_visual_tasks: ["draw-the-transformation"],
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Independent visual evidence")).toBeInTheDocument();
    expect(visualEvidenceRatio()).toContain("1 / 2");
    expect(
      screen.getByText(
        "Independent visual evidence is still required for this objective.",
      ),
    ).toBeInTheDocument();
  });

  it("stops asking once every visual task is demonstrated", () => {
    render(
      <ObjectiveDetail
        report={report({
          required_visual_tasks: ["draw-the-transformation"],
          demonstrated_visual_tasks: ["draw-the-transformation"],
        })}
        zh={false}
      />,
    );

    expect(visualEvidenceRatio()).toContain("1 / 1");
    expect(
      screen.queryByText(
        "Independent visual evidence is still required for this objective.",
      ),
    ).toBeNull();
  });

  it("flags assisted practice as separate from independent mastery", () => {
    render(
      <ObjectiveDetail
        report={report({
          attempts: [attempt({ independent: false })],
        })}
        zh={false}
      />,
    );

    expect(
      screen.getByText(
        "Assisted practice is recorded separately from independent mastery.",
      ),
    ).toBeInTheDocument();
  });

  it("lists retention evidence with visual context and truncation notice", () => {
    render(
      <ObjectiveDetail
        report={report({
          evidence: [
            evidence({
              quality: 0.85,
              hints_used: 1,
              visual_context: { task: "draw-the-transformation" },
            }),
            evidence({
              assessment_type: "qualitative",
              result: "partial",
              timestamp: 1_700_000_100,
            }),
          ],
          evidence_count: 25,
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Retention evidence (25)")).toBeInTheDocument();
    const first = screen.getByText(/Visual practice/);
    expect(first.textContent).toContain("Assisted");
    expect(first.textContent).toContain("85%");
    expect(
      screen.getByText("Showing the latest 20 events"),
    ).toBeInTheDocument();
  });

  it("omits the truncation notice when the count matches the page", () => {
    render(
      <ObjectiveDetail
        report={report({
          evidence: [evidence()],
        })}
        zh={false}
      />,
    );

    expect(screen.getByText("Retention evidence (1)")).toBeInTheDocument();
    expect(screen.queryByText("Showing the latest 20 events")).toBeNull();
  });

  it("explains itself when nothing has been attempted yet", () => {
    render(<ObjectiveDetail report={report()} zh={false} />);

    expect(
      screen.getByText(
        "No attempts yet. Once you work through this waypoint, its questions, your answers, and the grading evidence will appear here.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Error diagnosis")).toBeNull();
  });
});
