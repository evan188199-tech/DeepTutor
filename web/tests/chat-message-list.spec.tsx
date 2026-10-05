import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ChatMessageList } from "@/features/chat/messages/ChatMessageList";
import type { MessageRequestSnapshot } from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";
import type { OrphanedFailedTurn } from "@/lib/session-api";

initI18n("en");

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(async () => ({ ok: false, json: async () => null })),
}));
vi.mock("@/hooks/useVoiceAutoplay", () => ({
  useVoiceAutoplay: () => ({ autoplayEnabled: false }),
}));
vi.mock("@/hooks/useConnectedAgentKinds", () => ({
  useConnectedAgentKinds: () => ({}),
}));
// The body renderer drags in the reading/watching providers and the whole
// markdown pipeline; the list-level branches under test only need the text.
vi.mock("@/components/common/AssistantResponse", () => ({
  default: ({ content }: { content: string }) => (
    <div data-testid="assistant-body">{content}</div>
  ),
}));

type ListItem = React.ComponentProps<typeof ChatMessageList>["messages"][number];

const user = (content: string, extra: Partial<ListItem> = {}): ListItem => ({
  role: "user",
  content,
  ...extra,
});
const assistant = (content: string, extra: Partial<ListItem> = {}): ListItem => ({
  role: "assistant",
  content,
  ...extra,
});
const event = (
  type: string,
  content = "",
  metadata: Record<string, unknown> = {},
): StreamEvent =>
  ({ type, content, metadata, source: "spec", stage: "spec" }) as unknown as StreamEvent;

const renderList = (
  messages: ListItem[],
  props: Partial<React.ComponentProps<typeof ChatMessageList>> = {},
) =>
  render(
    <ChatMessageList
      messages={messages}
      isStreaming={false}
      onCopyAssistantMessage={vi.fn()}
      onRegenerateMessage={vi.fn()}
      {...props}
    />,
  );

it("groups turns in order and never renders system messages as bubbles", () => {
  const { container } = renderList([
    user("First question", { id: 1 }),
    assistant("First answer", { id: 2, parentMessageId: 1 }),
    { role: "system", id: 99, parentMessageId: 2, content: "quiz follow-up grounding" },
    user("Second question", { id: 3, parentMessageId: 99 }),
    assistant("Second answer", { id: 4, parentMessageId: 3 }),
  ]);
  const rows = container.querySelectorAll("[data-chat-message-role]");
  expect(rows).toHaveLength(4);
  expect([...rows].map((row) => row.getAttribute("data-chat-message-role"))).toEqual([
    "user",
    "assistant",
    "user",
    "assistant",
  ]);
  expect([...rows].map((row) => row.getAttribute("data-chat-message-id"))).toEqual([
    "1",
    "2",
    "3",
    "4",
  ]);
  expect(screen.queryByText("quiz follow-up grounding")).toBeNull();
  const bodies = screen.getAllByTestId("assistant-body");
  expect(bodies.map((body) => body.textContent)).toEqual(["First answer", "Second answer"]);
  expect(screen.getByText("Second question")).toBeVisible();
});

it("keeps the selected edit branch visible and exposes the branch navigator", () => {
  const onSwitchBranch = vi.fn();
  renderList(
    [
      user("Original question", { id: 1 }),
      user("Edited question", { id: 2 }),
      assistant("Answer to original", { id: 3, parentMessageId: 1 }),
      assistant("Answer to edit", { id: 4, parentMessageId: 2 }),
    ],
    { selectedBranches: { "null": 2 }, onSwitchBranch },
  );
  expect(screen.getByText("Edited question")).toBeVisible();
  expect(screen.getByText("Answer to edit")).toBeVisible();
  expect(screen.queryByText("Original question")).toBeNull();
  expect(screen.queryByText("Answer to original")).toBeNull();
  expect(screen.getByText("2 / 2")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Previous branch" }));
  expect(onSwitchBranch).toHaveBeenCalledWith(null, 1);
});

it("falls back to the latest sibling when no branch is selected", () => {
  renderList([
    user("Original question", { id: 1 }),
    user("Edited question", { id: 2 }),
    assistant("Answer to original", { id: 3, parentMessageId: 1 }),
    assistant("Answer to edit", { id: 4, parentMessageId: 2 }),
  ]);
  expect(screen.getByText("Edited question")).toBeVisible();
  expect(screen.getByText("Answer to edit")).toBeVisible();
  expect(screen.queryByText("Original question")).toBeNull();
});

it("renders the reading passage quote as a link back to the passage", () => {
  const snapshot: MessageRequestSnapshot = {
    content: "Explain this passage",
    enabledTools: [],
    knowledgeBases: [],
    language: "en",
    readingMaterialId: "mat-1",
    readingMaterialRevision: 7,
    readingSelection: {
      quote: "The mitochondria is the powerhouse of the cell.",
      locator: 3,
    },
  };
  renderList([user("Explain this passage", { id: 1, requestSnapshot: snapshot })]);
  const link = screen.getByRole("link", {
    name: "Go to this passage: The mitochondria is the powerhouse of the cell.",
  });
  expect(link).toBeVisible();
  expect(link.getAttribute("href")).toContain("mat-1-revision-7-locator-3");
});

it("keeps a reading quote as plain text when the passage link is unavailable", () => {
  const snapshot: MessageRequestSnapshot = {
    content: "Explain this passage",
    enabledTools: [],
    knowledgeBases: [],
    language: "en",
    readingSelection: { quote: "A quote without a material.", locator: 2 },
  };
  renderList([user("Explain this passage", { id: 1, requestSnapshot: snapshot })]);
  expect(screen.getByText("A quote without a material.")).toBeVisible();
  expect(screen.queryByRole("link", { name: /Go to this passage/ })).toBeNull();
});

it("clamps an over-long passage quote to the truncated block", () => {
  const longQuote = "surviving text ".repeat(60).trim();
  const snapshot: MessageRequestSnapshot = {
    content: "Summarize",
    enabledTools: [],
    knowledgeBases: [],
    language: "en",
    readingSelection: { quote: longQuote, locator: 1 },
  };
  renderList([user("Summarize", { id: 1, requestSnapshot: snapshot })]);
  expect(screen.getByText(longQuote)).toHaveClass("line-clamp-3");
});

it("marks a failed submission as not sent next to its bubble", () => {
  renderList([user("Never reached the server", { id: 5, failedSubmission: true })]);
  expect(screen.getByText("Not sent")).toBeVisible();
  expect(screen.getByText("Never reached the server")).toBeVisible();
});

it("does not mark an ordinary submission as unsent", () => {
  renderList([user("Delivered question", { id: 1 })]);
  expect(screen.queryByText("Not sent")).toBeNull();
});

it("renders an orphaned failed turn with retry on the trailing turn", () => {
  const onResendLastTurn = vi.fn();
  const failure: OrphanedFailedTurn = {
    turn_id: "turn-9",
    error: "Provider overloaded",
    failure_code: "upstream_error",
    retryable: true,
    finished_at: 1,
  };
  renderList([user("Summarize chapter 2", { id: 1, orphanedFailedTurn: failure })], {
    canResendLastTurn: true,
    onResendLastTurn,
  });
  const alert = screen.getByRole("alert");
  expect(alert).toHaveAttribute("data-orphaned-failed-turn", "turn-9");
  expect(alert).toHaveTextContent("Provider overloaded");
  fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
  expect(onResendLastTurn).toHaveBeenCalledTimes(1);
});

it("hides the retry affordance for a non-retryable orphaned failure", () => {
  const failure: OrphanedFailedTurn = {
    turn_id: "turn-10",
    error: "Turn interrupted by the user",
    failure_code: "cancelled",
    retryable: false,
    finished_at: 1,
  };
  renderList([user("Long task", { id: 1, orphanedFailedTurn: failure })], {
    canResendLastTurn: true,
    onResendLastTurn: vi.fn(),
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Turn interrupted by the user");
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});

it("surfaces a terminal assistant error with a regenerate retry", () => {
  const onRegenerateMessage = vi.fn();
  renderList(
    [
      user("What is gravity?", { id: 1 }),
      assistant("", {
        id: 2,
        parentMessageId: 1,
        events: [event("error", "Provider quota exceeded", { turn_terminal: true, retryable: true })],
      }),
    ],
    { onRegenerateMessage },
  );
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("Provider quota exceeded");
  fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
  expect(onRegenerateMessage).toHaveBeenCalledTimes(1);
});

it("offers resend for a failed turn that still has its request snapshot", () => {
  const onResendLastTurn = vi.fn();
  const snapshot: MessageRequestSnapshot = {
    content: "Retry me",
    enabledTools: [],
    knowledgeBases: [],
    language: "en",
  };
  renderList(
    [
      user("Retry me", { id: 1, requestSnapshot: snapshot }),
      assistant("", {
        id: 2,
        parentMessageId: 1,
        events: [event("error", "Upstream unavailable")],
      }),
    ],
    { canResendLastTurn: true, onResendLastTurn },
  );
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("Upstream unavailable");
  expect(within(alert).queryByRole("button", { name: "Retry" })).toBeNull();
  fireEvent.click(within(alert).getByRole("button", { name: "Resend" }));
  expect(onResendLastTurn).toHaveBeenCalledTimes(1);
});

it("marks a cancelled turn as stopped instead of failed", () => {
  renderList([
    user("Long task", { id: 1 }),
    assistant("Partial answer", {
      id: 2,
      parentMessageId: 1,
      events: [event("done", "", { status: "cancelled" })],
    }),
  ]);
  expect(screen.getByText("Stopped")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("prompts to retry when a turn produced no response at all", () => {
  renderList([
    user("Hello", { id: 1 }),
    assistant("", { id: 2, parentMessageId: 1 }),
  ]);
  expect(
    screen.getByText("No response was generated. Please try again."),
  ).toBeVisible();
});

it("renders a long conversation in order without dropping rows", () => {
  const turns = 40;
  const messages: ListItem[] = [];
  for (let i = 0; i < turns; i += 1) {
    messages.push(
      user(`Question ${i}`, {
        id: i * 2 + 1,
        parentMessageId: i === 0 ? null : i * 2,
      }),
    );
    messages.push(assistant(`Answer ${i}`, { id: i * 2 + 2, parentMessageId: i * 2 + 1 }));
  }
  const { container } = renderList(messages);
  const rows = container.querySelectorAll("[data-chat-message-role]");
  expect(rows).toHaveLength(turns * 2);
  expect(rows[0].getAttribute("data-chat-message-id")).toBe("1");
  expect(rows[rows.length - 1].getAttribute("data-chat-message-id")).toBe(
    String(turns * 2),
  );
  expect(screen.getByText("Question 0")).toBeVisible();
  expect(screen.getByText(`Answer ${turns - 1}`)).toBeVisible();
  expect(screen.getAllByTestId("assistant-body")).toHaveLength(turns);
});
