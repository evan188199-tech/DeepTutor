import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelSelector from "@/components/chat/home/ModelSelector";
import type { LLMOption } from "@/lib/llm-options";
import { initI18n } from "@/i18n/init";

initI18n("en");

function llmOption(overrides: Partial<LLMOption> = {}): LLMOption {
  return {
    profile_id: "profile-1",
    model_id: "model-1",
    profile_name: "Profile One",
    model_name: "GPT One",
    model: "gpt-one",
    provider: "openai",
    is_active_default: false,
    ...overrides,
  };
}

describe("ModelSelector", () => {
  it("opens the dropdown and renders every option with provider and context details", () => {
    const options = [
      llmOption(),
      llmOption({
        profile_id: "profile-2",
        model_id: "model-2",
        profile_name: "Profile Two",
        model_name: "GPT Two",
        model: "gpt-two",
        context_window: 128000,
        is_active_default: true,
      }),
    ];
    render(
      <ModelSelector
        options={options}
        activeDefault={null}
        value={null}
        loading={false}
        error={false}
        onChange={vi.fn()}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Select model" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "GPT One | Profile One" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "GPT Two | Profile Two" }),
    ).toHaveTextContent("Default");
    expect(screen.getByText("128k ctx")).toBeInTheDocument();
  });

  it("reports the chosen profile/model pair and closes the menu", () => {
    const onChange = vi.fn();
    render(
      <ModelSelector
        options={[llmOption()]}
        activeDefault={null}
        value={null}
        loading={false}
        error={false}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select model" }));
    fireEvent.click(
      screen.getByRole("button", { name: "GPT One | Profile One" }),
    );
    expect(onChange).toHaveBeenCalledWith({
      profile_id: "profile-1",
      model_id: "model-1",
    });
    expect(
      screen.getByRole("button", { name: "Select model" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("echoes the active selection label in the trigger", () => {
    render(
      <ModelSelector
        options={[
          llmOption(),
          llmOption({
            profile_id: "profile-2",
            model_id: "model-2",
            model: "gpt-two",
          }),
        ]}
        activeDefault={null}
        value={{ profile_id: "profile-2", model_id: "model-2" }}
        loading={false}
        error={false}
        onChange={vi.fn()}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Select model" });
    expect(trigger).toHaveTextContent("gpt-two");
    expect(trigger).not.toHaveTextContent("gpt-one");
  });

  it("falls back to the active default label when nothing is selected", () => {
    render(
      <ModelSelector
        options={[llmOption()]}
        activeDefault={{ profile_id: "profile-1", model_id: "model-1" }}
        value={null}
        loading={false}
        error={false}
        onChange={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Select model" }),
    ).toHaveTextContent("gpt-one");
  });

  it("keeps the system default slot usable with an empty profile list", () => {
    const onChange = vi.fn();
    render(
      <ModelSelector
        options={[]}
        activeDefault={null}
        value={null}
        loading={false}
        error={false}
        allowSystemDefault
        onChange={onChange}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Select model" });
    expect(trigger).toBeEnabled();
    fireEvent.click(trigger);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Use the active default model from Settings",
      }),
    );
    expect(onChange).toHaveBeenCalledWith(null);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("disables the trigger while models are loading", () => {
    render(
      <ModelSelector
        options={[]}
        activeDefault={null}
        value={null}
        loading
        error={false}
        onChange={vi.fn()}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Select model" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent("Loading models");
  });

  it("disables on error without refresh and offers refresh when possible", () => {
    const props = {
      options: [llmOption()],
      activeDefault: null,
      value: null,
      loading: false,
      error: true,
    };
    const { rerender } = render(
      <ModelSelector {...props} onChange={vi.fn()} />,
    );
    const disabledTrigger = screen.getByRole("button", {
      name: "Select model",
    });
    expect(disabledTrigger).toBeDisabled();
    expect(disabledTrigger).toHaveTextContent("Models unavailable");

    const onRefresh = vi.fn();
    rerender(
      <ModelSelector {...props} onChange={vi.fn()} onRefresh={onRefresh} />,
    );
    const trigger = screen.getByRole("button", { name: "Refresh models" });
    fireEvent.click(trigger);
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("disables when no options exist and no system default is allowed", () => {
    render(
      <ModelSelector
        options={[]}
        activeDefault={null}
        value={null}
        loading={false}
        error={false}
        onChange={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Select model" }),
    ).toBeDisabled();
  });
});
