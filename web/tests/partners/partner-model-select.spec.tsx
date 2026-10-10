import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PartnerModelSelect from "@/components/partners/PartnerModelSelect";
import type { LLMOption } from "@/lib/llm-options";
import type { LLMSelection } from "@/features/chat/model/protocol";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function makeOption(overrides: Partial<LLMOption> = {}): LLMOption {
  return {
    profile_id: "prof-1",
    model_id: "gpt-5",
    profile_name: "fast-profile",
    model_name: "GPT-5",
    model: "gpt-5",
    provider: "openai",
    provider_label: "OpenAI",
    context_window: 1_000_000,
    is_active_default: false,
    ...overrides,
  };
}

const options: LLMOption[] = [
  makeOption(),
  makeOption({
    profile_id: "prof-2",
    model_id: "claude",
    profile_name: "long-context",
    model_name: "Claude",
    model: "claude-sonnet",
    provider: "anthropic",
    provider_label: "Anthropic",
    context_window: 810_000,
  }),
];

const value: LLMSelection = { profile_id: "prof-1", model_id: "gpt-5" };

function renderSelect(overrides: {
  options?: LLMOption[];
  activeDefault?: LLMSelection | null;
  value?: LLMSelection | null;
  loading?: boolean;
  error?: boolean;
  noneLabel?: string;
  noneDetail?: string;
  onChange?: (selection: LLMSelection | null) => void;
} = {}) {
  return render(
    <PartnerModelSelect
      options={overrides.options ?? options}
      activeDefault={
        overrides.activeDefault === undefined ? null : overrides.activeDefault
      }
      value={overrides.value === undefined ? value : overrides.value}
      loading={overrides.loading ?? false}
      error={overrides.error ?? false}
      noneLabel={overrides.noneLabel ?? "System default"}
      noneDetail={overrides.noneDetail}
      onChange={overrides.onChange ?? (() => {})}
    />,
  );
}

const openDropdown = () => {
  fireEvent.click(screen.getByRole("button", { name: /GPT-5/ }));
};

it("shows a loading placeholder instead of the trigger while options load", () => {
  renderSelect({ loading: true });
  expect(screen.getByText("Loading models…")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("explains the fallback when the model catalog fails to load", () => {
  renderSelect({ error: true });
  expect(
    screen.getByText(
      "Could not load the model catalog — the partner will use the system default.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("echoes the current selection as the collapsed trigger text", () => {
  renderSelect();
  const trigger = screen.getByRole("button", { name: /GPT-5/ });
  expect(trigger).toHaveTextContent("GPT-5");
  expect(trigger).toHaveTextContent("OpenAI · fast-profile");
  expect(screen.queryByText("Claude")).not.toBeInTheDocument();
});

it("shows the none label when no model is selected", () => {
  renderSelect({ value: null, noneLabel: "System default", noneDetail: "owner default" });
  const trigger = screen.getByRole("button", { name: /System default/ });
  expect(trigger).toHaveTextContent("System default");
  expect(trigger).toHaveTextContent("owner default");
});

it("falls back to the active default summary when no model is selected", () => {
  renderSelect({
    value: null,
    activeDefault: { profile_id: "prof-2", model_id: "claude" },
  });
  const trigger = screen.getByRole("button", { name: /System default/ });
  expect(trigger).toHaveTextContent("Claude · Anthropic");
});

it("opens to list every option with provider, profile and context window", () => {
  renderSelect();
  openDropdown();
  const claudeRow = screen.getByRole("button", { name: /Claude/ });
  expect(claudeRow).toHaveTextContent("Anthropic · long-context");
  expect(claudeRow).toHaveTextContent("810K");
  const gptRow = screen
    .getAllByRole("button", { name: /GPT-5/ })
    .at(-1) as HTMLElement;
  expect(gptRow).toHaveTextContent("1M");
});

it("selecting an option reports the profile/model pair and closes", () => {
  const onChange = vi.fn();
  renderSelect({ onChange });
  openDropdown();
  fireEvent.click(screen.getByRole("button", { name: /Claude/ }));
  expect(onChange).toHaveBeenCalledWith({ profile_id: "prof-2", model_id: "claude" });
  expect(screen.queryByRole("button", { name: /Claude/ })).not.toBeInTheDocument();
});

it("selecting the none row clears the selection and closes", () => {
  const onChange = vi.fn();
  renderSelect({ onChange });
  fireEvent.click(screen.getByRole("button", { name: /GPT-5/ }));
  fireEvent.click(screen.getByRole("button", { name: "System default" }));
  expect(onChange).toHaveBeenCalledWith(null);
  expect(
    screen.queryByRole("button", { name: "System default" }),
  ).not.toBeInTheDocument();
});

it("marks the selected option row while the dropdown is open", () => {
  renderSelect();
  openDropdown();
  const selectedRow = screen
    .getAllByRole("button", { name: /GPT-5/ })
    .at(-1) as HTMLElement;
  expect(selectedRow.className).toContain("bg-[var(--secondary)]");
  const otherRow = screen.getByRole("button", { name: /Claude/ });
  expect(otherRow.className).not.toContain("bg-[var(--secondary)]");
});

it("falls back to the raw model id when the value is missing from options", () => {
  renderSelect({
    value: { profile_id: "prof-x", model_id: "ghost-model" },
    options: [],
  });
  expect(screen.getByRole("button", { name: /ghost-model/ })).toBeInTheDocument();
});

it("shows the empty-catalog copy when opening with no options", () => {
  renderSelect({ options: [], value: null });
  fireEvent.click(screen.getByRole("button", { name: /System default/ }));
  expect(
    screen.getByText("No models configured yet — add providers in Settings → LLM."),
  ).toBeInTheDocument();
});

it("closes on an outside pointer press but stays open for inside presses", async () => {
  renderSelect();
  const trigger = screen.getByRole("button", { name: /GPT-5/ });
  openDropdown();
  expect(screen.getByRole("button", { name: /Claude/ })).toBeInTheDocument();
  fireEvent.pointerDown(trigger);
  expect(screen.getByRole("button", { name: /Claude/ })).toBeInTheDocument();
  fireEvent.pointerDown(document.body);
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /Claude/ })).not.toBeInTheDocument(),
  );
});
