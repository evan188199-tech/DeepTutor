import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import MemoryL1Workbench from "@/components/memory/MemoryL1Workbench";

interface CapturedL1ViewProps {
  surface: string;
  focusRef: string | null;
  compact?: boolean;
  onSurfaceChange: (s: string) => void;
  onClearFocus: () => void;
  onToast: (msg: string) => void;
}

const fetcher = vi.hoisted(() => vi.fn());
const l1ViewCalls = vi.hoisted(() =>
  [] as {
    surface: string;
    focusRef: string | null;
    compact?: boolean;
    onSurfaceChange: (s: string) => void;
    onClearFocus: () => void;
    onToast: (msg: string) => void;
  }[],
);

vi.mock("@/lib/api", () => ({
  apiFetch: fetcher,
  apiUrl: (path: string) => path,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts?.n === "number" ? key.replace("{{n}}", String(opts.n)) : key,
  }),
}));
// The workbench assembly is the unit under test; the embedded L1View panel is
// replaced with a stub that records the props it is wired with.
vi.mock("@/components/memory/MemorySection", () => ({
  L1View: (props: (typeof l1ViewCalls)[number]) => {
    l1ViewCalls.push(props);
    return <div data-testid="l1-view" />;
  },
}));

const SNAPSHOT_URLS = [
  "/api/memory/snapshot/chat",
  "/api/memory/snapshot/notebook",
  "/api/memory/snapshot/quiz",
  "/api/memory/snapshot/kb",
  "/api/memory/snapshot/book",
  "/api/memory/snapshot/partner",
  "/api/memory/snapshot/cowriter",
];

const snapshotResponse = (entities: number, pendingChanges: number) => ({
  ok: true,
  json: async () => ({
    entities: Array.from({ length: entities }, (_, i) => ({ id: i })),
    pending_changes: Array.from({ length: pendingChanges }, (_, i) => ({ id: i })),
  }),
});

// Specs keyed by surface: [entity count, pending-change count].
const mockSnapshotSpecs = (specs: Record<string, [number, number]>) => {
  fetcher.mockImplementation((url: string) => {
    const key = String(url).replace("/api/memory/snapshot/", "");
    const spec = specs[key];
    if (!spec) return Promise.resolve(snapshotResponse(0, 0));
    return Promise.resolve(snapshotResponse(spec[0], spec[1]));
  });
};

const lastProps = (): (typeof l1ViewCalls)[number] => {
  expect(l1ViewCalls.length).toBeGreaterThan(0);
  return l1ViewCalls[l1ViewCalls.length - 1];
};

const railButton = (label: RegExp) =>
  screen.getByRole("button", { name: label });

// The mount fetch resolves in a microtask after the fetch calls register, so
// tests that touch the rail must wait for the badge render to settle before
// finishing — otherwise the trailing state update fires outside act().
const waitForRailCounts = async () => {
  await waitFor(() =>
    expect(within(railButton(/^Partner/)).getByText("0")).toBeInTheDocument(),
  );
};

beforeEach(() => {
  fetcher.mockReset();
  l1ViewCalls.length = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

it("renders the workspace shell with rail entries, breadcrumb and layer switcher", async () => {
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench />);

  expect(screen.getByRole("link", { name: "Memory" })).toHaveAttribute(
    "href",
    "/memory",
  );
  expect(screen.getByText("L1 · Workspace mirror")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "L2" })).toHaveAttribute(
    "href",
    "/memory/l2",
  );
  expect(screen.getByRole("link", { name: "L3" })).toHaveAttribute(
    "href",
    "/memory/l3",
  );
  expect(screen.getByText("L1")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "L1" })).toBeNull();

  for (const label of [
    /^Chat/,
    /^Notebook/,
    /^Quiz/,
    /^Knowledge base/,
    /^Book/,
    /^Partner/,
    /^Co-writer/,
  ]) {
    expect(railButton(label)).toBeInTheDocument();
  }

  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(SNAPSHOT_URLS.length));
  expect(fetcher.mock.calls.map(([url]) => url).sort()).toEqual(
    [...SNAPSHOT_URLS].sort(),
  );
  await waitForRailCounts();
  expect(lastProps().surface).toBe("notebook");
  expect(lastProps().compact).toBe(true);
});

it("seeds the active surface and focused entity from initial props", async () => {
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench initialSurface="quiz" initialFocusRef="note_9" />);

  expect(screen.getByTestId("l1-view")).toBeInTheDocument();
  const initial = l1ViewCalls[0];
  expect(initial.surface).toBe("quiz");
  expect(initial.focusRef).toBe("note_9");
  expect(initial.compact).toBe(true);
  await waitForRailCounts();
});

it("loads entity counts and pending badges for every rail entry", async () => {
  mockSnapshotSpecs({
    chat: [3, 2],
    notebook: [5, 0],
    quiz: [0, 0],
  });
  render(<MemoryL1Workbench />);

  expect(await screen.findByText("2 pending")).toBeInTheDocument();
  expect(
    within(railButton(/^Chat/)).getByText("2 pending"),
  ).toBeInTheDocument();
  expect(within(railButton(/^Notebook/)).getByText("5")).toBeInTheDocument();
  expect(within(railButton(/^Quiz/)).getByText("0")).toBeInTheDocument();
  expect(within(railButton(/^Partner/)).getByText("0")).toBeInTheDocument();
});

it("switches surface when a rail entry is clicked and clears the focused entity", async () => {
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench initialSurface="notebook" initialFocusRef="note_9" />);
  await screen.findByTestId("l1-view");
  expect(lastProps().surface).toBe("notebook");
  expect(lastProps().focusRef).toBe("note_9");

  fireEvent.click(railButton(/^Chat/));

  expect(lastProps().surface).toBe("chat");
  expect(lastProps().focusRef).toBeNull();
  await waitForRailCounts();
});

it("follows surface changes requested by the embedded L1View panel", async () => {
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench initialFocusRef="note_9" />);
  await screen.findByTestId("l1-view");

  act(() => lastProps().onSurfaceChange("book"));

  expect(lastProps().surface).toBe("book");
  expect(lastProps().focusRef).toBeNull();
  await waitForRailCounts();
});

it("clears the focused entity when the L1View panel requests it", async () => {
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench initialFocusRef="note_9" />);
  await screen.findByTestId("l1-view");
  expect(lastProps().focusRef).toBe("note_9");

  act(() => lastProps().onClearFocus());

  expect(lastProps().focusRef).toBeNull();
  await waitForRailCounts();
});

it("falls back to zeroed badges when every snapshot request fails", async () => {
  fetcher.mockRejectedValue(new Error("snapshot endpoint unavailable"));
  render(<MemoryL1Workbench />);

  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(SNAPSHOT_URLS.length));
  await waitFor(() =>
    expect(within(railButton(/^Notebook/)).getByText("0")).toBeInTheDocument(),
  );
  for (const label of [
    /^Chat/,
    /^Notebook/,
    /^Quiz/,
    /^Knowledge base/,
    /^Book/,
    /^Partner/,
    /^Co-writer/,
  ]) {
    expect(within(railButton(label)).queryByText(/pending/)).toBeNull();
    expect(within(railButton(label)).getByText("0")).toBeInTheDocument();
  }
  expect(screen.getByTestId("l1-view")).toBeInTheDocument();
});

it("treats empty and null snapshot payloads as zero counts", async () => {
  fetcher.mockImplementation((url: string) => {
    const key = String(url).replace("/api/memory/snapshot/", "");
    if (key === "chat") {
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }
    if (key === "notebook") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ entities: null, pending_changes: null }),
      });
    }
    return Promise.resolve(snapshotResponse(0, 0));
  });
  render(<MemoryL1Workbench />);

  await waitFor(() =>
    expect(within(railButton(/^Chat/)).getByText("0")).toBeInTheDocument(),
  );
  expect(within(railButton(/^Notebook/)).getByText("0")).toBeInTheDocument();
  expect(within(railButton(/^Co-writer/)).getByText("0")).toBeInTheDocument();
  expect(screen.queryByText(/pending/)).toBeNull();
});

it("surfaces a toast from the L1View panel and dismisses it automatically", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockSnapshotSpecs({});
  render(<MemoryL1Workbench />);
  await screen.findByTestId("l1-view");
  expect(screen.queryByText("Snapshot refreshed")).toBeNull();

  act(() => lastProps().onToast("Snapshot refreshed"));
  expect(screen.getByText("Snapshot refreshed")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2600);
  });
  expect(screen.queryByText("Snapshot refreshed")).toBeNull();
});

it("refetches rail counts when the window regains focus", async () => {
  const specs: Record<string, [number, number]> = {
    notebook: [5, 0],
    chat: [1, 0],
  };
  mockSnapshotSpecs(specs);
  render(<MemoryL1Workbench />);

  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(within(railButton(/^Notebook/)).getByText("5")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(SNAPSHOT_URLS.length);

  specs.notebook = [7, 1];
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
  });

  expect(await screen.findByText("1 pending")).toBeInTheDocument();
  expect(
    within(railButton(/^Notebook/)).getByText("1 pending"),
  ).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(SNAPSHOT_URLS.length * 2);
});
