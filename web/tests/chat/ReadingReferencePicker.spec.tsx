import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import ReadingReferencePicker from "@/components/chat/ReadingReferencePicker";
import type { MaterialDetail, MaterialInfo } from "@/lib/reading-api";
import type { SelectedReadingReference } from "@/lib/reading-references";
import { initI18n } from "@/i18n/init";

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/reading-api", () => ({ listMaterials: api.list, getMaterial: api.get }));
vi.mock("@/components/common/PickerShell", () => ({
  default: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
}));
initI18n("en");

function makeMaterial(id: string, title: string, filename: string, unitCount: number, revision?: number): MaterialInfo {
  return {
    material_id: id,
    filename,
    unit: "page",
    unit_count: unitCount,
    mime: "application/pdf",
    title,
    byte_size: 100,
    char_count: 100,
    created_at: 0,
    has_raw_view: true,
    render_mode: "text",
    extractor: "pdf",
    annotation_count: 0,
    ...(revision === undefined ? {} : { revision }),
  };
}

function makeDetail(material: MaterialInfo, outline: Array<{ locator: number; title: string }>, unitRefs: Array<{ locator: number; title: string }>): MaterialDetail {
  return {
    ...material,
    outline: outline.map((row) => ({ locator: row.locator, title: row.title, level: 1, synthesised: false })),
    outline_text: "",
    unit_refs: unitRefs.map((row) => ({ locator: row.locator, source_href: "", title: row.title })),
  };
}

const materialA = makeMaterial("mat_a", "Cell Biology", "cells.pdf", 3, 2);
const materialB = makeMaterial("mat_b", "Physics Notes", "physics.md", 2);
const detailA = makeDetail(
  materialA,
  [
    { locator: 1, title: "Intro" },
    { locator: 2, title: "  " },
    { locator: 3, title: "Methods" },
  ],
  [{ locator: 2, title: "Membranes" }],
);
const detailB = makeDetail(materialB, [{ locator: 1, title: "Motion" }, { locator: 2, title: "Waves" }], []);

function seeded(materialId: string, revision: number, locators: number[]): SelectedReadingReference {
  return {
    materialId,
    revision,
    materialTitle: materialId,
    unit: "page",
    units: locators.map((locator) => ({ locator, title: `Seeded ${locator}` })),
  };
}

function viewPicker(initial: SelectedReadingReference[] = [], onApply = vi.fn(), onClose = vi.fn()) {
  return render(<ReadingReferencePicker open initialReferences={initial} onClose={onClose} onApply={onApply} />);
}

it("renders materials and resolves unit titles from the outline and unit refs", async () => {
  api.list.mockResolvedValue([materialA, materialB]);
  api.get.mockResolvedValue(detailA);
  viewPicker();
  expect(await screen.findByRole("button", { name: /Intro/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Cell Biology/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Physics Notes/ })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Cell Biology" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Membranes/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Methods/ })).toBeTruthy();
  expect(screen.getAllByText("page 3").length).toBeGreaterThan(0);
});

it("filters materials by title and filename and shows the empty state", async () => {
  api.list.mockResolvedValue([materialA, materialB]);
  api.get.mockResolvedValue(detailA);
  viewPicker();
  await screen.findByRole("button", { name: /Intro/ });
  fireEvent.change(screen.getByPlaceholderText("Search reading materials"), { target: { value: "physics" } });
  expect(screen.getByRole("button", { name: /Physics Notes/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Cell Biology/ })).toBeNull();
  fireEvent.change(screen.getByPlaceholderText("Search reading materials"), { target: { value: "cells.pdf" } });
  expect(screen.getByRole("button", { name: /Cell Biology/ })).toBeTruthy();
  fireEvent.change(screen.getByPlaceholderText("Search reading materials"), { target: { value: "zzz" } });
  expect(await screen.findByText("No reading materials found.")).toBeTruthy();
});

it("shows a spinner while materials load and an alert when listing fails", async () => {
  let rejectList!: (cause: Error) => void;
  api.list.mockReturnValue(new Promise((_resolve, reject) => { rejectList = reject; }));
  const { container } = viewPicker();
  expect(container.querySelector(".animate-spin")).toBeTruthy();
  await act(async () => {
    rejectList(new Error("boom"));
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  expect(screen.getByText("No reading materials found.")).toBeTruthy();
});

it("toggles units on and off, then applies the payload with material metadata", async () => {
  api.list.mockResolvedValue([materialA]);
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  const onClose = vi.fn();
  viewPicker([], onApply, onClose);
  fireEvent.click(await screen.findByRole("button", { name: /Intro/ }));
  expect(screen.getByText("1 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Methods/ }));
  expect(screen.getByText("2 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Intro/ }));
  expect(screen.getByText("1 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(onApply).toHaveBeenCalledExactlyOnceWith([
    {
      materialId: "mat_a",
      revision: 2,
      materialTitle: "Cell Biology",
      unit: "page",
      units: [{ locator: 3, title: "Methods" }],
    },
  ]);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("Select all is dedupe-safe against seeded units and Clear material removes them", async () => {
  api.list.mockResolvedValue([materialA]);
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  viewPicker([seeded("mat_a", 2, [1])], onApply);
  await screen.findByRole("button", { name: /Membranes/ });
  expect(screen.getByText("1 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(screen.getByText("3 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(onApply.mock.calls[0][0][0].units.map((unit: { locator: number }) => unit.locator)).toEqual([1, 2, 3]);
  fireEvent.click(screen.getByRole("button", { name: "Clear material" }));
  expect(screen.getByText("No reading sections selected")).toBeTruthy();
});

it("caps total units and reports a partial selection", async () => {
  const busy = makeMaterial("mat_busy", "Workbook", "workbook.pdf", 22);
  api.list.mockResolvedValue([materialA, busy]);
  api.get.mockResolvedValue(detailA);
  viewPicker([seeded("mat_busy", 1, Array.from({ length: 22 }, (_, index) => index + 1))]);
  await screen.findByRole("button", { name: /Select all/ });
  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Only the first 2 available sections were selected.");
  expect(screen.getByText("24 reading sections selected")).toBeTruthy();
});

it("rejects a ninth material with the materials cap alert", async () => {
  const materials = Array.from({ length: 9 }, (_, index) => makeMaterial(`m${index + 1}`, `Volume ${index + 1}`, `v${index + 1}.pdf`, 2, 1));
  api.list.mockResolvedValue(materials);
  api.get.mockResolvedValue(makeDetail(materials[8], [{ locator: 1, title: "Opening" }, { locator: 2, title: "Closing" }], []));
  viewPicker(materials.slice(0, 8).map((material) => seeded(material.material_id, 1, [1])));
  fireEvent.click(await screen.findByRole("button", { name: /Volume 9/ }));
  fireEvent.click(await screen.findByRole("button", { name: /Opening/ }));
  expect(screen.getByRole("alert")).toHaveTextContent("You can reference up to 8 reading materials at once.");
  expect(screen.getByText("8 reading sections selected")).toBeTruthy();
});

it("Clear empties a seeded selection and Apply sends an empty list", async () => {
  api.list.mockResolvedValue([materialA]);
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  viewPicker([seeded("mat_a", 2, [1, 3])], onApply);
  await screen.findByRole("button", { name: /Membranes/ });
  expect(screen.getByText("2 reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getByText("No reading sections selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(onApply).toHaveBeenCalledExactlyOnceWith([]);
});

it("Close dismisses the picker without applying", async () => {
  api.list.mockResolvedValue([materialA]);
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  const onClose = vi.fn();
  viewPicker([], onApply, onClose);
  await screen.findByRole("button", { name: /Intro/ });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onApply).not.toHaveBeenCalled();
});

it("empty library shows the empty list state and the detail placeholder", async () => {
  api.list.mockResolvedValue([]);
  viewPicker();
  expect(await screen.findByText("No reading materials found.")).toBeTruthy();
  expect(screen.getByText("Select a reading material to view sections.")).toBeTruthy();
});
