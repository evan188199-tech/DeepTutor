import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ContextBudgetChip, {
  type ContextBudget,
} from "@/components/chat/home/ContextBudgetChip";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.defaultValue === "string" ? opts.defaultValue : key,
  }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const budget = (over: Partial<ContextBudget> = {}): ContextBudget => ({
  window: 1000,
  used_tokens: 300,
  free_tokens: 700,
  segments: [{ key: "messages", tokens: 300 }],
  ...over,
});

const chip = () =>
  screen.getByRole("button", { name: "contextBudget.chipAria" });

const openPopover = () => {
  fireEvent.click(chip());
  return screen.getByRole("dialog", { name: "contextBudget.title" });
};

const RING_CIRCUMFERENCE = 2 * Math.PI * 6.5;

const ringOffset = (container: HTMLElement) => {
  const circles = container.querySelectorAll("circle");
  return parseFloat(
    circles[circles.length - 1].getAttribute("stroke-dashoffset") ?? "NaN",
  );
};

const FALLBACK_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#14b8a6",
  "#f59e0b",
  "#a855f7",
  "#64748b",
];

const hexToRgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
};

it("shows the rounded used share and stays quiet below the warning threshold", () => {
  const { container } = render(<ContextBudgetChip budget={budget()} />);
  expect(chip()).toHaveTextContent("30%");
  expect(chip()).toHaveAttribute("aria-expanded", "false");
  expect(chip()).not.toHaveClass("text-amber-500");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  // The ring is 30% full: offset leaves 70% of the circumference.
  expect(ringOffset(container)).toBeCloseTo(RING_CIRCUMFERENCE * 0.7, 5);
});

it("lists every segment with compact tokens and per-segment shares when opened", () => {
  render(
    <ContextBudgetChip
      budget={budget({
        window: 2_000_000,
        used_tokens: 1_500_000,
        free_tokens: 500_000,
        model: "gpt-x",
        segments: [
          { key: "messages", tokens: 1_500_000 },
          { key: "sources", tokens: 895_300 },
          { key: "skills", tokens: 999 },
        ],
      })}
    />,
  );
  const dialog = openPopover();
  expect(chip()).toHaveAttribute("aria-expanded", "true");
  expect(within(dialog).getByText("gpt-x")).toBeInTheDocument();
  // Compact formatting keeps one decimal and a lowercase unit.
  expect(within(dialog).getByText("1.5M")).toBeInTheDocument();
  expect(within(dialog).getByText("895.3k")).toBeInTheDocument();
  expect(within(dialog).getByText("999")).toBeInTheDocument();
  expect(within(dialog).getByText("500k")).toBeInTheDocument();
  // Shares: 75% exactly, 44.765% rounds to 45%, a sliver reads as "<1%".
  expect(within(dialog).getByText("75%")).toBeInTheDocument();
  expect(within(dialog).getByText("45%")).toBeInTheDocument();
  expect(within(dialog).getByText("<1%")).toBeInTheDocument();
  expect(within(dialog).getByText("25%")).toBeInTheDocument();
});

it("drops segment rows without a usable key or a positive token count", () => {
  render(
    <ContextBudgetChip
      budget={budget({
        segments: [
          { key: "", tokens: 100 },
          { key: "messages", tokens: 0 },
          { key: "mcp_tools", tokens: Number.NaN },
          { key: "memory", tokens: 300 },
        ],
      })}
    />,
  );
  const dialog = openPopover();
  expect(within(dialog).getByText("memory")).toBeInTheDocument();
  expect(within(dialog).queryByText("messages")).not.toBeInTheDocument();
  expect(within(dialog).queryByText("mcp tools")).not.toBeInTheDocument();
});

it("clamps impossible numbers instead of printing NaN", () => {
  // A NaN used count clamps to zero: the caller's typeof guard lets NaN in.
  let view = render(
    <ContextBudgetChip
      budget={budget({ used_tokens: Number.NaN, free_tokens: Number.NaN })}
    />,
  );
  expect(chip()).toHaveTextContent("0%");
  // Nothing consumed: the ring stays empty (full offset).
  expect(ringOffset(view.container)).toBeCloseTo(RING_CIRCUMFERENCE, 5);
  view.unmount();

  // A zero window would divide by zero; fall back to the measured usage.
  view = render(
    <ContextBudgetChip
      budget={{ window: 0, used_tokens: 500, free_tokens: 0, segments: [] }}
    />,
  );
  expect(chip()).toHaveTextContent("100%");
  view.unmount();

  // Over-window usage: the label may exceed 100% but the ring clamps at full.
  view = render(
    <ContextBudgetChip
      budget={{
        window: 1000,
        used_tokens: 2000,
        free_tokens: 0,
        segments: [{ key: "messages", tokens: 2000 }],
      }}
    />,
  );
  expect(chip()).toHaveTextContent("200%");
  expect(ringOffset(view.container)).toBeCloseTo(0, 5);
  view.unmount();
});

it("turns amber only once usage reaches the 90% threshold", () => {
  // 89.9% rounds up to "90%" on the label, but the threshold reads the raw
  // share — the chip only warms when genuinely at 90%.
  let view = render(
    <ContextBudgetChip budget={budget({ used_tokens: 899 })} />,
  );
  expect(chip()).toHaveTextContent("90%");
  expect(chip()).not.toHaveClass("text-amber-500");
  view.unmount();

  render(<ContextBudgetChip budget={budget({ used_tokens: 900 })} />);
  expect(chip()).toHaveClass("text-amber-500");
});

it("renders estimate and counter footnotes only when flagged", () => {
  render(<ContextBudgetChip budget={budget()} />);
  const dialog = openPopover();
  expect(
    within(dialog).queryByText("contextBudget.estimated"),
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByText("contextBudget.note.estimatedWindow"),
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByText("contextBudget.note.heuristicCounter"),
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByText("contextBudget.note.deferredTools"),
  ).not.toBeInTheDocument();
  cleanup();

  render(
    <ContextBudgetChip
      budget={budget({
        window_estimated: true,
        counter: "heuristic",
        deferred_tool_count: 3,
      })}
    />,
  );
  const noted = openPopover();
  expect(
    within(noted).getByText("contextBudget.estimated"),
  ).toBeInTheDocument();
  expect(
    within(noted).getByText("contextBudget.note.estimatedWindow"),
  ).toBeInTheDocument();
  expect(
    within(noted).getByText("contextBudget.note.heuristicCounter"),
  ).toBeInTheDocument();
  expect(
    within(noted).getByText("contextBudget.note.deferredTools"),
  ).toBeInTheDocument();
});

it("toggles from the chip and closes on Escape and outside press", () => {
  render(
    <>
      <button>Elsewhere</button>
      <ContextBudgetChip budget={budget()} />
    </>,
  );
  fireEvent.click(chip());
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  fireEvent.click(chip());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  fireEvent.click(chip());
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  fireEvent.click(chip());
  fireEvent.mouseDown(screen.getByText("Elsewhere"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("gives unknown segment keys a stable fallback colour", () => {
  const key = "brand_new_segment";
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  const { container } = render(
    <ContextBudgetChip
      budget={budget({
        segments: [
          { key, tokens: 300 },
          { key: "messages", tokens: 100 },
        ],
      })}
    />,
  );
  openPopover();
  // Two segment swatches plus the bordered free-space swatch.
  const swatches = container.querySelectorAll<HTMLElement>(
    'span[class*="rounded-[2px]"]',
  );
  expect(swatches).toHaveLength(3);
  expect(swatches[0].style.backgroundColor).toBe(
    hexToRgb(FALLBACK_COLORS[hash % FALLBACK_COLORS.length]),
  );
  // Known keys keep their palette entry.
  expect(swatches[1].style.backgroundColor).toBe(hexToRgb("#6366f1"));
});
