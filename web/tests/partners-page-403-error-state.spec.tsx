import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import PartnersPage from "@/app/(workspace)/partners/page";

const api = vi.hoisted(() => ({
  listPartners: vi.fn(),
  listPartnerGroups: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children?: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/partners-api", () => ({
  listPartners: api.listPartners,
}));
vi.mock("@/lib/partner-groups-api", () => ({
  listPartnerGroups: api.listPartnerGroups,
  listDiscussionModes: vi.fn(),
}));

const forbidden = () =>
  Promise.reject(
    Object.assign(new Error("Request failed (403)"), { status: 403 }),
  );

// A forbidden roster read must render an error, not the "No partners yet"
// empty state (#1228 pattern).
it("renders an error instead of the empty state when the partner list is forbidden", async () => {
  api.listPartners.mockImplementation(forbidden);
  api.listPartnerGroups.mockImplementation(forbidden);

  render(<PartnersPage />);

  const alert = await screen.findByText("Could not load partners.");
  expect(alert).toHaveAttribute("role", "alert");
  expect(screen.queryByText("No partners yet")).toBeNull();
});

it("renders an error in the groups section when only group reads fail", async () => {
  api.listPartners.mockImplementation(() =>
    Promise.resolve([
      {
        partner_id: "p1",
        name: "Study Buddy",
        channels: ["telegram"],
        running: true,
        can_manage: true,
      },
    ]),
  );
  api.listPartnerGroups.mockImplementation(forbidden);

  render(<PartnersPage />);

  const alert = await screen.findByText("Could not load partner groups.");
  expect(alert).toHaveAttribute("role", "alert");
  expect(screen.getByText("Study Buddy")).toBeInTheDocument();
});
