import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Field } from "@/shared/ui/Field";

describe("Field rendering behavior", () => {
  it("generates the control id and leaves describedby unset without hint or error", () => {
    render(
      <Field label="Workspace name">
        <input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Workspace name" });
    const label = input.closest("div")?.querySelector("label");
    expect(label).toHaveAttribute("for", input.id);
    expect(input.id).not.toBe("");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("binds the label to a caller-provided id instead of the generated one", () => {
    render(
      <Field label="API key">
        <input id="api-key-input" />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "API key" });
    expect(input).toHaveAttribute("id", "api-key-input");
    expect(screen.getByText("API key")).toHaveAttribute(
      "for",
      "api-key-input",
    );
  });

  it("marks invalid only with an error and wires hint and error ids", () => {
    const { rerender } = render(
      <Field label="Email" hint="We never share it">
        <input type="email" />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Email" });
    expect(input).not.toHaveAttribute("aria-invalid");
    const describedBy = input.getAttribute("aria-describedby") ?? "";
    expect(describedBy.split(" ")).toHaveLength(1);
    expect(document.getElementById(describedBy)).toHaveTextContent(
      "We never share it",
    );
    rerender(
      <Field label="Email" hint="We never share it" error="Enter a valid email">
        <input type="email" />
      </Field>,
    );
    const invalid = screen.getByRole("textbox", { name: "Email" });
    expect(invalid).toHaveAttribute("aria-invalid", "true");
    const ids = (invalid.getAttribute("aria-describedby") ?? "").split(" ");
    expect(ids).toHaveLength(2);
    expect(document.getElementById(ids[1])).toHaveTextContent(
      "Enter a valid email",
    );
  });

  it("renders optional label and extreme-length error text without dropping content", () => {
    const longError = "E".repeat(1500);
    render(
      <Field label="Slug" optionalLabel="(optional)" error={longError}>
        <input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: /Slug/ });
    expect(screen.getByText(/optional/)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    const errorId = input.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(errorId)).toHaveTextContent(longError);
  });
});
