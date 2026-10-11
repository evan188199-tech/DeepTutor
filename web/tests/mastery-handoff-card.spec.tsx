import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MasteryHandoffCards } from "@/components/chat/home/MasteryHandoffCard";
import {
  masteryHandoffHref,
  type MasteryHandoffPayload,
} from "@/lib/mastery-handoff";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  setPendingPrompt: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/lib/pending-prompt", () => ({
  setPendingPrompt: mocks.setPendingPrompt,
}));

const resumePayload: MasteryHandoffPayload = {
  kind: "open",
  path_id: "stats_101",
  path_name: "Intro Statistics",
  emoji: "📊",
  session_id: "sess_7",
  session_title: "Sampling distributions",
  session_messages: 12,
  session_updated_at: 1_760_000_000,
  session_awaiting: true,
  session_running: false,
  module_id: "m1",
  module_name: "Lesson 1 · Descriptive stats",
  opening_message: "Take me back through lesson 1 and quiz me",
  reason: "Three objectives there are due for review",
  due_reviews: 3,
  mastered: 9,
  objectives: 12,
};

const newPayload: MasteryHandoffPayload = {
  kind: "new",
  path_id: "stats_101",
  path_name: "Intro Statistics",
  emoji: "",
  session_id: "",
  session_title: "",
  session_messages: 0,
  session_updated_at: 0,
  session_awaiting: false,
  session_running: false,
  module_id: "",
  module_name: "",
  opening_message: "Begin with the basics",
  reason: "",
  due_reviews: 0,
  mastered: 0,
  objectives: 8,
};

describe("MasteryHandoffCards", () => {
  beforeEach(() => {
    mocks.push.mockClear();
    mocks.setPendingPrompt.mockClear();
  });

  it("renders nothing for an empty handoff list", () => {
    const { container } = render(<MasteryHandoffCards handoffs={[]} />);
    expect(container.textContent).toBe("");
  });

  it("renders the resume card with reason headline, stats and waiting marker", () => {
    render(<MasteryHandoffCards handoffs={[resumePayload]} />);

    expect(
      screen.getByText("Three objectives there are due for review"),
    ).toBeTruthy();
    expect(screen.getByText("Intro Statistics")).toBeTruthy();
    expect(screen.getByText("Lesson 1 · Descriptive stats")).toBeTruthy();
    expect(screen.getByText("9/12 mastered · 3 due for review")).toBeTruthy();

    const take = screen.getByRole("button", { name: "Continue this session" });
    expect(take).toBeTruthy();
    expect(screen.getByText("Sampling distributions")).toBeTruthy();
    expect(screen.getByText("a question is waiting")).toBeTruthy();
    expect(screen.queryByText("The path keeps all of its progress")).toBeNull();
  });

  it("renders the new-path card with fresh-start copy and no session row", () => {
    render(<MasteryHandoffCards handoffs={[newPayload]} />);

    expect(
      screen.getByText("Start a fresh session on this path"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Begin a session" })).toBeTruthy();
    expect(screen.getByText("The path keeps all of its progress")).toBeTruthy();
    expect(screen.queryByText("a question is waiting")).toBeNull();
    expect(screen.queryByText("Continue this session")).toBeNull();
    expect(
      (screen.getByRole("textbox") as HTMLTextAreaElement).value,
    ).toBe("Begin with the basics");
  });

  it("omits the stats row when the path has no objectives", () => {
    render(
      <MasteryHandoffCards
        handoffs={[{ ...newPayload, objectives: 0, mastered: 0 }]}
      />,
    );

    expect(screen.queryByText(/mastered/)).toBeNull();
    expect(screen.queryByText(/due for review/)).toBeNull();
  });

  it("shows the session title without the waiting marker while running", () => {
    render(
      <MasteryHandoffCards
        handoffs={[{ ...resumePayload, session_awaiting: false }]}
      />,
    );

    expect(screen.getByText("Sampling distributions")).toBeTruthy();
    expect(screen.queryByText("a question is waiting")).toBeNull();
  });

  it("stores the edited opening scoped to the mastery path and navigates", () => {
    render(<MasteryHandoffCards handoffs={[resumePayload]} />);

    const opening = screen.getByRole("textbox");
    expect((opening as HTMLTextAreaElement).value).toBe(
      "Take me back through lesson 1 and quiz me",
    );
    fireEvent.change(opening, { target: { value: "  Custom opening line  " } });

    fireEvent.click(screen.getByRole("button", { name: "Continue this session" }));

    expect(mocks.setPendingPrompt).toHaveBeenCalledTimes(1);
    expect(mocks.setPendingPrompt).toHaveBeenCalledWith(
      "Custom opening line",
      "mastery_path",
    );
    expect(mocks.push).toHaveBeenCalledTimes(1);
    expect(mocks.push).toHaveBeenCalledWith(masteryHandoffHref(resumePayload));
  });

  it("navigates without storing a prompt when the opening is blank", () => {
    render(<MasteryHandoffCards handoffs={[resumePayload]} />);

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue this session" }));

    expect(mocks.setPendingPrompt).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledTimes(1);
    expect(mocks.push).toHaveBeenCalledWith(masteryHandoffHref(resumePayload));
  });

  it("renders one card per handoff", () => {
    render(
      <MasteryHandoffCards
        handoffs={[
          resumePayload,
          { ...newPayload, reason: "Warm-up is due today" },
        ]}
      />,
    );

    expect(
      screen.getByText("Three objectives there are due for review"),
    ).toBeTruthy();
    expect(screen.getByText("Warm-up is due today")).toBeTruthy();
    expect(screen.getAllByRole("button").length).toBe(2);
  });
});
