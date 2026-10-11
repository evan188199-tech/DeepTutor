import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import ReasoningEffortSelector from "@/components/chat/home/ReasoningEffortSelector";
import type { LLMOption } from "@/lib/llm-options";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function option(
  provider: string,
  model: string,
  extra: Partial<LLMOption> = {},
): LLMOption {
  return {
    profile_id: "p1",
    model_id: "m1",
    profile_name: "Profile",
    model_name: model,
    model,
    provider,
    is_active_default: false,
    ...extra,
  };
}

function Harness(props: {
  options: LLMOption[];
  value?: { profile_id: string; model_id: string; reasoning_effort?: string } | null;
}) {
  return (
    <ReasoningEffortSelector
      options={props.options}
      activeDefault={{ profile_id: "p1", model_id: "m1" }}
      value={props.value ?? null}
      onChange={() => {}}
    />
  );
}

function menuValues(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("div.absolute button")).map(
    (row) => row.textContent ?? "",
  );
}

it("lists only the levels the selected model supports", () => {
  const { container } = render(
    <Harness options={[option("openai", "gpt-5.2")]} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reasoning" }));
  const labels = menuValues(container);
  expect(labels).toEqual([
    "Provider default (Auto)",
    "Minimal",
    "Low",
    "Medium",
    "High",
    "Extra high",
  ]);
});

it("hides the selector for a model without a reasoning knob", () => {
  const { container } = render(
    <Harness options={[option("volcengine", "doubao-pro-32k")]} />,
  );
  expect(container.querySelector("button")).toBeNull();
});

it("sends the override on the model selection and clears it on Auto", () => {
  const onChange = vi.fn();
  const options = [option("openai", "gpt-5.2")];
  const { container, rerender } = render(
    <ReasoningEffortSelector
      options={options}
      activeDefault={{ profile_id: "p1", model_id: "m1" }}
      value={{ profile_id: "p1", model_id: "m1" }}
      onChange={onChange}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reasoning" }));
  const rows = Array.from(
    container.querySelectorAll("div.absolute button"),
  ) as HTMLElement[];
  fireEvent.click(rows[3]);
  expect(onChange).toHaveBeenCalledWith({
    profile_id: "p1",
    model_id: "m1",
    reasoning_effort: "medium",
  });

  // With the override active, picking Auto drops the field entirely.
  onChange.mockClear();
  rerender(
    <ReasoningEffortSelector
      options={options}
      activeDefault={{ profile_id: "p1", model_id: "m1" }}
      value={{ profile_id: "p1", model_id: "m1", reasoning_effort: "medium" }}
      onChange={onChange}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reasoning" }));
  const rowsAfter = Array.from(
    container.querySelectorAll("div.absolute button"),
  ) as HTMLElement[];
  fireEvent.click(rowsAfter[0]);
  expect(onChange).toHaveBeenCalledWith({
    profile_id: "p1",
    model_id: "m1",
  });
});

it("prefers the provider-reported levels for managed codex models", () => {
  const { container } = render(
    <Harness
      options={[
        option("openai_codex", "gpt-5.2-codex", {
          supported_reasoning_efforts: ["low", "high"],
        }),
      ]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reasoning" }));
  const labels = menuValues(container);
  expect(labels).toEqual(["Provider default (Auto)", "Low", "High"]);
});

it("shows the active override on the trigger", () => {
  render(
    <Harness
      options={[option("openai", "gpt-5.2")]}
      value={{ profile_id: "p1", model_id: "m1", reasoning_effort: "high" }}
    />,
  );
  expect(screen.getByRole("button", { name: "Reasoning" }).textContent).toContain(
    "High",
  );
});
