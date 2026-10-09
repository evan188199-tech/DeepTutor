import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  guardian: {
    listAdminGuardianRelationships: vi.fn(),
    getGuardianReport: vi.fn(),
    authorizeGuardianRelationship: vi.fn(),
    revokeGuardianRelationship: vi.fn(),
    resetLearnerCredentials: vi.fn(),
  },
}));

vi.mock("@/lib/guardian-api", () => ({
  listAdminGuardianRelationships: (...args: unknown[]) =>
    mocks.guardian.listAdminGuardianRelationships(...args),
  getGuardianReport: (...args: unknown[]) =>
    mocks.guardian.getGuardianReport(...args),
  authorizeGuardianRelationship: (...args: unknown[]) =>
    mocks.guardian.authorizeGuardianRelationship(...args),
  revokeGuardianRelationship: (...args: unknown[]) =>
    mocks.guardian.revokeGuardianRelationship(...args),
  resetLearnerCredentials: (...args: unknown[]) =>
    mocks.guardian.resetLearnerCredentials(...args),
}));

const t = (key: string, vars?: Record<string, unknown>) =>
  vars
    ? key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(vars[name]))
    : key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t }),
}));

import type { UserRecord } from "@/lib/admin-api";
import { GuardianRelationshipsEditor } from "@/features/multi-user/components/GuardianRelationshipsEditor";

const users = [
  {
    id: "u-admin",
    username: "Admin Ada",
    role: "admin",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "l1",
    username: "Self Learner",
    role: "user",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "u-learner",
    username: "Preset Learner",
    role: "user",
    preset: "learner",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "u-active",
    username: "Active Guardian",
    role: "user",
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "u-new",
    username: "Eligible User",
    role: "user",
    created_at: "2026-01-01T00:00:00Z",
  },
] as unknown as UserRecord[];

const adminRelationships = [
  {
    id: "rel-a",
    guardian_user_id: "u-active",
    guardian_username: "Active Guardian",
    learner_user_id: "l1",
    learner_username: "Learner Lou",
    permissions: ["assign_materials", "mystery_permission"],
    revoked_at: null,
  },
  {
    id: "rel-b",
    guardian_user_id: "u-other",
    guardian_username: "Elsewhere Guardian",
    learner_user_id: "l2",
    learner_username: "Other Learner",
    permissions: ["view_reports"],
    revoked_at: null,
  },
];
const report = {
  learner: { id: "l1", username: "Learner Lou", disabled: false },
  assigned_materials: [
    { book_id: "b1", permission: "read" },
    { book_id: "b2", permission: "read" },
  ],
  grant_summary: { model_count: 2, knowledge_base_count: 1, skill_count: 2 },
};

const renderEditor = (overrides: Partial<Parameters<typeof GuardianRelationshipsEditor>[0]> = {}) =>
  render(
    <GuardianRelationshipsEditor
      learnerId="l1"
      learnerUsername="Learner Lou"
      users={users}
      {...overrides}
    />,
  );

beforeEach(() => {
  for (const fn of Object.values(mocks.guardian)) fn.mockReset();
  mocks.guardian.listAdminGuardianRelationships.mockResolvedValue(
    adminRelationships,
  );
  mocks.guardian.getGuardianReport.mockResolvedValue(report);
});

it("shows the loading placeholder before rendering this learner's relationships", async () => {
  let resolveList!: (value: never[]) => void;
  mocks.guardian.listAdminGuardianRelationships.mockImplementation(
    () =>
      new Promise<never[]>((resolve) => {
        resolveList = resolve;
      }),
  );
  renderEditor();
  expect(
    screen.getByText("Loading guardian relationships…"),
  ).toBeInTheDocument();
  resolveList([]);
  await waitFor(() =>
    expect(
      screen.getByText("No active guardian relationships."),
    ).toBeInTheDocument(),
  );
});

it("filters relationships and permission labels to the selected learner", async () => {
  renderEditor();
  expect(await screen.findByText("Active Guardian")).toBeInTheDocument();
  expect(screen.queryByText("Elsewhere Guardian")).not.toBeInTheDocument();
  expect(
    screen.getByText("Manage materials · mystery_permission"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("2 approved materials · 5 enabled resources"),
  ).toBeInTheDocument();
});

it("renders the load failure instead of the relationship list", async () => {
  mocks.guardian.listAdminGuardianRelationships.mockRejectedValue(
    new Error("Forbidden"),
  );
  renderEditor();
  await waitFor(() =>
    expect(screen.getByText("Forbidden")).toBeInTheDocument(),
  );
  expect(
    screen.getByText("No active guardian relationships."),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Manage materials · mystery_permission"),
  ).not.toBeInTheDocument();
});

it("keeps the report failure non-fatal for the relationship list", async () => {
  mocks.guardian.getGuardianReport.mockRejectedValue(
    new Error("Report unavailable"),
  );
  renderEditor();
  await waitFor(() =>
    expect(screen.getByText("Report unavailable")).toBeInTheDocument(),
  );
  expect(screen.getByText("Active Guardian")).toBeInTheDocument();
  expect(
    screen.queryByText(/approved materials/),
  ).not.toBeInTheDocument();
});

it("offers only eligible non-learner candidates and disables the picker without them", async () => {
  const view = renderEditor();
  await screen.findByText("Active Guardian");
  const select = screen.getByRole("combobox");
  const names = within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
  expect(names).toEqual(["Select a guardian", "Eligible User"]);

  view.unmount();
  renderEditor({ users: [] });
  await screen.findByText("Active Guardian");
  expect(screen.getByRole("combobox")).toBeDisabled();
});

it("authorizes the chosen guardian with the selected permissions", async () => {
  mocks.guardian.authorizeGuardianRelationship.mockResolvedValue({
    id: "rel-new",
    guardian_user_id: "u-new",
    guardian_username: "Eligible User",
    learner_user_id: "l1",
    learner_username: "Learner Lou",
    permissions: ["view_reports"],
    revoked_at: null,
  });
  renderEditor();
  await screen.findByText("Active Guardian");
  const authorizeButton = screen.getByRole("button", {
    name: "Authorize guardian",
  });
  expect(authorizeButton).toBeDisabled();

  const select = screen.getByRole("combobox");
  fireEvent.change(select, { target: { value: "u-new" } });
  expect(authorizeButton).toBeEnabled();
  fireEvent.click(authorizeButton);
  await waitFor(() =>
    expect(
      mocks.guardian.authorizeGuardianRelationship,
    ).toHaveBeenCalledWith("u-new", "l1", [
      "assign_materials",
      "manage_restrictions",
      "view_reports",
      "reset_credentials",
    ]),
  );
  await screen.findByText("Guardian relationship added.");
  expect(screen.getByText("Eligible User")).toBeInTheDocument();
  expect(select).toHaveValue("");
});

it("blocks authorization once every permission is unchecked", async () => {
  renderEditor();
  await screen.findByText("Active Guardian");
  const select = screen.getByRole("combobox");
  fireEvent.change(select, { target: { value: "u-new" } });
  const authorizeButton = screen.getByRole("button", {
    name: "Authorize guardian",
  });
  expect(authorizeButton).toBeEnabled();
  for (const label of [
    "Manage materials",
    "Manage restrictions",
    "View reports",
    "Reset credentials",
  ]) {
    fireEvent.click(screen.getByRole("checkbox", { name: label }));
  }
  expect(authorizeButton).toBeDisabled();
  expect(mocks.guardian.authorizeGuardianRelationship).not.toHaveBeenCalled();
});

it("reports authorization failures without adding a row", async () => {
  mocks.guardian.authorizeGuardianRelationship.mockRejectedValue(
    new Error("Learner not found"),
  );
  renderEditor();
  await screen.findByText("Active Guardian");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "u-new" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize guardian" }));
  await waitFor(() =>
    expect(screen.getByText("Learner not found")).toBeInTheDocument(),
  );
  expect(
    screen.queryByText("Guardian relationship added."),
  ).not.toBeInTheDocument();
});

it("revokes a relationship after confirmation and shows the empty state", async () => {
  mocks.guardian.revokeGuardianRelationship.mockResolvedValue(undefined);
  renderEditor();
  const revokeButton = await screen.findByRole("button", {
    name: "Revoke access",
  });
  fireEvent.click(revokeButton);
  const dialog = screen.getByRole("alertdialog", {
    name: "Revoke guardian access",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Revoke access" }),
  );
  await waitFor(() =>
    expect(mocks.guardian.revokeGuardianRelationship).toHaveBeenCalledWith(
      "rel-a",
    ),
  );
  await screen.findByText("Guardian access revoked.");
  expect(
    screen.queryByText("Manage materials · mystery_permission"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("No active guardian relationships."),
  ).toBeInTheDocument();
});

it("closes the revoke dialog without calling the API on cancel", async () => {
  renderEditor();
  fireEvent.click(
    await screen.findByRole("button", { name: "Revoke access" }),
  );
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Cancel",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
  );
  expect(mocks.guardian.revokeGuardianRelationship).not.toHaveBeenCalled();
});

it("keeps the row and shows the error when revocation fails", async () => {
  mocks.guardian.revokeGuardianRelationship.mockRejectedValue(
    new Error("Already revoked"),
  );
  renderEditor();
  fireEvent.click(
    await screen.findByRole("button", { name: "Revoke access" }),
  );
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Revoke access",
    }),
  );
  await waitFor(() =>
    expect(screen.getByText("Already revoked")).toBeInTheDocument(),
  );
  expect(screen.getByText("Active Guardian")).toBeInTheDocument();
});

it("resets learner credentials only for a confirmed eight-character password", async () => {
  mocks.guardian.resetLearnerCredentials.mockResolvedValue(undefined);
  renderEditor();
  await screen.findByText("Active Guardian");
  const resetButton = screen.getByRole("button", {
    name: "Reset learner credentials",
  });
  const passwordInput = screen.getByLabelText("New learner password");
  expect(resetButton).toBeDisabled();
  fireEvent.change(passwordInput, { target: { value: "short" } });
  expect(resetButton).toBeDisabled();
  fireEvent.change(passwordInput, { target: { value: "long-enough-1" } });
  expect(resetButton).toBeEnabled();
  fireEvent.click(resetButton);
  const dialog = screen.getByRole("alertdialog", {
    name: "Reset learner credentials",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Reset credentials" }),
  );
  await waitFor(() =>
    expect(mocks.guardian.resetLearnerCredentials).toHaveBeenCalledWith(
      "l1",
      "long-enough-1",
    ),
  );
  await screen.findByText("Learner credentials were reset.");
  expect(passwordInput).toHaveValue("");
});

it("reports credential reset failures instead of a success message", async () => {
  mocks.guardian.resetLearnerCredentials.mockRejectedValue(
    new Error("Reset failed"),
  );
  renderEditor();
  await screen.findByText("Active Guardian");
  fireEvent.change(screen.getByLabelText("New learner password"), {
    target: { value: "long-enough-1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Reset learner credentials" }),
  );
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Reset credentials",
    }),
  );
  await waitFor(() =>
    expect(screen.getByText("Reset failed")).toBeInTheDocument(),
  );
  expect(
    screen.queryByText("Learner credentials were reset."),
  ).not.toBeInTheDocument();
});
