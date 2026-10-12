import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemePreviewCard } from "@/components/settings/ThemePreviewCard";
import type { UiSettings } from "@/features/settings/store/SettingsStore";

type Theme = UiSettings["theme"];
type CardProps = Parameters<typeof ThemePreviewCard>[0];

function renderCard(overrides: Partial<CardProps> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <ThemePreviewCard
      theme="snow"
      label="Snow"
      selected={false}
      onSelect={onSelect}
      {...overrides}
    />,
  );
  return { onSelect, ...view };
}

describe("ThemePreviewCard – normal branches", () => {
  it("renders the label inside a pressable button", () => {
    renderCard({ label: "Cream" });
    const button = screen.getByRole("button", { name: "Cream" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toHaveAttribute("type", "button");
  });

  it("reports clicks back with the card's own theme id", () => {
    const themes: Theme[] = ["light", "snow", "dark", "glass"];
    for (const theme of themes) {
      const { onSelect, unmount } = renderCard({ theme, label: theme });
      fireEvent.click(screen.getByRole("button", { name: theme }));
      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledWith(theme);
      unmount();
    }
  });

  it("marks the selected card with aria-pressed and a check badge", () => {
    const { container } = renderCard({ selected: true });
    expect(screen.getByRole("button", { name: "Snow" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(container.querySelectorAll("svg")).toHaveLength(2);
  });

  it("previews every theme with its own palette colours", () => {
    const expected = {
      light: { bg: "#fdfcf9", primary: "#b0501e" },
      snow: { bg: "#ffffff", primary: "#2563eb" },
      dark: { bg: "#1a1918", primary: "#d4734b" },
      glass: { bg: "#0e0d1a", primary: "#a855f7" },
    } as const;
    for (const [theme, palette] of Object.entries(expected)) {
      const { container, unmount } = renderCard({ theme: theme as Theme });
      const preview = container.querySelector("svg");
      expect(preview).not.toBeNull();
      expect(
        preview?.querySelector(`rect[fill="${palette.bg}"]`),
      ).not.toBeNull();
      expect(
        preview?.querySelector(`circle[fill="${palette.primary}"]`),
      ).not.toBeNull();
      unmount();
    }
  });
});

describe("ThemePreviewCard – empty (unselected) branches", () => {
  it("keeps the unselected card free of a check badge", () => {
    const { container } = renderCard({ selected: false });
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    const label = screen.getByText("Snow");
    expect(label.className).toContain("text-[var(--muted-foreground)]");
  });
});

describe("ThemePreviewCard – failure branches", () => {
  it("fails loudly instead of previewing a mismatched palette for an unknown theme id", () => {
    const unknown = "nope" as unknown as Theme;
    expect(() => renderCard({ theme: unknown })).toThrow();
  });
});
