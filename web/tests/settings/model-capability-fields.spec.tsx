import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelCapabilityFields } from "@/components/settings/ModelCapabilityFields";
import type { CatalogModel } from "@/features/settings/store/SettingsStore";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
  apiUrl: (url: string) => url,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: any) =>
      key.replace(/{{(\w+)}}/g, (_, name) => String(args?.[name] ?? name)),
  }),
}));

const model: CatalogModel = {
  id: "m1",
  name: "Chat model",
  model: "gpt-test",
};

/** Row order follows ModelCapabilityFields' ROWS declaration. */
function rows() {
  const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
  const [tools, vision, json, reasoning] = selects;
  return { tools, vision, json, reasoning };
}

function defaultsResponse(defaults: Record<string, boolean>) {
  return {
    ok: true,
    json: async () => ({ defaults }),
  } as unknown as Response;
}

async function flushDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
}

function setup(overrides: Partial<Parameters<typeof ModelCapabilityFields>[0]> = {}) {
  const onChange = vi.fn();
  const props = {
    binding: "openai",
    model,
    reasoningKnown: false,
    onChange,
    ...overrides,
  };
  const view = render(<ModelCapabilityFields {...props} />);
  return { view, onChange, props };
}

describe("ModelCapabilityFields settings component", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.fetch.mockResolvedValue(
      defaultsResponse({ tools: true, vision: false, json_output: true }),
    );
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("writes every three-way choice back through onChange", () => {
    const { onChange } = setup();
    const { tools, vision, json } = rows();

    fireEvent.change(tools, { target: { value: "yes" } });
    expect(onChange).toHaveBeenCalledWith("tools", true);
    fireEvent.change(vision, { target: { value: "no" } });
    expect(onChange).toHaveBeenCalledWith("vision", false);
    fireEvent.change(json, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith("json_output", null);
    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it("shows declared overrides instead of Auto for keyed capabilities", () => {
    setup({
      model: {
        ...model,
        capabilities: { tools: true, vision: false },
      },
    });
    const { tools, vision, json } = rows();
    expect((tools as HTMLSelectElement).value).toBe("yes");
    expect((vision as HTMLSelectElement).value).toBe("no");
    expect((json as HTMLSelectElement).value).toBe("");
  });

  it("fetches backend defaults after the debounce and labels Auto with them", async () => {
    const { view } = setup();
    expect(mocks.fetch).not.toHaveBeenCalled();

    await flushDebounce();
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(mocks.fetch).toHaveBeenCalledWith("/api/settings/model-capabilities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ binding: "openai", model: "gpt-test" }),
    });

    const { tools, vision } = rows();
    expect(tools.options[0].textContent).toBe("Auto (Supported)");
    expect(vision.options[0].textContent).toBe("Auto (Not supported)");
    expect(view.getByText("Capabilities")).toBeInTheDocument();
  });

  it("never shows a fetched answer against a different model", async () => {
    const { view } = setup();
    await flushDebounce();
    expect(rows().tools.options[0].textContent).toBe("Auto (Supported)");

    view.rerender(
      <ModelCapabilityFields
        binding="openai"
        model={{ ...model, id: "m2", model: "gpt-other" }}
        reasoningKnown={false}
        onChange={vi.fn()}
      />,
    );
    expect(rows().tools.options[0].textContent).toBe("Auto");
    await flushDebounce();
    expect(mocks.fetch).toHaveBeenCalledTimes(2);
    const secondCall = mocks.fetch.mock.calls[1] as unknown[];
    expect(JSON.parse(String((secondCall[1] as RequestInit).body))).toEqual({
      binding: "openai",
      model: "gpt-other",
    });
    expect(rows().tools.options[0].textContent).toBe("Auto (Supported)");
  });

  it("labels the reasoning row from reasoningKnown without waiting on the fetch", () => {
    const known = setup({ reasoningKnown: true });
    expect(rows().reasoning.options[0].textContent).toBe("Auto (Supported)");
    known.view.unmount();

    const unknown = setup({ reasoningKnown: false });
    expect(rows().reasoning.options[0].textContent).toBe("Auto (Not supported)");
    unknown.view.unmount();
  });

  it("skips the backend entirely for a blank model id", async () => {
    setup({ model: { ...model, model: "   " } });
    await flushDebounce();
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it("keeps the plain Auto label when the fetch fails", async () => {
    mocks.fetch.mockRejectedValue(new Error("offline"));
    setup();
    await flushDebounce();
    expect(rows().tools.options[0].textContent).toBe("Auto");
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });

  it("sends an empty binding when the profile has none", async () => {
    setup({ binding: undefined });
    await flushDebounce();
    expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/settings/model-capabilities",
      expect.objectContaining({
        body: JSON.stringify({ binding: "", model: "gpt-test" }),
      }),
    );
  });
});
