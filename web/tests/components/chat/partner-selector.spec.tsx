import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PartnerSelector from "@/components/chat/home/PartnerSelector";
import type { PartnerInfo } from "@/lib/partners-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const partner = (id: string, name: string): PartnerInfo =>
  ({
    partner_id: id,
    name,
    emoji: "🦉",
    color: "#4f7a5b",
  }) as PartnerInfo;

const partners = [partner("p1", "Owl"), partner("p2", "Fox")];

function renderSelector(
  overrides: Partial<Parameters<typeof PartnerSelector>[0]> = {},
) {
  const onSelect = vi.fn();
  render(
    <PartnerSelector
      partners={partners}
      selected={null}
      onSelect={onSelect}
      loading={false}
      error={false}
      {...overrides}
    />,
  );
  return { onSelect };
}

describe("PartnerSelector", () => {
  it("shows the loading state", () => {
    renderSelector({ loading: true });
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("No partners yet")).toBeNull();
  });

  it("shows the error state as an alert", () => {
    renderSelector({ error: true });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not load partners",
    );
  });

  it("shows the empty state only when loaded without partners", () => {
    renderSelector({ partners: [] });
    expect(screen.getByText("No partners yet")).toBeInTheDocument();
  });

  it("lists every partner with rows and a None entry", () => {
    renderSelector();
    expect(screen.getByRole("button", { name: "Owl" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fox" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "None" })).toBeInTheDocument();
  });

  it("marks only the selected partner as pressed", () => {
    renderSelector({ selected: "p2" });
    expect(
      screen.getByRole("button", { name: "Owl" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: "Fox" }),
    ).toHaveAttribute("aria-pressed", "true");
    // "None" is unselected: no check marker next to it (aria-pressed absent).
    expect(screen.getByRole("button", { name: "None" })).not.toHaveAttribute(
      "aria-pressed",
    );
  });

  it("selects a partner with its id", () => {
    const { onSelect } = renderSelector();
    fireEvent.click(screen.getByRole("button", { name: "Fox" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("p2");
  });

  it("clears the selection via None", () => {
    const { onSelect } = renderSelector({ selected: "p1" });
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("links to the partners management page", () => {
    renderSelector();
    const link = screen.getByRole("link", { name: "Partners" });
    expect(link).toHaveAttribute("href", "/partners");
  });
});
