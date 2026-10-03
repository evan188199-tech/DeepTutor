import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DataMigrationSettingsSection from "@/features/settings/sections/DataMigrationSettingsSection";

const fixture = vi.hoisted(() => ({
  fetch: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => fixture.fetch(...args),
}));
vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: () => ({ workspaces: [], error: null }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "en" } }),
}));

const SYNC_HINT = "Operation status sync is failing. Retrying automatically…";

let operationsOutcomes: Array<"ok" | "fail"> = [];

function operationsCalls(): number {
  return fixture.fetch.mock.calls.filter(([input]) =>
    String(input).includes("/operations"),
  ).length;
}

beforeEach(() => {
  operationsOutcomes = [];
  fixture.fetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/operations")) {
      const outcome = operationsOutcomes.shift() ?? "ok";
      if (outcome === "fail") {
        return { ok: false, status: 503, json: async () => ({ detail: "backend down" }) };
      }
      return { ok: true, status: 200, json: async () => ({ operations: [] }) };
    }
    if (url.includes("/discover")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ features: [], historical: [], session_backend: "test" }),
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

async function settle(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

it("shows a visible sync hint after consecutive /operations polling failures", async () => {
  operationsOutcomes = ["fail", "fail", "fail"];
  render(<DataMigrationSettingsSection />);
  await act(async () => {});
  expect(screen.queryByText(SYNC_HINT)).toBeNull();
  await settle(5000);
  expect(screen.getByText(SYNC_HINT)).toBeInTheDocument();
});

it("keeps the hint hidden for a single transient failure", async () => {
  operationsOutcomes = ["fail"];
  render(<DataMigrationSettingsSection />);
  await act(async () => {});
  await settle(15000);
  expect(screen.queryByText(SYNC_HINT)).toBeNull();
});

it("clears the hint once syncing recovers", async () => {
  operationsOutcomes = ["fail", "fail", "fail"];
  render(<DataMigrationSettingsSection />);
  await act(async () => {});
  await settle(5000);
  expect(screen.getByText(SYNC_HINT)).toBeInTheDocument();
  await settle(10000);
  expect(screen.queryByText(SYNC_HINT)).toBeNull();
});

it("keeps polling /operations on the original 5s cadence", async () => {
  render(<DataMigrationSettingsSection />);
  await act(async () => {});
  expect(operationsCalls()).toBe(1);
  await settle(4999);
  expect(operationsCalls()).toBe(1);
  await settle(1);
  expect(operationsCalls()).toBe(2);
});
