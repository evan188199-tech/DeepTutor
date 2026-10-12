import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import GroupSidePanel from "@/components/partners/group/GroupSidePanel";
import type { PartnerGroupMember, WhiteboardEntry } from "@/lib/partner-groups-api";
import type { Round, Seat } from "@/components/partners/group/useGroupSession";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";

initI18n("en");

const activity = vi.hoisted(() => ({
  instances: [] as Array<Record<string, unknown>>,
}));

vi.mock("@/features/chat/trace", () => ({
  AssistantActivity: (props: Record<string, unknown>) => {
    activity.instances.push(props);
    const content = props.content as string;
    return <div data-testid="activity">{content}</div>;
  },
}));

const members: PartnerGroupMember[] = [
  { partner_id: "ada", name: "Ada", description: "", running: false },
  { partner_id: "grace", name: "Grace", description: "", running: false },
  { partner_id: "linus", name: "Linus", description: "", running: false },
];


function seat(partnerId: string, partial: Partial<Seat> = {}): Seat {
  return { partnerId, status: "done", events: [], streamed: "", ...partial };
}

function round(partial: Partial<Round> = {}): Round {
  return {
    turnId: "t1",
    seats: [],
    followup: false,
    live: false,
    ...partial,
  };
}

function entry(partial: Partial<WhiteboardEntry> = {}): WhiteboardEntry {
  return {
    entry_id: "e1",
    turn_id: "t1",
    session_key: "s1",
    author_id: "ada",
    author_name: "Ada",
    content: "Shared note",
    mentions: [],
    created_at: "",
    ...partial,
  };
}

type PanelProps = Parameters<typeof GroupSidePanel>[0];

function renderPanel(overrides: Partial<PanelProps> = {}) {
  const props: PanelProps = {
    open: true,
    tab: "reasoning",
    focus: null,
    rounds: [],
    members,
    entries: [],
    onTabChange: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<GroupSidePanel {...props} />) };
}

beforeEach(() => {
  activity.instances.length = 0;
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
});

it("renders nothing while closed", () => {
  const { container } = renderPanel({ open: false });
  expect(container.querySelector("[data-group-panel]")).toBeNull();
});

it("switches tabs and closes from the header", () => {
  const onTabChange = vi.fn();
  const onClose = vi.fn();
  renderPanel({ onTabChange, onClose });
  fireEvent.click(screen.getByRole("button", { name: "Shared context" }));
  expect(onTabChange).toHaveBeenCalledWith("context");
  fireEvent.click(screen.getByRole("button", { name: "Reasoning" }));
  expect(onTabChange).toHaveBeenCalledWith("reasoning");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("lists only traced seats, highlights and scrolls to the focused one", () => {
  const rounds = [
    round({
      seats: [
        seat("ada", {
          events: [{ type: "content", content: "tool run" } as StreamEvent],
          message: {
            event_id: "a1",
            turn_id: "t1",
            session_key: "s1",
            role: "partner",
            content: "Ada finished",
            author_id: "ada",
            author_name: "Ada",
            created_at: "",
            mentions: [],
            error: false,
            kind: "message",
            events: [],
            invocation_id: "",
            invocation: null,
          },
        }),
        seat("grace", { status: "waiting" }),
        seat("linus", { status: "waiting" }),
      ],
    }),
    round({
      turnId: "t2",
      followup: true,
      seats: [
        seat("grace", {
          status: "working",
          streamed: "Grace is streaming",
        }),
      ],
    }),
  ];
  const { container } = renderPanel({
    rounds,
    focus: { turnId: "t1", partnerId: "ada" },
  });
  expect(screen.getByText("Ada")).toBeInTheDocument();
  expect(screen.getByText("Grace")).toBeInTheDocument();
  expect(screen.queryByText(/Linus/)).not.toBeInTheDocument();
  const card = container.querySelector('[data-trace="t1:ada"]');
  expect(card).not.toBeNull();
  expect(card).toHaveClass("border-[var(--ring)]");
  const scrollTo = HTMLElement.prototype.scrollTo as ReturnType<typeof vi.fn>;
  expect(scrollTo).toHaveBeenCalled();
  expect(activity.instances.at(-1)).toMatchObject({
    content: "Grace is streaming",
    isStreaming: true,
    agentName: "Grace",
  });
});

it("shows the empty reasoning state when no seat has a trace", () => {
  renderPanel({
    rounds: [round({ seats: [seat("ada", { status: "done" })] })],
  });
  expect(screen.getByText("No reasoning to show yet")).toBeInTheDocument();
});

it("renders shared context entries, or its empty state", () => {
  const { props, rerender } = renderPanel({ tab: "context" });
  expect(screen.getByText("Nothing shared yet")).toBeInTheDocument();
  rerender(
    <GroupSidePanel
      {...props}
      entries={[
        entry({ entry_id: "e1", content: "First note" }),
        entry({
          entry_id: "e2",
          author_id: "grace",
          author_name: "Grace",
          content: "Second note",
        }),
      ]}
    />,
  );
  expect(
    screen.getByText("Visible to every Partner in this group"),
  ).toBeInTheDocument();
  expect(screen.getByText("First note")).toBeInTheDocument();
  expect(screen.getByText("Second note")).toBeInTheDocument();
});

it("labels follow-up and summary seats in the trace list", () => {
  const message = (kind: string, author: string, content: string) => ({
    event_id: `${author}-1`,
    turn_id: "t1",
    session_key: "s1",
    role: "partner" as const,
    content,
    author_id: author,
    author_name: author === "ada" ? "Ada" : "Grace",
    created_at: "",
    mentions: [],
    error: false,
    kind,
    events: [],
    invocation_id: "",
    invocation: null,
  });
  renderPanel({
    rounds: [
      round({
        seats: [
          seat("ada", {
            events: [{ type: "content", content: "sum" } as StreamEvent],
            message: message("round_summary", "ada", "In summary"),
          }),
        ],
      }),
      round({
        turnId: "t2",
        followup: true,
        seats: [
          seat("grace", {
            events: [{ type: "content", content: "reply" } as StreamEvent],
            message: message("invocation_reply", "grace", "My reply"),
          }),
        ],
      }),
    ],
  });
  expect(screen.getByText("Summary")).toBeInTheDocument();
  expect(screen.getByText("Follow-up")).toBeInTheDocument();
  expect(screen.getByText("In summary")).toBeInTheDocument();
  expect(screen.getByText("My reply")).toBeInTheDocument();
  expect(activity.instances[0]).toMatchObject({
    content: "In summary",
    isStreaming: false,
    agentName: "Ada",
  });
});
