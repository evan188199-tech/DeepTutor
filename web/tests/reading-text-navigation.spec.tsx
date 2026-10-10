import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TextUnitView } from "@/components/reading/TextUnitView";
import { getMaterialMedia, getUnitText } from "@/lib/reading-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (value: string, options?: { unit?: string }) =>
      value.replace("{{unit}}", options?.unit ?? ""),
  }),
}));
vi.mock("@/lib/reading-api", () => ({
  getUnitText: vi.fn(),
  getMaterialMedia: vi.fn(),
  materialMediaUrl: vi.fn(),
}));
vi.mock("@/components/common/RichMarkdownRenderer", () => ({ default: () => null }));
vi.mock("@recogito/text-annotator", () => ({
  createTextAnnotator: () => ({ destroy: vi.fn(), setAnnotations: vi.fn(), on: vi.fn() }),
}));

describe("Markdown section navigation (#1641)", () => {
  beforeEach(() => {
    vi.mocked(getMaterialMedia).mockResolvedValue([]);
  });

  it.each([true, false])("reaches the final unit and returns with headings=%s", async (headings) => {
    const units = [
      (headings ? "# Opening\n\n" : "") + "Opening paragraph.",
      "````markdown\n```python\n# This is code\n```\n````\nMiddle paragraph.",
      (headings ? "## Last section\n\n" : "") + "END OF DOCUMENT",
    ];
    vi.mocked(getUnitText).mockImplementation(async (_id, locator) => ({
      locator, unit: "section", text: units[locator - 1],
    }));
    const user = userEvent.setup();
    render(<TextUnitView materialId="long-markdown" unit="section" unitCount={units.length}
      annotations={[]} jump={null} onSelection={vi.fn()} />);

    await screen.findByText("Opening paragraph.");
    expect(screen.getByRole("button", { name: "Previous Section" })).toBeDisabled();
    for (let locator = 2; locator <= units.length; locator++) {
      await user.click(screen.getByRole("button", { name: "Next Section" }));
      await waitFor(() => expect(getUnitText).toHaveBeenLastCalledWith("long-markdown", locator));
      await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
    }
    await screen.findByText("END OF DOCUMENT");
    expect(screen.getByRole("button", { name: "Next Section" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Previous Section" }));
    await waitFor(() => expect(screen.getByRole("article")).toHaveTextContent("Middle paragraph."));
    expect(screen.getByRole("button", { name: "Next Section" })).toBeEnabled();
  });
});

describe("Markdown pagination visible in narrow panels (#1641)", () => {
  beforeEach(() => {
    vi.mocked(getMaterialMedia).mockResolvedValue([]);
  });

  it("keeps the section buttons outside the scrolling display-controls strip", async () => {
    vi.mocked(getUnitText).mockImplementation(async (_id, locator) => ({
      locator, unit: "section", text: `Section ${locator} body.`,
    }));
    render(<TextUnitView materialId="narrow-markdown" unit="section" unitCount={3}
      annotations={[]} jump={null} onSelection={vi.fn()} />);

    await screen.findByText("Section 1 body.");
    const next = screen.getByRole("button", { name: "Next Section" });
    const previous = screen.getByRole("button", { name: "Previous Section" });

    // button -> tooltip wrapper span -> the pagination group.
    const group = next.parentElement!.parentElement as HTMLElement;
    expect(group).toContainElement(previous);
    expect(group.className).toContain("shrink-0");

    const row = group.parentElement as HTMLElement;
    // The row itself never scrolls: the whole toolbar sliding out of view is
    // how the way to turn a page used to disappear in a narrow panel.
    expect(row.className).toContain("shrink-0");
    expect(row.className).not.toContain("overflow-x-auto");

    // Display controls scroll in their own lane, shrinking before the
    // pagination group ever has to.
    const scroller = row.firstElementChild as HTMLElement;
    expect(group).not.toContainElement(scroller);
    expect(scroller).toBe(group.previousElementSibling);
    expect(scroller.className).toContain("min-w-0");
    expect(scroller.className).toContain("flex-1");
    expect(scroller.className).toContain("overflow-x-auto");
  });
});
