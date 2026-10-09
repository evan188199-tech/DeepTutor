import { describe, expect, it } from "vitest";

import {
  getTypeColor,
  type Notebook,
  type NotebookRecord,
  type SelectedRecord,
} from "@/lib/notebook-selection-types";

const DEFAULT_PALETTE = "bg-slate-100 text-slate-700 border-slate-200";

const PALETTES: Record<string, string> = {
  solve: "bg-blue-100 text-blue-700 border-blue-200",
  question: "bg-purple-100 text-purple-700 border-purple-200",
  research: "bg-emerald-100 text-emerald-700 border-emerald-200",
  chat: "bg-cyan-100 text-cyan-700 border-cyan-200",
  co_writer: "bg-amber-100 text-amber-700 border-amber-200",
};

function makeNotebookRecord(overrides: Partial<NotebookRecord> = {}): NotebookRecord {
  return {
    id: "rec-1",
    title: "Integration by parts",
    summary: "A worked example.",
    user_query: "How does integration by parts work?",
    output: "Choose u and dv, then apply the formula.",
    type: "solve",
    ...overrides,
  };
}

function makeSelectedRecord(overrides: Partial<SelectedRecord> = {}): SelectedRecord {
  return {
    ...makeNotebookRecord(),
    notebookId: "nb-1",
    notebookName: "Calculus",
    ...overrides,
  };
}

describe("getTypeColor", () => {
  it("maps every known record type to its palette classes", () => {
    for (const [type, palette] of Object.entries(PALETTES)) {
      expect(getTypeColor(type)).toBe(palette);
    }
  });

  it("falls back to the slate palette for unknown record types", () => {
    expect(getTypeColor("unknown-type")).toBe(DEFAULT_PALETTE);
  });

  it("falls back to the slate palette for empty and whitespace-only labels", () => {
    expect(getTypeColor("")).toBe(DEFAULT_PALETTE);
    expect(getTypeColor("   ")).toBe(DEFAULT_PALETTE);
  });

  it("matches record types case-sensitively", () => {
    expect(getTypeColor("SOLVE")).toBe(DEFAULT_PALETTE);
    expect(getTypeColor("Solve")).toBe(DEFAULT_PALETTE);
  });

  it("is deterministic across repeated lookups", () => {
    expect(getTypeColor("solve")).toBe(getTypeColor("solve"));
    expect(getTypeColor("nope")).toBe(getTypeColor("nope"));
    expect(getTypeColor("nope")).toBe(DEFAULT_PALETTE);
  });
});

describe("selection record contracts", () => {
  it("keeps SelectedRecord identity fields alongside the wrapped record", () => {
    const selected = makeSelectedRecord();

    expect(selected.notebookId).toBe("nb-1");
    expect(selected.notebookName).toBe("Calculus");
    expect(selected.id).toBe("rec-1");
    expect(selected.title).toBe("Integration by parts");
    expect(selected.user_query).toBe("How does integration by parts work?");
    expect(selected.output).toBe("Choose u and dv, then apply the formula.");
    expect(selected.type).toBe("solve");
  });

  it("treats the record summary as optional", () => {
    const withSummary = makeSelectedRecord();
    const withoutSummary = makeSelectedRecord({ summary: undefined });
    const bare = { ...makeNotebookRecord({ summary: undefined }), notebookId: "nb-2", notebookName: "Algebra" };

    expect(withSummary.summary).toBe("A worked example.");
    expect(withoutSummary.summary).toBeUndefined();
    expect((bare as SelectedRecord).summary).toBeUndefined();
  });

  it("keeps Notebook metadata fields intact", () => {
    const notebook: Notebook = {
      id: "nb-9",
      name: "Physics",
      description: "Mechanics notes",
      record_count: 12,
      color: "#123456",
    };

    expect(notebook.id).toBe("nb-9");
    expect(notebook.name).toBe("Physics");
    expect(notebook.description).toBe("Mechanics notes");
    expect(notebook.record_count).toBe(12);
    expect(notebook.color).toBe("#123456");
  });
});
