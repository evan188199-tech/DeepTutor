import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LinkFolderModal from "@/components/knowledge/LinkFolderModal";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

function renderModal(overrides?: Partial<{
  onClose: () => void;
  onSubmit: (folderPath: string) => Promise<void>;
}>) {
  const onClose = overrides?.onClose ?? vi.fn();
  const onSubmit =
    overrides?.onSubmit ?? vi.fn<(folderPath: string) => Promise<void>>().mockResolvedValue(undefined);
  render(<LinkFolderModal isOpen onClose={onClose} onSubmit={onSubmit} />);
  return { onClose, onSubmit };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LinkFolderModal", () => {
  it("requires a folder path before submitting", async () => {
    const { onSubmit } = renderModal();

    await screen.findByRole("dialog", { name: "Link a local folder" });
    fireEvent.click(screen.getByRole("button", { name: "Link folder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Folder path is required.",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("flags an empty path on blur and clears the error while typing", async () => {
    renderModal();

    const input = await screen.findByLabelText("Folder path");
    fireEvent.blur(input);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Folder path is required.",
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining("linked-folder-error"),
    );

    fireEvent.change(input, { target: { value: " " } });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "false");
  });

  it("submits the trimmed path and closes on success", async () => {
    const { onClose, onSubmit } = renderModal();

    const input = await screen.findByLabelText("Folder path");
    fireEvent.change(input, { target: { value: "  /Users/me/Notes  " } });
    fireEvent.click(screen.getByRole("button", { name: "Link folder" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("/Users/me/Notes"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("keeps the dialog open and surfaces the failure when linking is rejected", async () => {
    const { onClose } = renderModal({
      onSubmit: vi.fn().mockRejectedValue(new Error("Folder does not exist")),
    });

    const input = await screen.findByLabelText("Folder path");
    fireEvent.change(input, { target: { value: "/missing" } });
    fireEvent.click(screen.getByRole("button", { name: "Link folder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Folder does not exist",
    );
    expect(onClose).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Link folder" })).toBeEnabled(),
    );
  });

  it("disables the actions and shows progress while linking", async () => {
    let resolveSubmit!: () => void;
    const { onClose } = renderModal({
      onSubmit: vi
        .fn()
        .mockImplementation(() => new Promise<void>((resolve) => (resolveSubmit = resolve))),
    });

    const input = await screen.findByLabelText("Folder path");
    fireEvent.change(input, { target: { value: "/notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Link folder" }));

    expect(await screen.findByRole("button", { name: "Linking…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveSubmit();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("resets the input and error each time the modal reopens", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn<(folderPath: string) => Promise<void>>().mockResolvedValue(undefined);
    const { rerender } = render(
      <LinkFolderModal isOpen={false} onClose={onClose} onSubmit={onSubmit} />,
    );

    rerender(<LinkFolderModal isOpen onClose={onClose} onSubmit={onSubmit} />);
    const input = await screen.findByLabelText("Folder path");
    fireEvent.change(input, { target: { value: "/stale-path" } });
    fireEvent.blur(input);

    rerender(<LinkFolderModal isOpen={false} onClose={onClose} onSubmit={onSubmit} />);
    rerender(<LinkFolderModal isOpen onClose={onClose} onSubmit={onSubmit} />);

    const reopened = await screen.findByLabelText("Folder path");
    expect(reopened).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
