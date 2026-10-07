import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import ConnectedAgents from "@/components/agents/ConnectedAgents";

const api = vi.hoisted(() => ({
  detectSubagents: vi.fn(),
  listSubagentConnections: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/subagents-api", () => ({
  detectSubagents: api.detectSubagents,
  listSubagentConnections: api.listSubagentConnections,
  connectSubagent: vi.fn(),
  disconnectSubagent: vi.fn(),
}));

// A forbidden read must render an error box, not the "no agents available"
// empty state (#1228 pattern).
it("renders an error instead of the empty state when agent reads are forbidden", async () => {
  api.detectSubagents.mockImplementation(() =>
    Promise.reject(
      Object.assign(new Error("Request failed (403)"), { status: 403 }),
    ),
  );
  api.listSubagentConnections.mockImplementation(() =>
    Promise.reject(
      Object.assign(new Error("Request failed (403)"), { status: 403 }),
    ),
  );

  render(<ConnectedAgents />);

  const alert = await screen.findByText(
    "Could not load agents. Check your access and try again.",
  );
  expect(alert).toHaveAttribute("role", "alert");
  expect(
    screen.queryByText(/No supported local agent/i),
  ).toBeNull();
});
