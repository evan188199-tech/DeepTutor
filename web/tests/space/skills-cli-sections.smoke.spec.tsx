/**
 * Smoke coverage for the two remaining zero-reference space sections from
 * scan/web-test-gaps-20261007:
 *   - components/space/SkillsSection.tsx (1038 loc)
 *   - components/cli-apps/CliAppsSection.tsx (1026 loc)
 *
 * List / empty / filter / detail / mutation branches run against a mocked API
 * layer so no product code is touched. Component-level regression guard only:
 * deeper API behavior belongs to cli-apps-api.test.ts and skill-slug.test.ts.
 */

import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import SkillsSection from "@/components/space/SkillsSection";
import CliAppsSection from "@/components/cli-apps/CliAppsSection";
import { CliAppError } from "@/lib/cli-apps-api";
import type { CliApp, CliAppState, CliCatalogEntry } from "@/lib/cli-apps-api";

const skillsApi = vi.hoisted(() => ({
  listSkills: vi.fn(),
  listSkillTags: vi.fn(),
  getSkill: vi.fn(),
  createSkill: vi.fn(),
  updateSkill: vi.fn(),
  deleteSkill: vi.fn(),
  createSkillTag: vi.fn(),
  renameSkillTag: vi.fn(),
  deleteSkillTag: vi.fn(),
}));

const usageApi = vi.hoisted(() => ({
  resourceUsage: vi.fn(),
}));

const cliApi = vi.hoisted(() => ({
  getCliApps: vi.fn(),
  getCliCatalog: vi.fn(),
  installCliApp: vi.fn(),
  setCliAppEnabled: vi.fn(),
  uninstallCliApp: vi.fn(),
}));

const auth = vi.hoisted(() => ({ isAdmin: true, loading: false }));

vi.mock("@/lib/skills-api", () => skillsApi);
vi.mock("@/lib/workspaces-api", () => usageApi);
vi.mock("@/lib/cli-apps-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/cli-apps-api")>()),
  ...cliApi,
}));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({ isAdmin: auth.isAdmin, loading: auth.loading }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      key.replace(/\{\{(\w+)\}\}/g, (_m, k: string) => String(opts?.[k] ?? "")),
    i18n: { language: "en-US" },
  }),
}));

// The real Tooltip lazy-loads a hover layer the smoke run never triggers.
vi.mock("@/shared/ui/Tooltip", () => ({
  default: ({ children }: { children: React.ReactElement }) => children,
}));

// The viewer lazy-loads the markdown renderer through next/dynamic; a stub
// keeps the smoke run on SkillsSection's own wiring.
vi.mock("next/dynamic", () => ({
  default: () => (props: { content?: string }) => (
    <div data-testid="skill-markdown">{props.content}</div>
  ),
}));

vi.mock("@/components/space/EduHubImportModal", () => ({
  default: () => <div data-testid="eduhub-import-modal" />,
}));

vi.mock("@/components/common/BrandIcon", () => ({
  // Render the id, not the display name, so text queries stay unambiguous.
  default: ({ id }: { id: string }) => (
    <span data-testid="brand-icon">{id}</span>
  ),
  TrademarkNote: () => null,
}));

// ── Skills fixtures ─────────────────────────────────────────────────────

const userSkill = {
  name: "socratic-mentor",
  description: "Ask guiding questions",
  tags: ["teaching"],
  source: "user",
};

const builtinSkill = {
  name: "built-in-helper",
  description: "",
  tags: [],
  source: "builtin",
  read_only: true,
};

const untaggedSkill = {
  name: "free-form",
  description: "No tags here",
  tags: [],
};

function skillDetail(name: string, overrides: Record<string, unknown> = {}) {
  return {
    name,
    description: `${name} description`,
    content: `# ${name} playbook`,
    tags: [],
    source: "user",
    read_only: false,
    ...overrides,
  };
}

// ── CliApps fixtures ────────────────────────────────────────────────────

function cliAppState(
  apps: CliApp[],
  access: CliAppState["access"] = { unrestricted: true, exec_denied: false },
  overrides: Partial<CliAppState> = {},
): CliAppState {
  return { apps, access, catalog_pin: "pin-abc", ...overrides };
}

function cliApp(overrides: Partial<CliApp> = {}): CliApp {
  return {
    id: "blender",
    display_name: "Blender",
    description: "3D creation suite",
    category: "graphics",
    tool_name: "cli_blender",
    entry_point: "blender",
    runtime: "python",
    installed_at: "2026-10-01T00:00:00Z",
    version: "4.2.0",
    pin: "9a1b2c3d4e5f",
    trust: "first-party",
    granted: true,
    enabled: true,
    in_catalog: true,
    ...overrides,
  };
}

function catalogEntry(overrides: Partial<CliCatalogEntry> = {}): CliCatalogEntry {
  return {
    id: "obsidian",
    display_name: "Obsidian",
    description: "Local notes vault",
    category: "notes",
    origin: "github.com/obsidianmd/obsidian-releases",
    trust: "third-party",
    requires: "node >= 18",
    homepage: "https://obsidian.md",
    source_url: "https://github.com/obsidianmd/obsidian-releases",
    entry_point: "obsidian",
    runtime: "node",
    install_kind: "archive",
    install_target: "obsidian-1.0.0.zip",
    installable: true,
    pinned: false,
    unsupported_reason: "",
    install_notes: "Extract to data/cli-apps",
    installed: false,
    ...overrides,
  };
}

function catalogPage(
  entries: CliCatalogEntry[],
  overrides: { next_cursor?: string; total?: number; categories?: Record<string, number> } = {},
) {
  return {
    entries,
    next_cursor: overrides.next_cursor ?? "",
    total: overrides.total ?? entries.length,
    categories: overrides.categories ?? {},
    catalog_pin: "pin-abc",
  };
}

beforeEach(() => {
  skillsApi.listSkills.mockResolvedValue([]);
  skillsApi.listSkillTags.mockResolvedValue([]);
  skillsApi.getSkill.mockResolvedValue(skillDetail("anything"));
  skillsApi.createSkill.mockResolvedValue(undefined);
  skillsApi.updateSkill.mockResolvedValue(undefined);
  skillsApi.deleteSkill.mockResolvedValue(undefined);
  skillsApi.createSkillTag.mockImplementation(async (name: string) => name);
  skillsApi.renameSkillTag.mockResolvedValue(undefined);
  skillsApi.deleteSkillTag.mockResolvedValue(undefined);
  usageApi.resourceUsage.mockResolvedValue([]);
  cliApi.getCliApps.mockResolvedValue(cliAppState([]));
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([]));
  cliApi.installCliApp.mockResolvedValue(cliAppState([]));
  cliApi.setCliAppEnabled.mockResolvedValue(cliAppState([]));
  cliApi.uninstallCliApp.mockResolvedValue(cliAppState([]));
  auth.isAdmin = true;
  auth.loading = false;
});

// ── SkillsSection ───────────────────────────────────────────────────────

it("skills: renders loaded skills with badges, actions, and tag chips", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill, builtinSkill]);
  render(<SkillsSection />);

  expect(await screen.findByText("socratic-mentor")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
  expect(
    screen.getByText((_c, el) => el?.textContent === "2 skills.count.suffix"),
  ).toBeInTheDocument();

  // Read-only built-in card: badge shown, no edit/delete affordances.
  expect(screen.getByText("Built-in")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);

  // Descriptions and tag states.
  expect(screen.getByText("Ask guiding questions")).toBeInTheDocument();
  expect(screen.getByText("No description.")).toBeInTheDocument();
  expect(screen.getAllByText("Untagged").length).toBeGreaterThan(0);
});

it("skills: shows the empty state and opens the create editor from it", async () => {
  render(<SkillsSection />);

  expect(await screen.findByText("No skills yet")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Create your first skill" }),
  );

  expect(screen.getByRole("heading", { name: "New skill" })).toBeInTheDocument();
  expect(screen.getByPlaceholderText("e.g. socratic-math-mentor")).toBeInTheDocument();
  expect(screen.getByDisplayValue(/# My Skill/)).toBeInTheDocument();
});

it("skills: filters by tag and untagged and shows the filter-empty state", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill, untaggedSkill]);
  skillsApi.listSkillTags.mockResolvedValue(["teaching", "orphan"]);
  render(<SkillsSection />);
  await screen.findByText("socratic-mentor");

  // Accessible names concatenate chip label and count without a space.
  fireEvent.click(screen.getByRole("button", { name: /^teaching\s*1$/ }));
  expect(screen.queryByText("free-form")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /^Untagged\s*1$/ }));
  expect(screen.queryByText("socratic-mentor")).not.toBeInTheDocument();
  expect(screen.getByText("free-form")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /^orphan\s*0$/ }));
  expect(screen.getByText("No skills match this filter.")).toBeInTheDocument();
});

it("skills: opens the read-only viewer with stripped frontmatter", async () => {
  skillsApi.listSkills.mockResolvedValue([builtinSkill]);
  skillsApi.getSkill.mockResolvedValue(
    skillDetail("built-in-helper", {
      content: "---\nname: built-in-helper\ntags: []\n---\n\nPlaybook body here",
      source: "builtin",
      read_only: true,
    }),
  );
  render(<SkillsSection />);

  fireEvent.click(
    await screen.findByRole("button", { name: "View skill: built-in-helper" }),
  );
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(screen.getByTestId("skill-markdown")).toHaveTextContent(
      "Playbook body here",
    ),
  );
  expect(screen.getByTestId("skill-markdown").textContent).not.toContain("---");
  expect(within(dialog).getByText("Built-in")).toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: "Edit" }),
  ).not.toBeInTheDocument();

  fireEvent.click(dialog);
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});

it("skills: renders the viewer error when the detail request fails", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill]);
  skillsApi.getSkill.mockRejectedValue(new Error("detail boom"));
  render(<SkillsSection />);

  fireEvent.click(
    await screen.findByRole("button", { name: "View skill: socratic-mentor" }),
  );
  expect(await screen.findByText("detail boom")).toBeInTheDocument();
});

it("skills: validates the name on create, then saves and reloads", async () => {
  render(<SkillsSection />);
  fireEvent.click(await screen.findByRole("button", { name: "New skill" }));
  const nameInput = screen.getByPlaceholderText("e.g. socratic-math-mentor");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Name is required")).toBeInTheDocument();
  expect(skillsApi.createSkill).not.toHaveBeenCalled();

  fireEvent.change(nameInput, { target: { value: "a".repeat(70) } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByText(/Name must use only lowercase/),
  ).toBeInTheDocument();
  expect(skillsApi.createSkill).not.toHaveBeenCalled();

  // The input slugifies as it is typed.
  fireEvent.change(nameInput, { target: { value: "My New Skill!" } });
  expect(screen.getByDisplayValue("my-new-skill")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(skillsApi.createSkill).toHaveBeenCalledWith(
      expect.objectContaining({ name: "my-new-skill" }),
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "New skill" }),
    ).not.toBeInTheDocument(),
  );
  expect(skillsApi.listSkills).toHaveBeenCalledTimes(2);
});

it("skills: keeps the editor open with the error when createSkill rejects", async () => {
  skillsApi.createSkill.mockRejectedValue(new Error("create boom"));
  render(<SkillsSection />);
  fireEvent.click(await screen.findByRole("button", { name: "New skill" }));
  fireEvent.change(screen.getByPlaceholderText("e.g. socratic-math-mentor"), {
    target: { value: "fresh-skill" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByText("create boom")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "New skill" })).toBeInTheDocument();
});

it("skills: loads the detail into the edit dialog and renames on save", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill]);
  skillsApi.getSkill.mockResolvedValue(
    skillDetail("socratic-mentor", { description: "Ask guiding questions", content: "# Playbook", tags: ["teaching"] }),
  );
  render(<SkillsSection />);

  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(
    await screen.findByRole("heading", { name: "Edit skill" }),
  ).toBeInTheDocument();
  expect(screen.getByDisplayValue("socratic-mentor")).toBeInTheDocument();
  expect(screen.getByDisplayValue("# Playbook")).toBeInTheDocument();

  fireEvent.change(screen.getByDisplayValue("socratic-mentor"), {
    target: { value: "socratic-mentor-v2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(skillsApi.updateSkill).toHaveBeenCalledWith(
      "socratic-mentor",
      expect.objectContaining({
        rename_to: "socratic-mentor-v2",
        tags: ["teaching"],
      }),
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "Edit skill" }),
    ).not.toBeInTheDocument(),
  );
});

it("skills: guards delete behind confirm and reports workspace usage", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill]);
  usageApi.resourceUsage.mockResolvedValue(["alpha", "beta"]);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<SkillsSection />);

  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(String(confirm.mock.calls[0][0])).toContain(
    "Used by workspaces: alpha, beta",
  );
  expect(skillsApi.deleteSkill).not.toHaveBeenCalled();

  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() =>
    expect(skillsApi.deleteSkill).toHaveBeenCalledWith("socratic-mentor"),
  );
});

it("skills: creates, renames, and deletes tags from the tag manager", async () => {
  skillsApi.listSkills.mockResolvedValue([userSkill]);
  skillsApi.listSkillTags.mockResolvedValue(["teaching"]);
  render(<SkillsSection />);
  await screen.findByText("socratic-mentor");

  fireEvent.click(screen.getByRole("button", { name: /Manage Tags/ }));
  const section = screen.getByText("Manage Tags").closest("section");
  expect(section).not.toBeNull();
  const manager = within(section as HTMLElement);
  expect(manager.getByText("teaching")).toBeInTheDocument();

  fireEvent.change(manager.getByPlaceholderText("New tag name..."), {
    target: { value: "Research" },
  });
  fireEvent.click(manager.getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(skillsApi.createSkillTag).toHaveBeenCalledWith("research"),
  );

  fireEvent.click(manager.getByRole("button", { name: "Rename" }));
  const renameInput = manager.getByDisplayValue("teaching");
  fireEvent.change(renameInput, { target: { value: "teaching-basics" } });
  fireEvent.keyDown(renameInput, { key: "Enter" });
  await waitFor(() =>
    expect(skillsApi.renameSkillTag).toHaveBeenCalledWith(
      "teaching",
      "teaching-basics",
    ),
  );

  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(manager.getByRole("button", { name: "Delete" }));
  await waitFor(() =>
    expect(skillsApi.deleteSkillTag).toHaveBeenCalledWith("teaching"),
  );
});

it("skills: toggles a vocab tag chip and registers a new tag from the editor", async () => {
  skillsApi.listSkillTags.mockResolvedValue(["teaching"]);
  render(<SkillsSection />);
  fireEvent.click(await screen.findByRole("button", { name: "New skill" }));

  fireEvent.click(screen.getByRole("button", { name: "teaching" }));
  fireEvent.change(screen.getByPlaceholderText("Add a tag..."), {
    target: { value: "Fresh Tag" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(skillsApi.createSkillTag).toHaveBeenCalledWith("fresh tag"),
  );

  fireEvent.change(screen.getByPlaceholderText("e.g. socratic-math-mentor"), {
    target: { value: "tagged-skill" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(skillsApi.createSkill).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "tagged-skill",
        tags: expect.arrayContaining(["teaching", "fresh tag"]),
      }),
    ),
  );
});

it("skills: shows the load error banner when listing fails", async () => {
  skillsApi.listSkills.mockRejectedValue(new Error("network down"));
  render(<SkillsSection />);
  expect(await screen.findByText("network down")).toBeInTheDocument();
});

// ── CliAppsSection ──────────────────────────────────────────────────────

it("cli apps: renders the installed list with switches, trust chips, and lock notes", async () => {
  cliApi.getCliApps.mockResolvedValue(
    cliAppState([
      cliApp(),
      cliApp({
        id: "lockpick",
        display_name: "Lockpick",
        tool_name: "cli_lockpick",
        granted: false,
        enabled: false,
        trust: "third-party",
        pin: "",
      }),
    ]),
  );
  render(<CliAppsSection />);

  expect(await screen.findByText("Blender")).toBeInTheDocument();
  expect(screen.getByText("cli_blender")).toBeInTheDocument();
  expect(screen.getByText("1 available to you")).toBeInTheDocument();
  expect(screen.getByText("Pinned")).toBeInTheDocument();
  expect(screen.getByText("Third-party, unpinned")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Not assigned to your account. An administrator has to grant it before you can use it.",
    ),
  ).toBeInTheDocument();
  // The install-date row: label present, pin truncated to 12 chars.
  const blenderRow = screen.getByText("Blender").closest("li");
  expect(blenderRow).not.toBeNull();
  const installedRow = within(blenderRow as HTMLElement).getByText(
    (_c, el) => el?.tagName === "P" && /^Installed/.test(el.textContent ?? ""),
  );
  expect(installedRow.textContent).toContain("· 9a1b2c3d4e5f");

  const switches = screen.getAllByRole("switch");
  expect(switches).toHaveLength(1);
  expect(switches[0]).toHaveAttribute("aria-checked", "true");
});

it("cli apps: renders the load error banner", async () => {
  cliApi.getCliApps.mockRejectedValue(new Error("cli list boom"));
  render(<CliAppsSection />);
  expect(await screen.findByText("cli list boom")).toBeInTheDocument();
});

it("cli apps: shows the admin empty state and switches to the store", async () => {
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([catalogEntry()]));
  render(<CliAppsSection />);

  expect(await screen.findByText("No CLI apps installed")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Browse the store to install one. Installing runs the app's own installer on this server, so it stays an administrator action.",
    ),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Browse the store" }));
  expect(await screen.findByText("Obsidian")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("Search CLI apps…")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Include unavailable" }),
  ).toBeInTheDocument();
});

it("cli apps: shows the non-admin empty-state copy", async () => {
  auth.isAdmin = false;
  render(<CliAppsSection />);
  expect(await screen.findByText("No CLI apps installed")).toBeInTheDocument();
  expect(
    screen.getByText(
      "An administrator installs these, then assigns them to accounts. Browse the store to see what you could ask for by name.",
    ),
  ).toBeInTheDocument();
});

it("cli apps: warns when the account cannot execute code", async () => {
  cliApi.getCliApps.mockResolvedValue(
    cliAppState([cliApp()], { unrestricted: false, exec_denied: true }),
  );
  render(<CliAppsSection />);
  expect(
    await screen.findByText(
      "Your account cannot run code, so no CLI app is available to the chat agent — even the ones listed below.",
    ),
  ).toBeInTheDocument();
});

it("cli apps: toggles an app off through setCliAppEnabled", async () => {
  cliApi.getCliApps.mockResolvedValue(cliAppState([cliApp()]));
  cliApi.setCliAppEnabled.mockResolvedValue(
    cliAppState([cliApp({ enabled: false })]),
  );
  render(<CliAppsSection />);

  fireEvent.click(await screen.findByRole("switch", { name: "On" }));
  await waitFor(() =>
    expect(cliApi.setCliAppEnabled).toHaveBeenCalledWith("blender", false),
  );
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: "Off" })).toBeInTheDocument(),
  );
  expect(screen.getByRole("switch", { name: "Off" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByText("0 available to you")).toBeInTheDocument();
});

it("cli apps: keeps the switch and surfaces the failure when toggling fails", async () => {
  cliApi.getCliApps.mockResolvedValue(cliAppState([cliApp({ enabled: false })]));
  cliApi.setCliAppEnabled.mockRejectedValue(
    new CliAppError("enable refused", "forbidden"),
  );
  render(<CliAppsSection />);

  fireEvent.click(await screen.findByRole("switch", { name: "Off" }));
  expect(await screen.findByText("enable refused")).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Off" })).toBeInTheDocument();
});

it("cli apps: uninstalls after confirmation and skips the call on decline", async () => {
  cliApi.getCliApps.mockResolvedValue(cliAppState([cliApp()]));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<CliAppsSection />);

  fireEvent.click(await screen.findByRole("button", { name: "Uninstall" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(String(confirm.mock.calls[0][0])).toContain("Blender");
  expect(cliApi.uninstallCliApp).not.toHaveBeenCalled();

  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Uninstall" }));
  expect(await screen.findByText("No CLI apps installed")).toBeInTheDocument();
  expect(cliApi.uninstallCliApp).toHaveBeenCalledWith("blender");
});

it("cli apps: paginates the catalog and applies category and availability filters", async () => {
  cliApi.getCliCatalog
    .mockResolvedValueOnce(
      catalogPage(
        [
          catalogEntry(),
          catalogEntry({
            id: "jqtool",
            display_name: "jq",
            description: "JSON processor",
            category: "data",
            trust: "first-party",
            pinned: true,
          }),
        ],
        { next_cursor: "page-2", total: 3, categories: { notes: 2, data: 1 } },
      ),
    )
    .mockResolvedValueOnce(
      catalogPage([
        catalogEntry({
          id: "sd",
          display_name: "Stable Diffusion",
          description: "Image generation",
          category: "graphics",
        }),
      ]),
    );
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");

  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  expect(await screen.findByText("Obsidian")).toBeInTheDocument();
  expect(screen.getByText("jq")).toBeInTheDocument();
  expect(screen.getByText("2 of 3 apps")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^notes\s*2$/ })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Load more" }));  expect(await screen.findByText("Stable Diffusion")).toBeInTheDocument();
  expect(screen.getByText("3 of 3 apps")).toBeInTheDocument();
  expect(cliApi.getCliCatalog).toHaveBeenLastCalledWith(
    expect.objectContaining({ cursor: "page-2", limit: 12 }),
  );

  fireEvent.click(screen.getByRole("button", { name: /^notes\s*2$/ }));
  await waitFor(() =>
    expect(cliApi.getCliCatalog).toHaveBeenLastCalledWith(
      expect.objectContaining({ category: "notes" }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Include unavailable" }));
  await waitFor(() =>
    expect(cliApi.getCliCatalog).toHaveBeenLastCalledWith(
      expect.objectContaining({ installableOnly: false }),
    ),
  );
});

it("cli apps: debounces the search draft into the catalog query", async () => {
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");
  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  fireEvent.change(await screen.findByPlaceholderText("Search CLI apps…"), {
    target: { value: "obs" },
  });

  await waitFor(
    () =>
      expect(cliApi.getCliCatalog).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "obs" }),
      ),
    { timeout: 2000 },
  );
});

it("cli apps: shows the store empty state", async () => {
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([], { total: 0 }));
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");
  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
});

it("cli apps: installs from the entry detail, surfacing the refusal log, then reinstalling", async () => {
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([catalogEntry()]));
  cliApi.installCliApp
    .mockRejectedValueOnce(
      new CliAppError(
        "its published install command is a shell script",
        "setup_failed",
        "resolving obsidian 1.0.0",
      ),
    )
    .mockResolvedValueOnce(
      cliAppState([cliApp({ id: "obsidian", display_name: "Obsidian", tool_name: "cli_obsidian" })], undefined, {
        log: "installed obsidian 1.0.0",
      }),
    );
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");

  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  fireEvent.click(await screen.findByRole("button", { name: /Obsidian/ }));

  expect(await screen.findByText("cli_obsidian")).toBeInTheDocument();
  expect(screen.getByText("node >= 18")).toBeInTheDocument();
  expect(screen.getByText("Extract to data/cli-apps")).toBeInTheDocument();
  expect(
    screen.getByText(
      "This resolves to whatever that source publishes today — it is not pinned to a reviewed revision.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Website" })).toHaveAttribute(
    "href",
    "https://obsidian.md",
  );
  expect(screen.getByRole("link", { name: "Source" })).toHaveAttribute(
    "href",
    "https://github.com/obsidianmd/obsidian-releases",
  );

  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(
    await screen.findByText("its published install command is a shell script"),
  ).toBeInTheDocument();
  expect(screen.getByText("resolving obsidian 1.0.0")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(await screen.findByRole("button", { name: "Reinstall" })).toBeInTheDocument();
  expect(screen.getAllByText("Installed").length).toBeGreaterThan(0);
  expect(screen.getByText("1 available to you")).toBeInTheDocument();
});

it("cli apps: keeps the store read-only for non-admins", async () => {
  auth.isAdmin = false;
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([catalogEntry()]));
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");

  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  expect(
    await screen.findByText(
      "Installing runs the app's own installer on this server, so it is an administrator action. You can browse here and ask for an app by name.",
    ),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Obsidian/ }));
  expect(
    await screen.findByText(
      "Only an administrator can install this. Once installed they can assign it to your account.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
});

it("cli apps: explains why an unavailable entry cannot be installed", async () => {
  cliApi.getCliCatalog.mockResolvedValue(
    catalogPage([
      catalogEntry({
        id: "win-only",
        display_name: "Windows Only",
        description: "Needs Windows",
        installable: false,
        unsupported_reason: "Arm64 builds unavailable",
      }),
    ]),
  );
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");

  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  fireEvent.click(await screen.findByRole("button", { name: /Windows Only/ }));
  expect(await screen.findByText("Not installable here.")).toBeInTheDocument();
  expect(screen.getByText("Arm64 builds unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
});

it("cli apps: hides install affordances while admin status is loading", async () => {
  auth.loading = true;
  cliApi.getCliCatalog.mockResolvedValue(catalogPage([catalogEntry()]));
  render(<CliAppsSection />);
  await screen.findByText("No CLI apps installed");

  fireEvent.click(screen.getByRole("button", { name: "Store" }));
  fireEvent.click(await screen.findByRole("button", { name: /Obsidian/ }));
  await screen.findByText("cli_obsidian");
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  expect(
    screen.queryByText("Only an administrator can install this. Once installed they can assign it to your account."),
  ).not.toBeInTheDocument();
});
