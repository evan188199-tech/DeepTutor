import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import type { MasteryHandoffPayload } from "@/lib/mastery-handoff";
import { MasteryHandoffCards } from "@/components/chat/home/MasteryHandoffCard";

initI18n("en");

const harness = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: harness.push }),
}));

function payload(
  overrides: Partial<MasteryHandoffPayload> = {},
): MasteryHandoffPayload {
  return {
    kind: "open",
    path_id: "limits-calculus",
    path_name: "Calculus Limits",
    emoji: "∫",
    session_id: "sess-1",
    session_title: "Limits review",
    session_messages: 4,
    session_updated_at: 0,
    session_awaiting: false,
    session_running: false,
    module_id: "mod-1",
    module_name: "Lesson 1",
    opening_message: "Let's review lesson 1",
    reason: "Finish lesson 1",
    due_reviews: 3,
    mastered: 9,
    objectives: 12,
    ...overrides,
  };
}

function mountCards(handoffs: MasteryHandoffPayload[]) {
  return render(<MasteryHandoffCards handoffs={handoffs} />);
}

const PENDING_PROMPT_KEY = "deeptutor.pendingPrompt.mastery_path";

describe("MasteryHandoffCard", () => {
  beforeEach(() => {
    harness.push.mockClear();
    sessionStorage.clear();
  });

  it("renders the reason headline, destination, lesson chip and progress figures", () => {
    const { container } = mountCards([payload()]);

    expect(screen.getByText("Finish lesson 1")).toBeTruthy();
    expect(screen.getByText("Calculus Limits")).toBeTruthy();
    expect(screen.getByText("Lesson 1")).toBeTruthy();
    expect(screen.getByText("9/12 mastered · 3 due for review")).toBeTruthy();
    const bar = container.querySelector<HTMLSpanElement>(
      "span[aria-hidden] > span[style]",
    );
    expect(bar?.style.width).toBe("75%");
  });

  it("falls back to the resume headline and the untitled session label", () => {
    mountCards([payload({ reason: "", session_title: "" })]);

    expect(
      screen.getByText("Pick this back up where you left it"),
    ).toBeTruthy();
    expect(screen.getByText("Untitled session")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Continue this session" }),
    ).toBeTruthy();
  });

  it("offers a fresh session for kind new without any session row", () => {
    mountCards([
      payload({
        kind: "new",
        session_id: "",
        session_title: "",
        opening_message: "",
        reason: "",
      }),
    ]);

    expect(
      screen.getByText("Start a fresh session on this path"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Begin a session" })).toBeTruthy();
    expect(screen.getByText("The path keeps all of its progress")).toBeTruthy();
    expect(screen.queryByText("Untitled session")).toBeNull();
  });

  it("flags a waiting question in the resumed session", () => {
    mountCards([payload({ session_awaiting: true, session_updated_at: 1000 })]);

    expect(screen.getByText("Limits review")).toBeTruthy();
    expect(screen.getByText("a question is waiting")).toBeTruthy();
  });

  it("shows the session's relative age instead of the waiting flag", () => {
    const now = new Date("2026-10-12T12:00:00Z");
    vi.useFakeTimers({ toFake: ["Date"], now });
    try {
      mountCards([
        payload({
          session_updated_at: Math.floor(now.getTime() / 1000) - 3600,
        }),
      ]);
      expect(screen.getByText(/hour ago/)).toBeTruthy();
      expect(screen.queryByText("a question is waiting")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("drops optional decoration when the payload is degenerate", () => {
    const { container } = mountCards([
      payload({
        path_name: "",
        module_name: "",
        mastered: 0,
        objectives: 0,
        due_reviews: 0,
        opening_message: "",
      }),
    ]);

    expect(screen.getByText("Mastery Path")).toBeTruthy();
    expect(screen.queryByText("Lesson 1")).toBeNull();
    expect(screen.queryByText(/mastered/)).toBeNull();
    expect(
      container.querySelector("span[aria-hidden] > span[style]"),
    ).toBeNull();
  });

  it("stashes the edited opening draft scoped to mastery and navigates", () => {
    mountCards([payload()]);

    const draft = screen.getByLabelText("Opens with");
    expect(draft).toHaveValue("Let's review lesson 1");
    fireEvent.change(draft, { target: { value: "Start with epsilon-delta" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Continue this session" }),
    );

    expect(sessionStorage.getItem(PENDING_PROMPT_KEY)).toBe(
      "Start with epsilon-delta",
    );
    expect(harness.push).toHaveBeenCalledTimes(1);
    expect(harness.push).toHaveBeenCalledWith(
      "/learning/mastery/limits-calculus/sessions/sess-1",
    );
  });

  it("navigates without stashing when the draft is blank", () => {
    mountCards([payload({ opening_message: "   " })]);

    fireEvent.click(
      screen.getByRole("button", { name: "Continue this session" }),
    );

    expect(sessionStorage.getItem(PENDING_PROMPT_KEY)).toBeNull();
    expect(harness.push).toHaveBeenCalledTimes(1);
  });

  it("hides the opening box entirely when there is no opening message", () => {
    mountCards([payload({ opening_message: "" })]);

    expect(screen.queryByText("Opens with")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("percent-encodes hand-off ids into the session routes", () => {
    mountCards([payload({ path_id: "calc/ii", session_id: "s 1" })]);
    fireEvent.click(
      screen.getByRole("button", { name: "Continue this session" }),
    );
    expect(harness.push).toHaveBeenCalledWith(
      "/learning/mastery/calc%2Fii/sessions/s%201",
    );

    harness.push.mockClear();
    mountCards([
      payload({ kind: "new", path_id: "calc/ii", session_id: "" }),
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Begin a session" }));
    expect(harness.push).toHaveBeenCalledWith(
      "/learning/mastery/calc%2Fii/sessions",
    );
  });

  it("renders one card per handoff and nothing for an empty list", () => {
    const empty = mountCards([]);
    expect(empty.container.firstChild).toBeNull();
    empty.unmount();

    mountCards([
      payload({ reason: "Finish lesson 1" }),
      payload({
        kind: "new",
        reason: "Start linear maps",
        path_id: "linear-maps",
        session_id: "",
      }),
    ]);
    expect(screen.getByText("Finish lesson 1")).toBeTruthy();
    expect(screen.getByText("Start linear maps")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Continue this session" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Begin a session" })).toBeTruthy();
  });
});
