import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import GroupComposer from "@/components/partners/group/GroupComposer";
import type { PartnerGroupMember } from "@/lib/partner-groups-api";
import { initI18n } from "@/i18n/init";

initI18n("en");

const members: PartnerGroupMember[] = [
  { partner_id: "ada", name: "Ada", description: "", running: false },
  { partner_id: "grace", name: "Grace", description: "", running: false },
];

const placeholder = "Message the group · type @ to choose Partners";

function renderComposer(
  overrides: Partial<Parameters<typeof GroupComposer>[0]> = {},
) {
  const props = {
    members,
    running: false,
    connected: true,
    quote: null,
    onClearQuote: vi.fn(),
    onSend: vi.fn(() => true),
    onCancel: vi.fn(),
    ...overrides,
  };
  return render(<GroupComposer {...props} />);
}

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", ((callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  }) as typeof requestAnimationFrame);
});

it("submits a trimmed draft on Enter and clears the input", () => {
  const onSend = vi.fn(() => true);
  renderComposer({ onSend });
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "  Hello there  " } });
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(onSend).toHaveBeenCalledWith("Hello there", null);
  expect(box).toHaveValue("");
});

it("keeps the send control locked and ignores Enter while disconnected", () => {
  const onSend = vi.fn(() => true);
  renderComposer({ connected: false, onSend });
  const box = screen.getByPlaceholderText(placeholder);
  expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  fireEvent.change(box, { target: { value: "Hello" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).not.toHaveBeenCalled();
});

it("keeps the draft and the quote when onSend refuses it", () => {
  const onSend = vi.fn(() => false);
  const onClearQuote = vi.fn();
  renderComposer({
    onSend,
    onClearQuote,
    quote: { name: "Ada", content: "Original point" },
  });
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "Reply" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(box).toHaveValue("Reply");
  expect(onClearQuote).not.toHaveBeenCalled();
});

it("prepends a quote as markdown on send and drops it after clearing", () => {
  const onSend = vi.fn(() => true);
  const onClearQuote = vi.fn();
  const quote = { name: "Ada", content: "line one\nline two" };
  const { rerender } = renderComposer({ onSend, onClearQuote, quote });
  expect(screen.getByText("Following up on Ada")).toBeInTheDocument();
  expect(screen.getByText(/line one/)).toBeInTheDocument();
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "Reply" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledWith("> Ada: line one line two\n\nReply", null);
  expect(onClearQuote).toHaveBeenCalledTimes(1);
  rerender(
    <GroupComposer
      members={members}
      running={false}
      connected
      quote={null}
      onClearQuote={onClearQuote}
      onSend={onSend}
      onCancel={vi.fn()}
    />,
  );
  expect(screen.queryByText("Following up on Ada")).not.toBeInTheDocument();
});

it("clears the quote directly from its close button", () => {
  const onClearQuote = vi.fn();
  renderComposer({ onClearQuote, quote: { name: "Ada", content: "Quoted" } });
  const clear = screen
    .getAllByRole("button")
    .find((button) => !button.getAttribute("aria-label"));
  expect(clear).toBeDefined();
  fireEvent.click(clear!);
  expect(onClearQuote).toHaveBeenCalledTimes(1);
});

it("offers mention suggestions and completes one with the keyboard", () => {
  const onSend = vi.fn(() => true);
  renderComposer({ onSend });
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "@" } });
  expect(screen.getByRole("button", { name: /Ada/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Grace/ })).toBeInTheDocument();
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(box).toHaveValue("@Grace ");
  expect(screen.getByText("Talking to Grace")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Grace/ }),
  ).not.toBeInTheDocument();
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledWith("@Grace", ["grace"]);
});

it("hides the suggestion list on Escape so Enter submits the raw draft", () => {
  const onSend = vi.fn(() => true);
  renderComposer({ onSend });
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "@" } });
  expect(screen.getByRole("button", { name: /Grace/ })).toBeInTheDocument();
  fireEvent.keyDown(box, { key: "Escape" });
  expect(
    screen.queryByRole("button", { name: /Grace/ }),
  ).not.toBeInTheDocument();
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledWith("@", null);
});

it("surfaces unknown tokens and sends the everyone list for @all", () => {
  const onSend = vi.fn(() => true);
  const { rerender } = renderComposer({ onSend });
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "@nobody hello" } });
  expect(screen.getByText("Unrecognized: @nobody")).toBeInTheDocument();
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenLastCalledWith("@nobody hello", null);
  rerender(
    <GroupComposer
      members={members}
      running={false}
      connected
      quote={null}
      onClearQuote={vi.fn()}
      onSend={onSend}
      onCancel={vi.fn()}
    />,
  );
  fireEvent.change(box, { target: { value: "@all hello" } });
  expect(
    screen.getByText("No mention · everyone will answer"),
  ).toBeInTheDocument();
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenLastCalledWith("@all hello", []);
});

it("swaps Send for Stop while a round runs and keeps the textarea usable", () => {
  const onCancel = vi.fn();
  renderComposer({ running: true, onCancel });
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "next question" } });
  expect(box).toHaveValue("next question");
});

it("reports draft presence to onDraftChange around a send", () => {
  const onDraftChange = vi.fn();
  renderComposer({ onDraftChange });
  expect(onDraftChange).toHaveBeenNthCalledWith(1, false);
  const box = screen.getByPlaceholderText(placeholder);
  fireEvent.change(box, { target: { value: "draft" } });
  expect(onDraftChange).toHaveBeenLastCalledWith(true);
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onDraftChange).toHaveBeenLastCalledWith(false);
});
