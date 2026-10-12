import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PageIndexSettingsModal, {
  PageIndexConfigForm,
} from "@/components/knowledge/PageIndexSettingsModal";
import type { PageIndexConfig } from "@/features/knowledge/api/engines";

const fixture = vi.hoisted(() => ({
  t: (key: string) => key,
  get: vi.fn(),
  update: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/features/knowledge/api/engines", () => ({
  getPageIndexConfig: fixture.get,
  updatePageIndexConfig: fixture.update,
}));

const configured: PageIndexConfig = { api_key_set: true, configured: true };
const unconfigured: PageIndexConfig = { api_key_set: false, configured: false };

beforeEach(() => {
  fixture.get.mockReset().mockResolvedValue(unconfigured);
  fixture.update.mockReset().mockResolvedValue(unconfigured);
});

describe("PageIndexConfigForm", () => {
  it("renders a loading state until the config resolves, then the configured key state", async () => {
    let resolveGet!: (value: PageIndexConfig) => void;
    fixture.get.mockImplementation(
      () => new Promise<PageIndexConfig>((resolve) => (resolveGet = resolve)),
    );

    render(
      <PageIndexSettingsModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen.queryByPlaceholderText(/leave blank to keep/),
    ).not.toBeInTheDocument();

    await act(async () => {
      resolveGet(configured);
    });

    const input = await screen.findByPlaceholderText(/leave blank to keep/);
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Remove stored key" }),
    ).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("renders the unconfigured empty state without a stored key", async () => {
    render(
      <PageIndexSettingsModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />,
    );

    expect(
      await screen.findByPlaceholderText("Enter your PageIndex API key"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove stored key" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("surfaces the config load failure and keeps the inline form usable", async () => {
    fixture.get.mockRejectedValueOnce(new Error("PageIndex config unavailable"));
    const onError = vi.fn();

    render(<PageIndexConfigForm onError={onError} />);

    expect(await screen.findByText("PageIndex config unavailable")).toBeInTheDocument();
    expect(onError).toHaveBeenCalledWith("PageIndex config unavailable");
    expect(
      screen.getByPlaceholderText("Enter your PageIndex API key"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
  });

  it("saves a trimmed key, clears the field and reports success", async () => {
    fixture.update.mockResolvedValue(configured);
    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(
      <PageIndexSettingsModal isOpen onClose={onClose} onSaved={onSaved} />,
    );

    const input = await screen.findByPlaceholderText(
      "Enter your PageIndex API key",
    );
    fireEvent.change(input, { target: { value: "  sk-live-123  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fixture.update).toHaveBeenCalledWith({ api_key: "sk-live-123" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalled();
    expect(
      await screen.findByPlaceholderText(/leave blank to keep/),
    ).toHaveValue("");
  });

  it("keeps the stored key when saving with a blank input", async () => {
    fixture.get.mockResolvedValue(configured);
    const onClose = vi.fn();

    render(
      <PageIndexSettingsModal isOpen onClose={onClose} onSaved={vi.fn()} />,
    );

    await screen.findByPlaceholderText(/leave blank to keep/);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fixture.update).toHaveBeenCalledWith({}));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("shows the update failure, reports onError and does not close", async () => {
    fixture.update.mockRejectedValueOnce(new Error("Key rejected by provider"));
    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(
      <PageIndexSettingsModal isOpen onClose={onClose} onSaved={onSaved} />,
    );

    const input = await screen.findByPlaceholderText(
      "Enter your PageIndex API key",
    );
    fireEvent.change(input, { target: { value: "bad-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Key rejected by provider")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
  });

  it("removes the stored key", async () => {
    fixture.get.mockResolvedValue(configured);
    fixture.update.mockResolvedValue(unconfigured);

    render(
      <PageIndexSettingsModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Remove stored key" }));

    await waitFor(() => expect(fixture.update).toHaveBeenCalledWith({ api_key: "" }));
  });
});

describe("PageIndexSettingsModal", () => {
  it("renders nothing until opened and shows the dialog with a cancel action when open", async () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <PageIndexSettingsModal isOpen={false} onClose={onClose} />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    rerender(<PageIndexSettingsModal isOpen onClose={onClose} />);

    expect(
      await screen.findByRole("dialog", { name: "PageIndex settings" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByPlaceholderText("Enter your PageIndex API key"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Get an API key" })).toBeInTheDocument();
  });

  it("blocks closing the modal while a save is in flight, then closes on success", async () => {
    let resolveUpdate!: (value: PageIndexConfig) => void;
    fixture.update.mockImplementation(
      () => new Promise<PageIndexConfig>((resolve) => (resolveUpdate = resolve)),
    );
    const onClose = vi.fn();

    render(<PageIndexSettingsModal isOpen onClose={onClose} />);

    const input = await screen.findByPlaceholderText(
      "Enter your PageIndex API key",
    );
    fireEvent.change(input, { target: { value: "sk-pending" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fixture.update).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveUpdate(configured);
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
