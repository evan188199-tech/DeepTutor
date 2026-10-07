import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SpaceDashboard from "@/components/space/SpaceDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}))

const tileLoaders = vi.hoisted(() => ({
  listSessions: vi.fn(),
  listNotebooks: vi.fn(),
  listNotebookEntries: vi.fn(),
  listPersonas: vi.fn(),
  listKnowledgeBases: vi.fn(),
  listSkills: vi.fn(),
  getCliApps: vi.fn(),
  loadMcpSurface: vi.fn(),
}))

vi.mock("@/lib/session-api", () => ({ listSessions: tileLoaders.listSessions }))
vi.mock("@/lib/notebook-api", () => ({
  listNotebooks: tileLoaders.listNotebooks,
  listNotebookEntries: tileLoaders.listNotebookEntries,
}))
vi.mock("@/lib/personas-api", () => ({ listPersonas: tileLoaders.listPersonas }))
vi.mock("@/features/knowledge/api/catalog", () => ({
  listKnowledgeBases: tileLoaders.listKnowledgeBases,
}))
vi.mock("@/lib/skills-api", () => ({ listSkills: tileLoaders.listSkills }))
vi.mock("@/lib/cli-apps-api", () => ({
  CLI_APPS_BASE_PATH: "/api/space/cli-apps",
  getCliApps: tileLoaders.getCliApps,
}))
vi.mock("@/components/mcp/surface", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/mcp/surface")>()
  return { ...actual, loadMcpSurface: tileLoaders.loadMcpSurface }
})
vi.mock("@/features/capabilities/api", () => ({
  fetchCapabilityCatalog: vi.fn(() =>
    Promise.reject(Object.assign(new Error("Request failed: 403"), { status: 403 })),
  ),
}))

// Regression guard for the #1228 pattern on /space tiles: a 403 on any tile
// load is swallowed by the per-tile catch, so every count is silently omitted
// and the grid reads as empty. The dashboard must instead keep the tiles
// visible and raise a visible error.
it("renders a visible error instead of silently blank counts when every space tile is forbidden", async () => {
  for (const loader of Object.values(tileLoaders)) {
    loader.mockImplementation(() =>
      Promise.reject(Object.assign(new Error("Request failed: 403"), { status: 403 })),
    )
  }
  render(<SpaceDashboard />)
  await waitFor(() => expect(tileLoaders.listSessions).toHaveBeenCalled())
  expect(screen.getByText("Chat History")).toBeInTheDocument()
  expect(await screen.findByRole("alert")).toBeInTheDocument()
  expect(screen.getAllByText("—").length).toBeGreaterThan(0)
})
