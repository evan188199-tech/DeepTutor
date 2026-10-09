import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  SchemaField,
  defaultFor,
  isNullable,
  resolveSchemaVariant,
  type JsonSchema,
} from "@/components/partners/schema-form";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const NO_SECRETS = new Set<string>();
const NO_REVEAL = new Set<string>();
const NO_TOGGLE = () => {};

type FieldOptions = {
  fieldKey?: string;
  path?: string;
  secretFields?: Set<string>;
  showSecretFor?: Set<string>;
  toggleSecret?: (path: string) => void;
};

function renderField(
  schema: JsonSchema,
  value: unknown,
  onChange: (next: unknown) => void = () => {},
  options: FieldOptions = {},
) {
  const fieldKey = options.fieldKey ?? "field";
  return render(
    <SchemaField
      fieldKey={fieldKey}
      schema={schema}
      value={value}
      onChange={onChange}
      secretFields={options.secretFields ?? NO_SECRETS}
      path={options.path ?? fieldKey}
      showSecretFor={options.showSecretFor ?? NO_REVEAL}
      toggleSecret={options.toggleSecret ?? NO_TOGGLE}
    />,
  );
}

/** Mirrors how PartnerChannels composes SchemaField values into a config. */
function SchemaHarness({
  schema,
  initialConfig = {},
  secretFields = NO_SECRETS,
}: {
  schema: JsonSchema;
  initialConfig?: Record<string, unknown>;
  secretFields?: Set<string>;
}) {
  const [config, setConfig] = useState(initialConfig);
  const [revealed, setRevealed] = useState<Set<string>>(() => new Set());
  return (
    <div>
      {Object.entries(schema.properties ?? {}).map(([k, child]) => (
        <SchemaField
          key={k}
          fieldKey={k}
          schema={child}
          value={config[k] ?? defaultFor(child)}
          onChange={(next) => setConfig((prev) => ({ ...prev, [k]: next }))}
          secretFields={secretFields}
          path={k}
          showSecretFor={revealed}
          toggleSecret={(p) =>
            setRevealed((prev) => {
              const next = new Set(prev);
              if (next.has(p)) next.delete(p);
              else next.add(p);
              return next;
            })
          }
        />
      ))}
      <div data-testid="payload">{JSON.stringify(config)}</div>
    </div>
  );
}

function payload(): Record<string, unknown> {
  return JSON.parse(screen.getByTestId("payload").textContent ?? "{}");
}

/** Finds the wrapper element of the field whose label starts with `labelText`. */
function fieldBox(root: HTMLElement, labelText: string): HTMLElement {
  const label = Array.from(root.querySelectorAll("label")).find((el) =>
    (el.textContent ?? "").startsWith(labelText),
  );
  if (!label) throw new Error(`field label not found: ${labelText}`);
  return label.parentElement ?? label;
}

function SecretRevealHarness({ secretPath }: { secretPath: string }) {
  const [revealed, setRevealed] = useState<Set<string>>(() => new Set());
  return (
    <SchemaField
      fieldKey={secretPath}
      schema={{ type: "string", title: "Api Key" }}
      value="abc"
      onChange={() => {}}
      secretFields={new Set([secretPath])}
      path={secretPath}
      showSecretFor={revealed}
      toggleSecret={(p) =>
        setRevealed((prev) => {
          const next = new Set(prev);
          if (next.has(p)) next.delete(p);
          else next.add(p);
          return next;
        })
      }
    />
  );
}

describe("schema helpers", () => {
  it("picks the first non-null anyOf variant and merges outer meta", () => {
    const variant = resolveSchemaVariant({
      title: "Outer",
      description: "Outer desc",
      anyOf: [
        { type: "null" },
        { type: "string", title: "Inner", description: "Inner desc" },
      ],
    });
    expect(variant.type).toBe("string");
    expect(variant.title).toBe("Outer");
    expect(variant.description).toBe("Outer desc");
    expect(resolveSchemaVariant({ type: "string" })).toEqual({ type: "string" });
  });

  it("falls back to the first anyOf variant when every variant is null", () => {
    expect(resolveSchemaVariant({ anyOf: [{ type: "null" }] }).type).toBe("null");
  });

  it("detects nullability from type arrays and anyOf", () => {
    expect(isNullable({ type: ["string", "null"] })).toBe(true);
    expect(
      isNullable({ anyOf: [{ type: "string" }, { type: "null" }] }),
    ).toBe(true);
    expect(isNullable({ type: "string" })).toBe(false);
    expect(isNullable({ type: "integer" })).toBe(false);
  });

  it("provides typed defaults when the schema has none", () => {
    expect(defaultFor({ default: "preset" })).toBe("preset");
    expect(defaultFor({ type: "boolean" })).toBe(false);
    expect(defaultFor({ type: "integer" })).toBe(0);
    expect(defaultFor({ type: "number" })).toBe(0);
    expect(defaultFor({ type: "array" })).toEqual([]);
    expect(defaultFor({ type: "object" })).toEqual({});
    expect(defaultFor({ type: "string" })).toBe("");
    expect(defaultFor({ anyOf: [{ type: "string" }, { type: "null" }] })).toBe("");
  });
});

describe("schema-driven field rendering", () => {
  it("renders booleans as checkboxes with title and description", () => {
    const onChange = vi.fn();
    renderField(
      { type: "boolean", title: "Enabled", description: "Receive messages" },
      false,
      onChange,
    );
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    const label = checkbox.closest("label");
    expect(label?.textContent).toContain("Enabled");
    expect(label?.textContent).toContain("Receive messages");
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("renders enums as selects and reports the chosen literal", () => {
    const onChange = vi.fn();
    renderField(
      { type: "string", enum: ["auto", "on", "off"], title: "Mode" },
      "auto",
      onChange,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("auto");
    expect(select.options).toHaveLength(3);
    fireEvent.change(select, { target: { value: "on" } });
    expect(onChange).toHaveBeenCalledWith("on");
  });

  it("renders string arrays as one-value-per-line textareas", () => {
    const onChange = vi.fn();
    renderField(
      { type: "array", items: { type: "string" }, title: "Tags" },
      ["x", "y"],
      onChange,
    );
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("x\ny");
    fireEvent.change(textarea, { target: { value: "p\n q \n\nr" } });
    expect(onChange).toHaveBeenCalledWith(["p", "q", "r"]);
  });

  it("renders numbers as numeric inputs and parses int vs float", () => {
    const onChange = vi.fn();
    const int = renderField({ type: "integer", title: "Timeout" }, 120, onChange);
    const intInput = within(int.container).getByRole(
      "spinbutton",
    ) as HTMLInputElement;
    expect(intInput.value).toBe("120");
    fireEvent.change(intInput, { target: { value: "9" } });
    expect(onChange).toHaveBeenCalledWith(9);
    const onFloat = vi.fn();
    const num = renderField({ type: "number", title: "Ratio" }, 0.5, onFloat);
    const numInput = within(num.container).getByRole(
      "spinbutton",
    ) as HTMLInputElement;
    fireEvent.change(numInput, { target: { value: "0.75" } });
    expect(onFloat).toHaveBeenCalledWith(0.75);
  });

  it("renders plain strings as text inputs keeping the stored value", () => {
    renderField({ type: "string", title: "Name" }, "ada");
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input).toHaveAttribute("type", "text");
    expect(input.value).toBe("ada");
  });

  it("humanises snake_case keys when no title exists", () => {
    renderField({ type: "string" }, "", vi.fn(), {
      fieldKey: "api_key",
      path: "api_key",
    });
    const label = Array.from(document.querySelectorAll("label")).find(
      (el) => (el.textContent ?? "") === "Api Key",
    );
    expect(label).toBeDefined();
  });

  it("renders nested objects as recursive fieldsets with defaults", () => {
    const onChange = vi.fn();
    const { container } = renderField(
      {
        type: "object",
        title: "Server",
        properties: {
          host: { type: "string", default: "localhost" },
          port: { type: "integer" },
        },
      },
      { host: "h1" },
      onChange,
    );
    const fieldset = container.querySelector("fieldset");
    expect(fieldset).not.toBeNull();
    expect(within(fieldset as HTMLElement).getByText("Server").tagName).toBe(
      "LEGEND",
    );
    const host = fieldBox(fieldset as HTMLElement, "Host").querySelector(
      "input",
    ) as HTMLInputElement;
    const port = fieldBox(fieldset as HTMLElement, "Port").querySelector(
      "input",
    ) as HTMLInputElement;
    expect(host.value).toBe("h1");
    expect(port.value).toBe("0");
    fireEvent.change(host, { target: { value: "h2" } });
    expect(onChange).toHaveBeenLastCalledWith({ host: "h2" });
    fireEvent.change(port, { target: { value: "5432" } });
    expect(onChange).toHaveBeenLastCalledWith({ host: "h1", port: 5432 });
  });

  it("masks secret inputs until the reveal toggle is used", () => {
    const { container } = render(<SecretRevealHarness secretPath="api_key" />);
    const input = container.querySelector("input") as HTMLInputElement;
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "new-password");
    expect(
      screen.getByRole("button", { name: "Show secret" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    expect(input).toHaveAttribute("type", "text");
    expect(
      screen.getByRole("button", { name: "Hide secret" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("validation error display", () => {
  it("prefills the dict JSON textarea from the stored value", () => {
    renderField({ type: "object", title: "Extra" }, { retries: 2 });
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe('{\n  "retries": 2\n}');
  });

  it("flags invalid JSON, keeps the prior value, and recovers", () => {
    const onChange = vi.fn();
    renderField({ type: "object", title: "Extra" }, {}, onChange);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: "{oops" } });
    expect(
      screen.getByText("Invalid JSON — value not applied."),
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: '{"retries": 3}' } });
    expect(
      screen.queryByText("Invalid JSON — value not applied."),
    ).not.toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith({ retries: 3 });

    fireEvent.change(textarea, { target: { value: "[1, 2]" } });
    expect(
      screen.getByText("Invalid JSON — value not applied."),
    ).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(1);

    fireEvent.change(textarea, { target: { value: "   " } });
    expect(
      screen.queryByText("Invalid JSON — value not applied."),
    ).not.toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith({});
  });
});

describe("submission payload assembly", () => {
  it("assembles a typed config payload from every field kind", () => {
    const { container } = render(
      <SchemaHarness
        schema={{
          type: "object",
          properties: {
            enabled: { type: "boolean", title: "Enabled" },
            mode: {
              type: "string",
              title: "Mode",
              enum: ["auto", "on", "off"],
              default: "auto",
            },
            tags: { type: "array", title: "Tags", items: { type: "string" } },
            timeout: { type: "integer", title: "Timeout" },
            ratio: { type: "number", title: "Ratio" },
            retries: {
              title: "Retries",
              anyOf: [{ type: "integer" }, { type: "null" }],
            },
            api_key: {
              title: "Api Key",
              anyOf: [{ type: "string" }, { type: "null" }],
            },
            server: {
              type: "object",
              title: "Server",
              properties: {
                host: { type: "string" },
                port: { type: "integer" },
              },
            },
          },
        }}
        initialConfig={{}}
        secretFields={new Set(["api_key"])}
      />,
    );

    expect(payload()).toEqual({});

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "on" },
    });
    fireEvent.change(
      fieldBox(container, "Tags").querySelector("textarea") as HTMLTextAreaElement,
      { target: { value: "alpha\n beta \n\ngamma" } },
    );
    fireEvent.change(
      fieldBox(container, "Timeout").querySelector("input") as HTMLInputElement,
      { target: { value: "120" } },
    );
    fireEvent.change(
      fieldBox(container, "Ratio").querySelector("input") as HTMLInputElement,
      { target: { value: "0.75" } },
    );
    fireEvent.change(
      fieldBox(container, "Retries").querySelector("input") as HTMLInputElement,
      { target: { value: "" } },
    );
    expect(payload()).toMatchObject({ retries: null });

    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    fireEvent.change(
      fieldBox(container, "Api Key").querySelector("input") as HTMLInputElement,
      { target: { value: "sk-1" } },
    );
    expect(payload()).toMatchObject({ api_key: "sk-1" });
    fireEvent.change(
      fieldBox(container, "Api Key").querySelector("input") as HTMLInputElement,
      { target: { value: "" } },
    );
    expect(payload()).toMatchObject({ api_key: null });

    const fieldset = container.querySelector("fieldset") as HTMLElement;
    fireEvent.change(
      fieldBox(fieldset, "Host").querySelector("input") as HTMLInputElement,
      { target: { value: "db.local" } },
    );
    fireEvent.change(
      fieldBox(fieldset, "Port").querySelector("input") as HTMLInputElement,
      { target: { value: "5432" } },
    );

    expect(payload()).toEqual({
      enabled: true,
      mode: "on",
      tags: ["alpha", "beta", "gamma"],
      timeout: 120,
      ratio: 0.75,
      retries: null,
      api_key: null,
      server: { host: "db.local", port: 5432 },
    });
  });

  it("persists an emptied optional string as null", () => {
    const onChange = vi.fn();
    renderField(
      { anyOf: [{ type: "string" }, { type: "null" }] },
      "abc",
      onChange,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("resets a cleared integer to zero when not nullable and to null when nullable", () => {
    const onChange = vi.fn();
    const plain = renderField({ type: "integer", title: "Timeout" }, 120, onChange);
    fireEvent.change(within(plain.container).getByRole("spinbutton"), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenCalledWith(0);

    const onNullable = vi.fn();
    const nullable = renderField(
      { anyOf: [{ type: "integer" }, { type: "null" }], title: "Retries" },
      3,
      onNullable,
    );
    fireEvent.change(within(nullable.container).getByRole("spinbutton"), {
      target: { value: "" },
    });
    expect(onNullable).toHaveBeenCalledWith(null);
  });
});
