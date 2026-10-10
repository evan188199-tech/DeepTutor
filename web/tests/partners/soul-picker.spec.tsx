import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SoulPicker from "@/components/partners/SoulPicker";
import type { SoulSources, SoulSpec } from "@/lib/partners-api";

const fixture = vi.hoisted(() => ({
  getSoulSources: vi.fn(),
  createSoulTemplate: vi.fn(),
  isAdmin: false,
}));

vi.mock("@/lib/partners-api", () => ({
  getSoulSources: fixture.getSoulSources,
  createSoulTemplate: fixture.createSoulTemplate,
}));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({ isAdmin: fixture.isAdmin }),
}));
vi.mock("@/components/partners/SoulEditor", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (next: string) => void;
  }) => (
    <textarea
      aria-label="soul-editor"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  fixture.isAdmin = false;
});

const sources: SoulSources = {
  library: [
    { id: "stoic", name: "Stoic Sage", content: "# Stoic\n\nBe calm." },
    {
      id: "tutor",
      name: "Patient Tutor",
      content: "# Tutor\n\nExplain step by step.",
    },
  ],
  personas: [
    { name: "Research Rabbit", description: "digs deep", content: "# Rabbit" },
  ],
};

function Harness({ initial }: { initial: SoulSpec }) {
  const [value, setValue] = useState<SoulSpec>(initial);
  return <SoulPicker value={value} onChange={setValue} />;
}

it("loads soul sources and renders library chips on the library tab", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "library", id: "stoic" }} />);
  expect(await screen.findByRole("button", { name: "Stoic Sage" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Patient Tutor" })).toBeInTheDocument();
  expect(fixture.getSoulSources).toHaveBeenCalledTimes(1);
});

it("preselects the first library soul when the wizard value is untouched", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "default" }} />);
  const editor = await screen.findByRole("textbox", { name: "soul-editor" });
  await waitFor(() => expect(editor).toHaveValue("# Stoic\n\nBe calm."));
  expect(screen.getByRole("button", { name: "Soul library" })).toHaveClass("font-medium");
});

it("selects a library soul and echoes its content in the editor", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "library", id: "stoic" }} />);
  await screen.findByRole("button", { name: "Patient Tutor" });
  fireEvent.click(screen.getByRole("button", { name: "Patient Tutor" }));
  const editor = screen.getByRole("textbox", { name: "soul-editor" });
  await waitFor(() => expect(editor).toHaveValue("# Tutor\n\nExplain step by step."));
  expect(screen.getByRole("button", { name: "Patient Tutor" }).className).toContain(
    "border-[var(--primary)]",
  );
});

it("selects a persona and shows the persona copy note", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "library", id: "stoic" }} />);
  fireEvent.click(await screen.findByRole("button", { name: "Clone a persona" }));
  fireEvent.click(await screen.findByRole("button", { name: "Research Rabbit" }));
  expect(
    await screen.findByText(
      "The persona's markdown is copied into the partner — later edits to the persona won't affect it.",
    ),
  ).toBeInTheDocument();
  const editor = screen.getByRole("textbox", { name: "soul-editor" });
  await waitFor(() => expect(editor).toHaveValue("# Rabbit"));
});

it("shows empty states for both source lists", async () => {
  fixture.getSoulSources.mockResolvedValue({ library: [], personas: [] });
  render(<Harness initial={{ source: "default" }} />);
  expect(await screen.findByText("No soul templates yet.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clone a persona" }));
  expect(
    await screen.findByText("No personas in your chat workspace yet."),
  ).toBeInTheDocument();
});

it("falls back to empty lists when loading soul sources fails", async () => {
  fixture.getSoulSources.mockRejectedValue(new Error("offline"));
  render(<Harness initial={{ source: "default" }} />);
  expect(await screen.findByText("No soul templates yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Stoic Sage" })).not.toBeInTheDocument();
});

it("opens on the persona tab when the value already points at a persona", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "persona", id: "Research Rabbit" }} />);
  expect(await screen.findByRole("button", { name: "Research Rabbit" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clone a persona" })).toHaveClass("font-medium");
  expect(
    screen.queryByRole("button", { name: "Stoic Sage" }),
  ).not.toBeInTheDocument();
});

it("switching to custom empties the draft and typing detaches a custom copy", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "library", id: "stoic" }} />);
  await screen.findByRole("button", { name: "Stoic Sage" });
  fireEvent.click(screen.getByRole("button", { name: "Write your own" }));
  const editor = screen.getByRole("textbox", { name: "soul-editor" });
  expect(editor).toHaveValue("");
  fireEvent.change(editor, { target: { value: "# Custom soul" } });
  await waitFor(() => expect(editor).toHaveValue("# Custom soul"));
  fireEvent.click(screen.getByRole("button", { name: "Soul library" }));
  expect(
    await screen.findByText(
      "Edited — your version becomes this partner's soul. The original template is untouched.",
    ),
  ).toBeInTheDocument();
});

it("hides the save-to-library controls for non-admins", async () => {
  fixture.getSoulSources.mockResolvedValue(sources);
  render(<Harness initial={{ source: "custom", content: "# Draft" }} />);
  await screen.findByRole("textbox", { name: "soul-editor" });
  expect(
    screen.queryByPlaceholderText("Template name"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Save to soul library" }),
  ).not.toBeInTheDocument();
});

it("admins can save a custom soul back into the library", async () => {
  fixture.isAdmin = true;
  fixture.getSoulSources
    .mockResolvedValueOnce(sources)
    .mockResolvedValueOnce({
      ...sources,
      library: [
        ...sources.library,
        { id: "my-soul-2", name: "My Soul 2!", content: "# Draft" },
      ],
    });
  fixture.createSoulTemplate.mockResolvedValue({
    id: "my-soul-2",
    name: "My Soul 2!",
    content: "# Draft",
  });
  render(<Harness initial={{ source: "custom", content: "# Draft" }} />);
  await screen.findByRole("textbox", { name: "soul-editor" });
  const saveButton = screen.getByRole("button", { name: "Save to soul library" });
  expect(saveButton).toBeDisabled();
  fireEvent.change(screen.getByPlaceholderText("Template name"), {
    target: { value: "My Soul 2!" },
  });
  expect(saveButton).toBeEnabled();
  fireEvent.click(saveButton);
  await waitFor(() =>
    expect(fixture.createSoulTemplate).toHaveBeenCalledWith(
      "my-soul-2",
      "My Soul 2!",
      "# Draft",
    ),
  );
  await waitFor(() => expect(fixture.getSoulSources).toHaveBeenCalledTimes(2));
  const chip = await screen.findByRole("button", { name: /My Soul 2!/ });
  expect(chip.className).toContain("border-[var(--primary)]");
  expect(screen.getByRole("button", { name: "Soul library" })).toHaveClass("font-medium");
});

it("shows the save error message when saving fails", async () => {
  fixture.isAdmin = true;
  fixture.getSoulSources.mockResolvedValue(sources);
  fixture.createSoulTemplate.mockRejectedValue(new Error("name already taken"));
  render(<Harness initial={{ source: "custom", content: "# Draft" }} />);
  await screen.findByRole("textbox", { name: "soul-editor" });
  fireEvent.change(screen.getByPlaceholderText("Template name"), {
    target: { value: "Dup" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save to soul library" }));
  expect(await screen.findByText("name already taken")).toBeInTheDocument();
  expect(fixture.getSoulSources).toHaveBeenCalledTimes(1);
});

it("falls back to a generated ASCII id when the name has no slug-safe characters", async () => {
  fixture.isAdmin = true;
  fixture.getSoulSources.mockResolvedValue(sources);
  fixture.createSoulTemplate.mockResolvedValue({
    id: "soul-fallback",
    name: "灵魂",
    content: "# Draft",
  });
  render(<Harness initial={{ source: "custom", content: "# Draft" }} />);
  await screen.findByRole("textbox", { name: "soul-editor" });
  fireEvent.change(screen.getByPlaceholderText("Template name"), {
    target: { value: "灵魂" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save to soul library" }));
  await waitFor(() => expect(fixture.createSoulTemplate).toHaveBeenCalled());
  const [id] = fixture.createSoulTemplate.mock.calls[0];
  expect(id).toMatch(/^soul-[0-9a-z]+$/);
});

it("marks the freshly saved library chip with a check", async () => {
  fixture.isAdmin = true;
  fixture.getSoulSources.mockResolvedValue(sources);
  fixture.createSoulTemplate.mockResolvedValue({
    id: "stoic",
    name: "Stoic Sage",
    content: "# Draft",
  });
  render(<Harness initial={{ source: "custom", content: "# Draft" }} />);
  await screen.findByRole("textbox", { name: "soul-editor" });
  fireEvent.change(screen.getByPlaceholderText("Template name"), {
    target: { value: "Stoic Sage" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save to soul library" }));
  const chip = await screen.findByRole("button", { name: "Stoic Sage" });
  await waitFor(() => expect(chip.querySelector("svg")).not.toBeNull());
});
