import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PersonaSelector from "@/components/chat/home/PersonaSelector";
import { listPersonas, type PersonaInfo } from "@/lib/personas-api";
import { initI18n } from "@/i18n/init";

initI18n("en");

vi.mock("@/lib/personas-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/personas-api")>()),
  listPersonas: vi.fn(async (): Promise<PersonaInfo[]> => []),
}));

const listPersonasMock = vi.mocked(listPersonas);

const personas: PersonaInfo[] = [
  {
    name: "Alpha Persona",
    description: "Depth-first explorer",
    source: "user",
    read_only: false,
  },
  {
    name: "Beta Persona",
    description: "Exam coach",
    source: "admin",
    read_only: true,
  },
];

beforeEach(() => {
  listPersonasMock.mockResolvedValue([...personas]);
});

describe("PersonaSelector", () => {
  it("lazily loads the persona list on first open and marks admin presets", async () => {
    render(<PersonaSelector value="" onChange={vi.fn()} />);
    expect(listPersonasMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    expect(await screen.findByText("Alpha Persona")).toBeInTheDocument();
    expect(screen.getByText("Beta Persona")).toBeInTheDocument();
    expect(screen.getAllByText("Preset")).toHaveLength(1);
    expect(listPersonasMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    expect(listPersonasMock).toHaveBeenCalledTimes(1);
  });

  it("selecting a persona reports the name and closes the menu", async () => {
    const onChange = vi.fn();
    render(<PersonaSelector value="" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    fireEvent.click(await screen.findByText("Beta Persona"));
    expect(onChange).toHaveBeenCalledWith("Beta Persona");
    expect(
      screen.getByRole("button", { name: "Select persona" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("the default row resets the selection to no persona", async () => {
    const onChange = vi.fn();
    render(<PersonaSelector value="Beta Persona" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    fireEvent.click(await screen.findByText("Default"));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("search filters rows and shows the empty state when nothing matches", async () => {
    render(<PersonaSelector value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    const search = await screen.findByPlaceholderText("Search personas...");
    fireEvent.change(search, { target: { value: "exam" } });
    expect(screen.getByText("Beta Persona")).toBeInTheDocument();
    expect(screen.queryByText("Alpha Persona")).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(
      screen.getByText("No personas match this search."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No persona — the assistant's standard behavior"),
    ).not.toBeInTheDocument();
  });

  it("keeps the default row reachable when the persona list fails to load", async () => {
    listPersonasMock.mockRejectedValueOnce(new Error("offline"));
    render(<PersonaSelector value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Select persona" }));
    expect(
      await screen.findByText("No persona — the assistant's standard behavior"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No personas match this search."),
    ).not.toBeInTheDocument();
  });

  it("supports controlled open state and escape-to-close", async () => {
    const onOpenChange = vi.fn();
    render(
      <PersonaSelector
        value=""
        onChange={vi.fn()}
        open
        onOpenChange={onOpenChange}
      />,
    );
    const search = await screen.findByPlaceholderText("Search personas...");
    fireEvent.keyDown(search, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
