import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import FaceEditor, {
  FACE_EMOJIS,
  type FaceValue,
} from "@/components/partners/FaceEditor";
import { PARTNER_COLORS } from "@/components/partners/PartnerAvatar";

const translate = vi.hoisted(() => (key: string) => key);
const avatar = vi.hoisted(() => ({
  current: null as null | {
    name: string;
    emoji?: string;
    color?: string;
    image?: string;
  },
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock(
  "@/components/partners/PartnerAvatar",
  async (importOriginal: () => Promise<typeof import("@/components/partners/PartnerAvatar")>) => {
    const actual = await importOriginal();
    return {
      ...actual,
      default: (props: {
        name: string;
        emoji?: string;
        color?: string;
        image?: string;
      }) => {
        avatar.current = props;
        return <div data-testid="avatar-preview" />;
      },
    };
  },
);

const EMPTY: FaceValue = { emoji: "", color: "", avatar: "" };
const EMOJI_ONLY: FaceValue = { emoji: "🦊", color: "#4f7a5b", avatar: "" };
const IMAGE_ONLY: FaceValue = {
  emoji: "",
  color: "",
  avatar: "data:image/png;base64,AAAA",
};

function renderEditor(value: FaceValue) {
  const onChange = vi.fn();
  render(<FaceEditor name="Ada" value={value} onChange={onChange} />);
  return onChange;
}

function fileInput(): HTMLInputElement & { files: FileList | null } {
  const input = document.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error("file input not found");
  }
  return input as HTMLInputElement & { files: FileList | null };
}

function colorButton(color: string): HTMLElement {
  const button = screen.getByRole("button", { name: color });
  if (!(button instanceof HTMLElement)) {
    throw new Error(`color button ${color} not found`);
  }
  return button;
}

function svgFile(size = 32): File {
  const pad = " ".repeat(Math.max(0, size));
  const content = `<svg xmlns="http://www.w3.org/2000/svg">${pad}</svg>`;
  return new File([content], "icon.svg", { type: "image/svg+xml" });
}

describe("FaceEditor", () => {
  it("renders every emoji preset and feeds the live preview", () => {
    renderEditor(EMOJI_ONLY);

    for (const preset of FACE_EMOJIS) {
      expect(screen.getByRole("button", { name: preset })).toBeInTheDocument();
    }
    expect(avatar.current).toMatchObject({
      name: "Ada",
      emoji: "🦊",
      color: "#4f7a5b",
      image: "",
    });
    expect(
      screen.getByRole("button", { name: "Upload photo or SVG" }),
    ).toBeInTheDocument();
  });

  it("renders the empty value state with no active preset and no remove action", () => {
    renderEditor(EMPTY);

    expect(avatar.current).toMatchObject({ name: "Ada", emoji: "", color: "" });
    for (const preset of FACE_EMOJIS) {
      const button = screen.getByRole("button", { name: preset });
      expect(button.className).not.toContain("bg-[var(--secondary)]");
    }
    for (const color of PARTNER_COLORS) {
      expect(colorButton(color).querySelector("span")).toBeNull();
    }
    expect(
      screen.queryByRole("button", { name: "Remove" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("That file is too large.")).not.toBeInTheDocument();
  });

  it("selects an emoji preset and reports the composed value", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);

    await user.click(screen.getByRole("button", { name: "🐳" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({
      emoji: "🐳",
      color: "",
      avatar: "",
    });
  });

  it("clears the emoji when the active preset is tapped again", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMOJI_ONLY);

    const active = screen.getByRole("button", { name: "🦊" });
    expect(active.className).toContain("bg-[var(--secondary)]");
    await user.click(active);

    expect(onChange).toHaveBeenCalledWith({
      emoji: "",
      color: "#4f7a5b",
      avatar: "",
    });
  });

  it("leaves image mode when an emoji is tapped while an avatar is set", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(IMAGE_ONLY);

    await user.click(screen.getByRole("button", { name: "🦉" }));

    expect(onChange).toHaveBeenCalledWith({
      emoji: "🦉",
      color: "",
      avatar: "",
    });
  });

  it("selects a background color and reports the composed value", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);

    await user.click(colorButton(PARTNER_COLORS[0]));

    expect(onChange).toHaveBeenCalledWith({
      emoji: "",
      color: PARTNER_COLORS[0],
      avatar: "",
    });
  });

  it("marks the selected color swatch with a dot", () => {
    renderEditor({ ...EMPTY, color: PARTNER_COLORS[0] });

    expect(colorButton(PARTNER_COLORS[0]).querySelector("span")).not.toBeNull();
    expect(colorButton(PARTNER_COLORS[1]).querySelector("span")).toBeNull();
  });

  it("deselects the color when the active swatch is tapped again", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMOJI_ONLY);

    await user.click(colorButton("#4f7a5b"));

    expect(onChange).toHaveBeenCalledWith({
      emoji: "🦊",
      color: "",
      avatar: "",
    });
  });

  it("offers replace/remove while an avatar is set and remove clears it", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(IMAGE_ONLY);

    expect(
      screen.getByRole("button", { name: "Replace photo" }),
    ).toBeInTheDocument();
    const remove = screen.getByRole("button", { name: "Remove" });
    await user.click(remove);

    expect(onChange).toHaveBeenCalledWith({
      emoji: "",
      color: "",
      avatar: "",
    });
  });

  it("disables the color row while an avatar is set", () => {
    renderEditor(IMAGE_ONLY);

    const swatch = colorButton(PARTNER_COLORS[0]);
    const row = swatch.parentElement;
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row?.className).toContain("pointer-events-none");
  });

  it("converts an accepted SVG upload into a data URL avatar", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);
    const file = svgFile();

    await user.upload(fileInput(), file);

    const expected = `data:image/svg+xml;base64,${btoa(
      String.fromCharCode(...new TextEncoder().encode(await file.text())),
    )}`;
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        emoji: "",
        color: "",
        avatar: expected,
      }),
    );
    expect(
      screen.queryByText("Use a PNG, JPG, WebP, GIF, or SVG image."),
    ).not.toBeInTheDocument();
  });

  it("ignores a change event with no file selected", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);

    await user.upload(fileInput(), []);

    expect(onChange).not.toHaveBeenCalled();
    expect(
      screen.queryByText("Use a PNG, JPG, WebP, GIF, or SVG image."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("That file is too large.")).not.toBeInTheDocument();
  });

  it("rejects an unsupported file type with a hint", async () => {
    const onChange = renderEditor(EMPTY);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    // userEvent.upload applies the input's accept filter, which a file
    // picker enforces anyway; drive the defensive branch directly.
    await act(async () => {
      fireEvent.change(fileInput(), { target: { files: [file] } });
    });

    expect(
      screen.getByText("Use a PNG, JPG, WebP, GIF, or SVG image."),
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects an oversized SVG", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);
    const file = new File([new Uint8Array(101 * 1024)], "big.svg", {
      type: "image/svg+xml",
    });

    await user.upload(fileInput(), file);

    expect(await screen.findByText("That file is too large.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects an oversized raster image", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(EMPTY);
    const file = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.png", {
      type: "image/png",
    });

    await user.upload(fileInput(), file);

    expect(await screen.findByText("That file is too large.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("clears the upload error on the next accepted upload", async () => {
    const onChange = renderEditor(EMPTY);

    const rejected = new File(["hello"], "notes.txt", { type: "text/plain" });
    await act(async () => {
      fireEvent.change(fileInput(), { target: { files: [rejected] } });
    });
    expect(
      screen.getByText("Use a PNG, JPG, WebP, GIF, or SVG image."),
    ).toBeInTheDocument();

    const accepted = svgFile();
    await act(async () => {
      fireEvent.change(fileInput(), { target: { files: [accepted] } });
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByText("Use a PNG, JPG, WebP, GIF, or SVG image."),
      ).not.toBeInTheDocument(),
    );
  });
});
