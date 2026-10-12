import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import PersonaPicker from "@/components/chat/PersonaPicker";
import { listPersonas, type PersonaInfo } from "@/lib/personas-api";
import { initI18n } from "@/i18n/init";

vi.mock("@/components/common/PickerShell", () => ({
  default: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
}));
vi.mock("@/lib/personas-api", () => ({
  listPersonas: vi.fn(async () => []),
}));

initI18n("en");

const persona = (
  name: string,
  description = "",
  source: PersonaInfo["source"] = "user",
): PersonaInfo => ({
  name,
  description,
  source,
  read_only: source === "admin",
});

const renderPicker = (
  props: Partial<Parameters<typeof PersonaPicker>[0]> = {},
) => {
  const onApply = vi.fn();
  const onClose = vi.fn();
  const view = render(
    <PersonaPicker
      open
      initialPersona={null}
      onClose={onClose}
      onApply={onApply}
      {...props}
    />,
  );
  return { onApply, onClose, view };
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPersonas).mockResolvedValue([]);
});

it("loads personas with the initial selection applied and marks admin presets", async () => {
  vi.mocked(listPersonas).mockResolvedValue([
    persona("Alpha", "Alpha tutor"),
    persona("Beta", "Beta tutor", "admin"),
  ]);
  const { onApply, onClose } = renderPicker({ initialPersona: "Alpha" });

  expect(await screen.findByText("Alpha")).toBeInTheDocument();
  expect(screen.getByText("Beta")).toBeInTheDocument();
  expect(screen.getByText("preset")).toBeInTheDocument();
  expect(screen.getByText("Persona: Alpha")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Use Persona" })).toBeInTheDocument();
  expect(listPersonas).toHaveBeenCalledWith({ force: true });

  fireEvent.click(screen.getByRole("button", { name: "Use Persona" }));
  expect(onApply).toHaveBeenLastCalledWith("Alpha");
  expect(onClose).toHaveBeenCalledOnce();
});

it("switches the selection to a clicked persona and reports it on apply", async () => {
  vi.mocked(listPersonas).mockResolvedValue([
    persona("Alpha"),
    persona("Beta"),
  ]);
  const { onApply, onClose } = renderPicker({ initialPersona: "Alpha" });

  fireEvent.click(await screen.findByRole("button", { name: /Beta/ }));
  expect(screen.getByText("Persona: Beta")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Use Persona" }));
  expect(onApply).toHaveBeenLastCalledWith("Beta");
  expect(onClose).toHaveBeenCalledOnce();
});

it("reverts to the no-persona choice and applies null with the default label", async () => {
  vi.mocked(listPersonas).mockResolvedValue([persona("Alpha")]);
  const { onApply } = renderPicker({ initialPersona: "Alpha" });
  await screen.findByText("Alpha");

  fireEvent.click(screen.getByRole("button", { name: /No persona/ }));
  expect(screen.getByText("No persona selected")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Continue without persona" }),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Continue without persona" }));
  expect(onApply).toHaveBeenLastCalledWith(null);
});

it("filters personas by name and description keywords", async () => {
  vi.mocked(listPersonas).mockResolvedValue([
    persona("Alpha", "loves chess puzzles"),
    persona("Beta", "loves math drills"),
  ]);
  renderPicker();
  await screen.findByText("Alpha");

  fireEvent.change(screen.getByPlaceholderText("Search personas by name or description"), {
    target: { value: "math" },
  });
  expect(screen.getByText("Beta")).toBeInTheDocument();
  expect(screen.queryByText("Alpha")).not.toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("Search personas by name or description"), {
    target: { value: "alpha" },
  });
  expect(screen.getByText("Alpha")).toBeInTheDocument();
  expect(screen.queryByText("Beta")).not.toBeInTheDocument();
});

it("shows the no-match message for queries without hits and recovers after clearing", async () => {
  vi.mocked(listPersonas).mockResolvedValue([persona("Alpha")]);
  renderPicker();
  await screen.findByText("Alpha");

  fireEvent.change(screen.getByPlaceholderText("Search personas by name or description"), {
    target: { value: "nothing-matches" },
  });
  expect(screen.getByText("No matching personas found.")).toBeInTheDocument();
  expect(screen.queryByText("Alpha")).not.toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("Search personas by name or description"), {
    target: { value: "   " },
  });
  expect(screen.queryByText("No matching personas found.")).not.toBeInTheDocument();
  expect(screen.getByText("Alpha")).toBeInTheDocument();
});

it("shows the empty state when the account has no personas", async () => {
  renderPicker();
  expect(await screen.findByText("No personas yet")).toBeInTheDocument();
  expect(screen.queryByText("No matching personas found.")).not.toBeInTheDocument();
});

it("keeps the picker operable when loading personas fails", async () => {
  vi.mocked(listPersonas).mockRejectedValueOnce(new Error("network down"));
  const { onApply } = renderPicker();

  expect(await screen.findByText("No personas yet")).toBeInTheDocument();
  expect(document.querySelector(".animate-spin")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Continue without persona" }));
  expect(onApply).toHaveBeenLastCalledWith(null);
});

it("shows the loading indicator until the persona list resolves", async () => {
  let resolveList: (items: PersonaInfo[]) => void = () => {};
  vi.mocked(listPersonas).mockImplementation(
    () =>
      new Promise<PersonaInfo[]>((resolve) => {
        resolveList = resolve;
      }),
  );
  renderPicker();

  expect(document.querySelector(".animate-spin")).not.toBeNull();
  expect(screen.queryByText("No personas yet")).not.toBeInTheDocument();

  await act(async () => {
    resolveList([persona("Alpha")]);
  });
  expect(await screen.findByText("Alpha")).toBeInTheDocument();
  expect(document.querySelector(".animate-spin")).toBeNull();
});

it("resets the query and re-syncs the selection every time the picker reopens", async () => {
  vi.mocked(listPersonas).mockResolvedValue([
    persona("Alpha"),
    persona("Beta"),
  ]);
  const { view } = renderPicker({ initialPersona: "Alpha" });
  await screen.findByText("Alpha");

  fireEvent.change(screen.getByPlaceholderText("Search personas by name or description"), {
    target: { value: "alpha" },
  });
  expect(screen.queryByText("Beta")).not.toBeInTheDocument();

  view.rerender(
    <PersonaPicker open={false} initialPersona="Alpha" onClose={vi.fn()} onApply={vi.fn()} />,
  );
  view.rerender(
    <PersonaPicker open initialPersona="Beta" onClose={vi.fn()} onApply={vi.fn()} />,
  );

  expect(await screen.findByText("Persona: Beta")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });
  expect(
    screen.getByPlaceholderText("Search personas by name or description"),
  ).toHaveValue("");
  expect(screen.getByText("Alpha")).toBeInTheDocument();
});
