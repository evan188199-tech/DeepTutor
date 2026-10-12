import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import GroupRound from "@/components/partners/group/GroupRound";
import type {
  PartnerGroupMember,
  PartnerGroupMessage,
  PartnerInvocation,
} from "@/lib/partner-groups-api";
import type { Round, Seat } from "@/components/partners/group/useGroupSession";
import { initI18n } from "@/i18n/init";

initI18n("en");

vi.mock("next/dynamic", () => ({
  default: () =>
    ({ content }: { content: string }) => <span>{content}</span>,
}));

const members: PartnerGroupMember[] = [
  { partner_id: "ada", name: "Ada", description: "", running: false },
  { partner_id: "grace", name: "Grace", description: "", running: false },
  { partner_id: "linus", name: "Linus", description: "", running: false },
];

function message(
  partial: Partial<PartnerGroupMessage> & {
    event_id: string;
    author_id: string;
    author_name: string;
  },
): PartnerGroupMessage {
  return {
    turn_id: "t1",
    session_key: "s1",
    role: "partner",
    content: "",
    created_at: "2026-01-01T00:00:00Z",
    mentions: [],
    error: false,
    kind: "message",
    events: [],
    invocation_id: "",
    invocation: null,
    ...partial,
  };
}

function seat(partnerId: string, partial: Partial<Seat> = {}): Seat {
  return { partnerId, status: "done", events: [], streamed: "", ...partial };
}

function invocation(
  partial: Partial<PartnerInvocation> = {},
): PartnerInvocation {
  return {
    invocation_id: "inv1",
    group_id: "g1",
    session_key: "s1",
    parent_turn_id: "t1",
    requester_partner_id: "ada",
    requester_partner_name: "Ada",
    target_partner_id: "grace",
    target_partner_name: "Grace",
    question: "Grace, what is your take?",
    status: "pending",
    created_at: "",
    updated_at: "",
    question_event_id: "",
    reply_event_id: "",
    error: "",
    ...partial,
  };
}

function panelRound(partial: Partial<Round> = {}): Round {
  return {
    turnId: "t1",
    user: message({
      event_id: "u1",
      role: "user",
      author_id: "user",
      author_name: "You",
      content: "What about X?",
    }),
    seats: [
      seat("ada", {
        message: message({
          event_id: "a1",
          author_id: "ada",
          author_name: "Ada",
          content: "Ada says yes",
        }),
      }),
      seat("grace", {
        message: message({
          event_id: "g1",
          author_id: "grace",
          author_name: "Grace",
          content: "Grace says no",
        }),
      }),
    ],
    followup: false,
    live: false,
    ...partial,
  };
}

type RoundProps = Parameters<typeof GroupRound>[0];

function renderRound(
  overrides: Partial<RoundProps> & { round: Round },
) {
  const props: RoundProps = {
    members,
    progress: null,
    pendingActions: new Set<string>(),
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onQuote: vi.fn(),
    onOpenTrace: vi.fn(),
    onAskPeer: vi.fn(),
    onSummarize: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<GroupRound {...props} />) };
}

it("renders the user question and each seat in transcript order", () => {
  renderRound({ round: panelRound() });
  expect(screen.getByText("What about X?")).toBeInTheDocument();
  expect(screen.getByText("Ada says yes")).toBeInTheDocument();
  expect(screen.getByText("Grace says no")).toBeInTheDocument();
  expect(screen.getByText("Ada")).toBeInTheDocument();
  expect(screen.getByText("Grace")).toBeInTheDocument();
});

it("shows the live progress counter, the clash label, and hides it for panels of one", () => {
  const round = panelRound({ live: true });
  const { props, rerender } = renderRound({
    round,
    progress: { done: 1, total: 2 },
  });
  expect(screen.getByText("1 of 2 answered")).toBeInTheDocument();
  rerender(
    <GroupRound {...props} progress={{ done: 2, total: 2, clash: true }} />,
  );
  expect(screen.getByText("Clash round · 2 of 2")).toBeInTheDocument();
  rerender(<GroupRound {...props} progress={{ done: 0, total: 1 }} />);
  expect(screen.queryByText(/answered/)).not.toBeInTheDocument();
});

it("offers the summary from answered members and reports turn and partner", () => {
  const onSummarize = vi.fn();
  renderRound({ round: panelRound(), onSummarize });
  fireEvent.click(screen.getByRole("button", { name: "Summarise this round" }));
  expect(screen.getByText("Who should sum it up?")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Linus/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Ada/ }));
  expect(onSummarize).toHaveBeenCalledWith("t1", "ada");
});

it.each([
  [
    "still live",
    panelRound({
      live: true,
      seats: [
        seat("ada", {
          message: message({
            event_id: "a1",
            author_id: "ada",
            author_name: "Ada",
            content: "Ada says yes",
          }),
        }),
        seat("grace", {
          message: message({
            event_id: "g1",
            author_id: "grace",
            author_name: "Grace",
            content: "Grace says no",
          }),
        }),
      ],
    }),
  ],
  ["stopped", panelRound({ stopped: true })],
  [
    "already summarised",
    panelRound({
      seats: [
        seat("ada", {
          message: message({
            event_id: "a1",
            author_id: "ada",
            author_name: "Ada",
            content: "Ada says yes",
          }),
        }),
        seat("grace", {
          message: message({
            event_id: "g1",
            author_id: "grace",
            author_name: "Grace",
            content: "Grace says no",
          }),
        }),
        seat("linus", {
          message: message({
            event_id: "s1",
            author_id: "linus",
            author_name: "Linus",
            kind: "round_summary",
            content: "We agree",
          }),
        }),
      ],
    }),
  ],
  [
    "left with a single answer",
    panelRound({
      seats: [
        seat("ada", {
          message: message({
            event_id: "a1",
            author_id: "ada",
            author_name: "Ada",
            content: "Ada says yes",
          }),
        }),
      ],
    }),
  ],
])("hides the summary action while the round is %s", (_, round) => {
  renderRound({ round });
  expect(
    screen.queryByRole("button", { name: "Summarise this round" }),
  ).not.toBeInTheDocument();
});

it("marks a stopped round in the transcript", () => {
  renderRound({ round: panelRound({ stopped: true }) });
  expect(screen.getByText("You stopped this round")).toBeInTheDocument();
});

it("shows the seat error text, falling back to a generic line", () => {
  const failing = panelRound({
    seats: [
      seat("ada", {
        status: "error",
        message: message({
          event_id: "a1",
          author_id: "ada",
          author_name: "Ada",
          content: "Provider unavailable",
          error: true,
        }),
      }),
      seat("grace", {
        status: "error",
        message: message({
          event_id: "g1",
          author_id: "grace",
          author_name: "Grace",
          content: "",
          error: true,
        }),
      }),
    ],
  });
  renderRound({ round: failing });
  expect(screen.getByText("Provider unavailable")).toBeInTheDocument();
  expect(screen.getByText("This Partner could not answer.")).toBeInTheDocument();
});

it("renders a pending invocation card wired to approve and reject", () => {
  const pending = invocation({ status: "pending" });
  const round = panelRound({
    seats: [
      seat("ada", {
        message: message({
          event_id: "a1",
          author_id: "ada",
          author_name: "Ada",
          content: "Ada says yes",
        }),
      }),
      seat("grace", {
        message: message({
          event_id: "g1",
          author_id: "grace",
          author_name: "Grace",
          content: "",
          invocation: pending,
        }),
      }),
    ],
  });
  const onApprove = vi.fn();
  const onReject = vi.fn();
  const { props, rerender } = renderRound({ round, onApprove, onReject });
  expect(screen.getByText("Grace, what is your take?")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Let them discuss" }));
  expect(onApprove).toHaveBeenCalledWith("inv1");
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(onReject).toHaveBeenCalledWith("inv1");
  rerender(
    <GroupRound {...props} pendingActions={new Set(["inv1"])} />,
  );
  expect(screen.getByRole("button", { name: "Let them discuss" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Not now" })).toBeDisabled();
  rerender(
    <GroupRound
      {...props}
      pendingActions={new Set()}
      round={panelRound({
        seats: [
          seat("grace", {
            message: message({
              event_id: "g1",
              author_id: "grace",
              author_name: "Grace",
              content: "",
              invocation: invocation({ status: "completed" }),
            }),
          }),
          seat("ada", {
            message: message({
              event_id: "a1",
              author_id: "ada",
              author_name: "Ada",
              content: "Ada says yes",
            }),
          }),
        ],
      })}
    />,
  );
  expect(
    screen.queryByText("Grace, what is your take?"),
  ).not.toBeInTheDocument();
});

it("titles a follow-up aside by who asked whom and collapses it", () => {
  const followup: Round = {
    turnId: "t2",
    seats: [
      seat("ada", {
        message: message({
          event_id: "q1",
          turn_id: "t2",
          author_id: "ada",
          author_name: "Ada",
          kind: "invocation_question",
          content: "Grace, thoughts on X?",
          invocation: invocation({
            status: "completed",
            parent_turn_id: "t1",
          }),
        }),
      }),
      seat("grace", {
        message: message({
          event_id: "r1",
          turn_id: "t2",
          author_id: "grace",
          author_name: "Grace",
          kind: "invocation_reply",
          content: "Grace answers here",
        }),
      }),
    ],
    followup: true,
    live: false,
  };
  renderRound({ round: followup });
  expect(screen.getByText("Ada asked Grace")).toBeInTheDocument();
  expect(screen.getByText("Grace answers here")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Ada asked Grace/ }));
  expect(screen.queryByText("Grace answers here")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Ada asked Grace/ }));
  expect(screen.getByText("Grace answers here")).toBeInTheDocument();
});

it("falls back to a generic follow-up title when no names are known", () => {
  const followup: Round = {
    turnId: "t3",
    seats: [
      seat("ada", {
        message: message({
          event_id: "q2",
          turn_id: "t3",
          author_id: "ada",
          author_name: "",
          kind: "invocation_question",
          content: "Anonymous ask",
        }),
      }),
    ],
    followup: true,
    live: false,
  };
  renderRound({ round: followup });
  expect(screen.getByText("Follow-up discussion")).toBeInTheDocument();
});

it("asks a peer from a finished seat and quotes another speaker", () => {
  const onAskPeer = vi.fn();
  const onQuote = vi.fn();
  renderRound({ round: panelRound(), onAskPeer, onQuote });
  const askButtons = screen.getAllByRole("button", { name: "Ask a peer" });
  expect(askButtons).toHaveLength(2);
  fireEvent.click(askButtons[0]);
  expect(screen.getByText("Who should respond to Ada?")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Grace/ }));
  expect(onAskPeer).toHaveBeenCalledWith("ada", "grace", "Ada says yes");
  const quoteButtons = screen.getAllByRole("button", { name: "Follow up" });
  expect(quoteButtons).toHaveLength(2);
  fireEvent.click(quoteButtons[1]);
  expect(onQuote).toHaveBeenCalledWith({
    name: "Grace",
    content: "Grace says no",
  });
});
