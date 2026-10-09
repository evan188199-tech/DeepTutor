import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  guardian: {
    listGuardianRelationships: vi.fn(),
    getGuardianReport: vi.fn(),
    getGuardianMaterials: vi.fn(),
    getGuardianRestrictions: vi.fn(),
    resetLearnerCredentials: vi.fn(),
    revokeMyGuardianRelationship: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));

vi.mock("@/lib/guardian-api", () => ({
  listGuardianRelationships: (...args: unknown[]) =>
    mocks.guardian.listGuardianRelationships(...args),
  getGuardianReport: (...args: unknown[]) =>
    mocks.guardian.getGuardianReport(...args),
  getGuardianMaterials: (...args: unknown[]) =>
    mocks.guardian.getGuardianMaterials(...args),
  getGuardianRestrictions: (...args: unknown[]) =>
    mocks.guardian.getGuardianRestrictions(...args),
  resetLearnerCredentials: (...args: unknown[]) =>
    mocks.guardian.resetLearnerCredentials(...args),
  revokeMyGuardianRelationship: (...args: unknown[]) =>
    mocks.guardian.revokeMyGuardianRelationship(...args),
}));

const t = (key: string, vars?: Record<string, unknown>) =>
  vars
    ? key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(vars[name]))
    : key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t }),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/theme", () => ({ setTheme: vi.fn() }));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "github",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));
vi.mock("@/lib/llm-options", () => ({
  invalidateLLMOptionsCache: vi.fn(),
  listLLMOptions: vi.fn(async () => ({ active: null, options: [] })),
}));

import GuardianSettingsSection from "@/features/settings/sections/GuardianSettingsSection";
import {
  defaultCatalog,
  SettingsProvider,
} from "@/features/settings/store/SettingsStore";

const reply = (value: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 422,
  json: async () => value,
});

const relationship = (overrides: Record<string, unknown> = {}) => ({
  id: "rel-1",
  guardian_user_id: "g1",
  guardian_username: "Guardian Grace",
  learner_user_id: "l1",
  learner_username: "Learner Lou",
  permissions: [
    "assign_materials",
    "manage_restrictions",
    "view_reports",
    "reset_credentials",
  ],
  revoked_at: null,
  ...overrides,
});
const report = {
  learner: { id: "l1", username: "Learner Lou", disabled: false },
  assigned_materials: [{ book_id: "b1", permission: "read" }],
  grant_summary: { model_count: 1, knowledge_base_count: 2, skill_count: 3 },
};
const materials = [
  { book_id: "b1", title: "Algebra Basics", assigned: true, permission: "read" },
  { book_id: "b2", assigned: false, permission: "read" },
];
const restrictionsPayload = {
  restrictions: {
    age_band: "9-12" as const,
    allow_upload: false,
    allowed_surfaces: ["chat" as const],
    extensions: [],
  },
  available_extensions: [{ id: "ext-1", name: "Math Pack", version: "1.0" }],
};

const renderSection = () =>
  render(
    <SettingsProvider>
      <GuardianSettingsSection />
    </SettingsProvider>,
  );

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.fetch.mockImplementation(async (url: string) => {
    if (url === "/api/settings")
      return reply({
        catalog: defaultCatalog(),
        ui: { theme: "snow", language: "en", response_language: "en" },
      });
    if (url === "/api/settings/draft") return reply({ draft: null });
    if (url === "/api/system/status") return reply({ healthy: true });
    return reply({});
  });
  for (const fn of Object.values(mocks.guardian)) fn.mockReset();
});

it("shows the loading placeholder before resolving to the empty state", async () => {
  let resolveList!: (value: never[]) => void;
  mocks.guardian.listGuardianRelationships.mockImplementation(
    () =>
      new Promise<never[]>((resolve) => {
        resolveList = resolve;
      }),
  );
  renderSection();
  expect(
    screen.getByText("Loading guardian relationships…"),
  ).toBeInTheDocument();
  resolveList([]);
  await waitFor(() =>
    expect(
      screen.getByText("No active learner relationships."),
    ).toBeInTheDocument(),
  );
});

it("renders the list failure instead of the relationship grid", async () => {
  mocks.guardian.listGuardianRelationships.mockRejectedValue(
    new Error("Session expired"),
  );
  renderSection();
  await waitFor(() =>
    expect(screen.getByText("Session expired")).toBeInTheDocument(),
  );
  expect(
    screen.getByText("No active learner relationships."),
  ).toBeInTheDocument();
});

it("loads only the sections the selected relationship's permissions allow", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["view_reports"] }),
  ]);
  mocks.guardian.getGuardianReport.mockResolvedValue(report);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  await waitFor(() =>
    expect(mocks.guardian.getGuardianReport).toHaveBeenCalledWith("l1"),
  );
  expect(mocks.guardian.getGuardianMaterials).not.toHaveBeenCalled();
  expect(mocks.guardian.getGuardianRestrictions).not.toHaveBeenCalled();
  expect(screen.getByText("View reports")).toBeInTheDocument();
  expect(screen.getByText("1")).toBeInTheDocument();
  expect(screen.getByText("6")).toBeInTheDocument();
  expect(
    screen.queryByText("No approved materials are available."),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Learning restrictions")).not.toBeInTheDocument();
  expect(screen.queryByText("New learner password")).not.toBeInTheDocument();
});

it("explains that the report is hidden without the view_reports permission", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["reset_credentials"] }),
  ]);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  await waitFor(() =>
    expect(
      screen.getByText(
        "You are not authorized to view this learner report.",
      ),
    ).toBeInTheDocument(),
  );
  expect(mocks.guardian.getGuardianReport).not.toHaveBeenCalled();
  expect(mocks.guardian.getGuardianMaterials).not.toHaveBeenCalled();
  expect(mocks.guardian.getGuardianRestrictions).not.toHaveBeenCalled();
  expect(screen.getByText("New learner password")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Reset learner credentials" }),
  ).toBeDisabled();
});

it("renders assigned materials with the id fallback and stages checkbox edits", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["assign_materials"] }),
  ]);
  mocks.guardian.getGuardianMaterials.mockResolvedValue(materials);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  expect(await screen.findByText("Algebra Basics")).toBeInTheDocument();
  expect(screen.getByText("b2")).toBeInTheDocument();
  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes[0]).toBeChecked();
  expect(checkboxes[1]).not.toBeChecked();
  fireEvent.click(checkboxes[1]);
  expect(checkboxes[1]).toBeChecked();
  fireEvent.click(checkboxes[0]);
  expect(checkboxes[0]).not.toBeChecked();
});

it("shows the empty materials note when nothing is catalogued", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["assign_materials"] }),
  ]);
  mocks.guardian.getGuardianMaterials.mockResolvedValue([]);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  await waitFor(() =>
    expect(
      screen.getByText("No approved materials are available."),
    ).toBeInTheDocument(),
  );
});

it("renders the restrictions editor and stages age band and extension edits", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["manage_restrictions"] }),
  ]);
  mocks.guardian.getGuardianRestrictions.mockResolvedValue(
    restrictionsPayload,
  );
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  const ageBand = await screen.findByDisplayValue("9-12");
  const extensionToggle = screen.getByRole("checkbox", { name: "Math Pack" });
  expect(extensionToggle).not.toBeChecked();
  const uploadToggle = screen.getByRole("checkbox", {
    name: "Allow learner uploads",
  });
  expect(uploadToggle).not.toBeChecked();
  fireEvent.change(ageBand, { target: { value: "13-15" } });
  expect(ageBand).toHaveValue("13-15");
  fireEvent.click(extensionToggle);
  expect(extensionToggle).toBeChecked();
});

it("resets credentials only for a confirmed eight-character password", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["reset_credentials"] }),
  ]);
  mocks.guardian.resetLearnerCredentials.mockResolvedValue(undefined);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  const resetButton = await screen.findByRole("button", {
    name: "Reset learner credentials",
  });
  const passwordInput = screen.getByLabelText("New learner password");
  fireEvent.change(passwordInput, { target: { value: "short" } });
  expect(resetButton).toBeDisabled();
  fireEvent.change(passwordInput, { target: { value: "long-enough-1" } });
  expect(resetButton).toBeEnabled();
  fireEvent.click(resetButton);
  const dialog = screen.getByRole("alertdialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Reset credentials" }),
  );
  await waitFor(() =>
    expect(mocks.guardian.resetLearnerCredentials).toHaveBeenCalledWith(
      "l1",
      "long-enough-1",
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByText("Learner credentials were reset."),
    ).toBeInTheDocument(),
  );
  expect(passwordInput).toHaveValue("");
});

it("reports credential reset failures instead of a success message", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([
    relationship({ permissions: ["reset_credentials"] }),
  ]);
  mocks.guardian.resetLearnerCredentials.mockRejectedValue(
    new Error("Password rejected"),
  );
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  const resetButton = await screen.findByRole("button", {
    name: "Reset learner credentials",
  });
  fireEvent.change(screen.getByLabelText("New learner password"), {
    target: { value: "long-enough-1" },
  });
  fireEvent.click(resetButton);
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Reset credentials",
    }),
  );
  await waitFor(() =>
    expect(screen.getByText("Password rejected")).toBeInTheDocument(),
  );
  expect(
    screen.queryByText("Learner credentials were reset."),
  ).not.toBeInTheDocument();
});

it("revokes access after confirmation and drops the relationship", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([relationship()]);
  mocks.guardian.revokeMyGuardianRelationship.mockResolvedValue(undefined);
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  const revokeButton = await screen.findByRole("button", {
    name: "Revoke access",
  });
  await waitFor(() => expect(revokeButton).toBeEnabled());
  fireEvent.click(revokeButton);
  const dialog = screen.getByRole("alertdialog", {
    name: "Revoke guardian access",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Revoke access" }),
  );
  await waitFor(() =>
    expect(mocks.guardian.revokeMyGuardianRelationship).toHaveBeenCalledWith(
      "rel-1",
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByText("Guardian access revoked."),
    ).toBeInTheDocument(),
  );
  await waitFor(() =>
    expect(screen.queryByText("Learner Lou")).not.toBeInTheDocument(),
  );
  expect(
    screen.getByText("No active learner relationships."),
  ).toBeInTheDocument();
});

it("keeps the relationship and shows the error when revocation fails", async () => {
  mocks.guardian.listGuardianRelationships.mockResolvedValue([relationship()]);
  mocks.guardian.revokeMyGuardianRelationship.mockRejectedValue(
    new Error("Revoke failed"),
  );
  renderSection();
  fireEvent.click(await screen.findByText("Learner Lou"));
  const revokeButton = await screen.findByRole("button", {
    name: "Revoke access",
  });
  await waitFor(() => expect(revokeButton).toBeEnabled());
  fireEvent.click(revokeButton);
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Revoke access",
    }),
  );
  await waitFor(() =>
    expect(screen.getByText("Revoke failed")).toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: /Learner Lou/ }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Guardian access revoked."),
  ).not.toBeInTheDocument();
});
