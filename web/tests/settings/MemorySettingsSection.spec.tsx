import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MemorySettingsPage from "@/features/settings/sections/MemorySettingsSection";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

interface MemoryEdit {
  dirty: boolean;
  save: () => Promise<void>;
  payload: unknown;
}

const staged = vi.hoisted(() => {
  const edits = new Map<string, MemoryEdit>();
  const pending = new Map<string, unknown>();
  return {
    edits,
    pending,
    registerExtension: vi.fn(
      (key: string, edit: MemoryEdit | null) => {
        if (edit === null) edits.delete(key);
        else edits.set(key, edit);
      },
    ),
    pendingExtensionPayload: (key: string) => pending.get(key),
  };
});

vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => ({
    registerExtension: staged.registerExtension,
    pendingExtensionPayload: staged.pendingExtensionPayload,
    draftRevision: 0,
  }),
}));

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => fetchMock(...args),
}));

const memoryDTO = {
  update: { l2_budget: 8, l3_budget: 4 },
  audit: { l2_budget: 6, l3_budget: 3 },
  dedup: { iterations: 2, auto_after_update: false },
  merge: {
    auto_after_update: true,
    auto_after_audit: false,
    auto_after_dedup: false,
  },
  chunking: {
    overlap_ratio: 0.1,
    boundary: "paragraph" as const,
    min_chunk_chars: 800,
    max_chunk_chars: 3200,
  },
  reference: { enforce_required: true, drop_invalid_refs: false },
};

const reply = (value: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => value,
});

/** The SettingSection that renders the given heading text. */
function sectionOf(title: string): HTMLElement {
  return screen.getByText(title).closest("section") as HTMLElement;
}

/** The SettingRow root that renders the given row title inside `scope`. */
function rowOf(scope: HTMLElement, label: string): HTMLElement {
  const title = within(scope).getByText(label);
  return title.parentElement?.parentElement as HTMLElement;
}

function numberRow(label: string, scope: HTMLElement): HTMLInputElement {
  return within(rowOf(scope, label)).getByRole(
    "spinbutton",
  ) as HTMLInputElement;
}

function lastRegistration(): MemoryEdit | undefined {
  const calls = staged.registerExtension.mock.calls.filter(
    ([key]) => key === "memory",
  );
  return calls.length ? calls[calls.length - 1][1] ?? undefined : undefined;
}

beforeEach(() => {
  staged.edits.clear();
  staged.pending.clear();
  fetchMock.mockReset().mockResolvedValue(reply(memoryDTO));
});

describe("MemorySettingsSection", () => {
  it("loads server settings into the form fields", async () => {
    render(<MemorySettingsPage />);

    expect(await screen.findByText("Update mode")).toBeInTheDocument();
    const update = sectionOf("Update mode");
    expect(numberRow("L2 budget (per surface)", update).value).toBe("8");
    expect(numberRow("L3 budget (per slot)", update).value).toBe("4");

    const dedup = sectionOf("Dedup");
    expect(numberRow("Iterations", dedup).value).toBe("2");

    const chunking = sectionOf("Chunking");
    expect(numberRow("Overlap ratio", chunking).value).toBe("0.1");
    expect(numberRow("Min chunk chars", chunking).value).toBe("800");
    expect(
      within(chunking).getByRole("button", { name: "Paragraph" }),
    ).toHaveClass("font-medium");

    const reference = sectionOf("References");
    expect(
      within(rowOf(reference, "Require ref on every fact")).getByRole(
        "switch",
      ),
    ).toHaveAttribute("aria-checked", "true");

    await waitFor(() => {
      const ext = staged.edits.get("memory");
      expect(ext?.dirty).toBe(false);
      expect(ext?.payload).toEqual(memoryDTO);
    });
  });

  it("prefers a pending extension payload over the server snapshot", async () => {
    const pendingDTO = {
      ...memoryDTO,
      update: { ...memoryDTO.update, l2_budget: 64 },
    };
    staged.pending.set("memory", pendingDTO);

    render(<MemorySettingsPage />);

    await screen.findByText("Update mode");
    const update = sectionOf("Update mode");
    await waitFor(() => {
      expect(numberRow("L2 budget (per surface)", update).value).toBe("64");
    });
    await waitFor(() => {
      expect(staged.edits.get("memory")?.dirty).toBe(true);
      expect(staged.edits.get("memory")?.payload).toEqual(pendingDTO);
    });
  });

  it("surfaces the loading spinner before settings arrive", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));

    render(<MemorySettingsPage />);

    expect(document.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("Update mode")).not.toBeInTheDocument();
  });

  it("renders the error branch when loading fails", async () => {
    fetchMock.mockResolvedValue(reply({}, false, 500));

    render(<MemorySettingsPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Failed to load settings. HTTP 500");
    expect(screen.queryByText("Update mode")).not.toBeInTheDocument();
  });

  it("marks the draft dirty and patches the payload on edit", async () => {
    render(<MemorySettingsPage />);
    await screen.findByText("Update mode");
    const update = sectionOf("Update mode");
    await waitFor(() => expect(staged.edits.get("memory")?.dirty).toBe(false));

    fireEvent.change(numberRow("L2 budget (per surface)", update), {
      target: { value: "12" },
    });

    await waitFor(() => {
      const ext = staged.edits.get("memory");
      expect(ext?.dirty).toBe(true);
      expect(ext?.payload).toMatchObject({
        update: { l2_budget: 12, l3_budget: 4 },
      });
    });
  });

  it("ignores empty number input instead of NaN", async () => {
    render(<MemorySettingsPage />);
    await screen.findByText("Update mode");
    const update = sectionOf("Update mode");
    await waitFor(() => expect(staged.edits.size).toBeGreaterThan(0));

    fireEvent.change(numberRow("L2 budget (per surface)", update), {
      target: { value: "" },
    });

    const ext = staged.edits.get("memory");
    expect(ext?.payload).toMatchObject({
      update: { l2_budget: 8, l3_budget: 4 },
    });
  });

  it("flips toggles and the boundary selector through the payload", async () => {
    render(<MemorySettingsPage />);
    await screen.findByText("Dedup");

    const dedupSwitch = within(
      rowOf(sectionOf("Dedup"), "Run dedup automatically after Update"),
    ).getByRole("switch");
    expect(dedupSwitch).toHaveAttribute("aria-checked", "false");
    fireEvent.click(dedupSwitch);

    await waitFor(() => {
      expect(staged.edits.get("memory")?.payload).toMatchObject({
        dedup: { iterations: 2, auto_after_update: true },
      });
    });

    fireEvent.click(
      within(sectionOf("Chunking")).getByRole("button", {
        name: "Sentence",
      }),
    );

    await waitFor(() => {
      expect(staged.edits.get("memory")?.payload).toMatchObject({
        chunking: { boundary: "sentence" },
      });
    });
  });

  it("save PUTs the draft and re-syncs from the server response", async () => {
    render(<MemorySettingsPage />);
    await screen.findByText("Update mode");
    const update = sectionOf("Update mode");
    await waitFor(() => expect(staged.edits.get("memory")?.dirty).toBe(false));

    fireEvent.change(numberRow("L2 budget (per surface)", update), {
      target: { value: "12" },
    });
    await waitFor(() =>
      expect(staged.edits.get("memory")?.dirty).toBe(true),
    );

    const normalized = {
      ...memoryDTO,
      update: { ...memoryDTO.update, l2_budget: 16 },
    };
    fetchMock.mockResolvedValue(reply(normalized));

    await act(async () => {
      await staged.edits.get("memory")?.save();
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/memory/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...memoryDTO,
        update: { ...memoryDTO.update, l2_budget: 12 },
      }),
    });
    await waitFor(() => {
      expect(
        numberRow("L2 budget (per surface)", update).value,
      ).toBe("16");
      expect(lastRegistration()?.dirty).toBe(false);
    });
  });

  it("save rejects with the HTTP status when the PUT fails", async () => {
    render(<MemorySettingsPage />);
    await waitFor(() => expect(staged.edits.get("memory")?.dirty).toBe(false));

    const update = sectionOf("Update mode");
    fireEvent.change(numberRow("L2 budget (per surface)", update), {
      target: { value: "12" },
    });
    await waitFor(() =>
      expect(staged.edits.get("memory")?.dirty).toBe(true),
    );

    fetchMock.mockResolvedValue(reply({}, false, 500));
    await expect(staged.edits.get("memory")?.save()).rejects.toThrow(
      "HTTP 500",
    );
  });
});
