import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConnectKiwixModal from "@/components/knowledge/ConnectKiwixModal";

const catalog = vi.hoisted(() => ({
  listKiwixArchives: vi.fn(),
  probeKiwix: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/features/knowledge/api/catalog", () => ({
  listKiwixArchives: (...args: unknown[]) =>
    catalog.listKiwixArchives(...args),
  probeKiwix: (...args: unknown[]) => catalog.probeKiwix(...args),
}));

type Props = Parameters<typeof ConnectKiwixModal>[0];

function renderModal(overrides: Partial<Props> = {}) {
  const onClose = vi.fn();
  const onConnect = vi.fn();
  render(<ConnectKiwixModal onClose={onClose} onConnect={onConnect} {...overrides} />);
  return { onClose, onConnect };
}

const nameInput = () =>
  screen.getByLabelText("Knowledge base name") as HTMLInputElement;
const urlInput = () =>
  screen.getByLabelText("Kiwix server URL") as HTMLInputElement;
const zimInput = () => screen.getByLabelText("ZIM name") as HTMLInputElement;
const connectButton = () =>
  screen.getByRole("button", { name: "Connect archive" }) as HTMLButtonElement;
const browseButton = () =>
  screen.getByRole("button", { name: "Browse archives" }) as HTMLButtonElement;
const probeButton = () =>
  screen.getByRole("button", { name: "Check connection" }) as HTMLButtonElement;

describe("ConnectKiwixModal", () => {
  beforeEach(() => {
    catalog.listKiwixArchives.mockReset();
    catalog.probeKiwix.mockReset();
  });

  it("keeps Connect disabled until name, server URL and ZIM name are filled", () => {
    renderModal();
    expect(connectButton()).toBeDisabled();

    fireEvent.change(nameInput(), { target: { value: "wiki" } });
    expect(connectButton()).toBeDisabled();

    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    expect(connectButton()).toBeDisabled();

    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    expect(connectButton()).toBeEnabled();
  });

  it("disables browsing without a server URL and sends the trimmed query", async () => {
    catalog.listKiwixArchives.mockResolvedValue([
      { zim_name: "wikipedia_en_all", title: "Wikipedia" },
    ]);
    renderModal();

    expect(browseButton()).toBeDisabled();

    fireEvent.change(urlInput(), { target: { value: "  http://localhost:8080 " } });
    fireEvent.change(screen.getByLabelText("Find archive"), {
      target: { value: " wiki " },
    });
    fireEvent.click(browseButton());

    await waitFor(() => {
      expect(catalog.listKiwixArchives).toHaveBeenCalledWith(
        "http://localhost:8080",
        "wiki",
      );
    });
    expect(
      screen.getByLabelText("Loaded archives"),
    ).toBeInTheDocument();
    expect(screen.getByText("Wikipedia (wikipedia_en_all)")).toBeInTheDocument();
  });

  it("fills the ZIM name from the archive selector", async () => {
    catalog.listKiwixArchives.mockResolvedValue([
      { zim_name: "wikipedia_en_all", title: "Wikipedia" },
    ]);
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.click(browseButton());

    const select = (await screen.findByLabelText(
      "Loaded archives",
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "wikipedia_en_all" } });

    expect(zimInput().value).toBe("wikipedia_en_all");
  });

  it("reports a failed catalog browse as an alert", async () => {
    catalog.listKiwixArchives.mockRejectedValue(new Error("server down"));
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.click(browseButton());

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("server down");
    });
  });

  it("offers manual ZIM entry after an empty catalog browse", async () => {
    catalog.listKiwixArchives.mockResolvedValue([]);
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.click(browseButton());

    expect(
      await screen.findByText(
        "No archives returned. Enter the ZIM name manually or search by title.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Loaded archives")).toBeNull();
  });

  it("verifies the connection and shows the archive title", async () => {
    catalog.probeKiwix.mockResolvedValue({
      ok: true,
      title: "Wikipedia",
      zim_name: "wikipedia_en_all",
    });
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: " wikipedia_en_all " } });
    fireEvent.click(probeButton());

    await waitFor(() => {
      expect(catalog.probeKiwix).toHaveBeenCalledWith({
        serverUrl: "http://localhost:8080",
        zimName: "wikipedia_en_all",
      });
    });
    expect(await screen.findByText("Ready: Wikipedia")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears a stale verification when the ZIM name changes", async () => {
    catalog.probeKiwix.mockResolvedValue({
      ok: true,
      title: "Wikipedia",
      zim_name: "wikipedia_en_all",
    });
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    fireEvent.click(probeButton());
    expect(await screen.findByText("Ready: Wikipedia")).toBeInTheDocument();

    fireEvent.change(zimInput(), { target: { value: "wikipedia_fr_all" } });
    expect(screen.queryByText("Ready: Wikipedia")).toBeNull();
  });

  it("reports a probe failure and keeps the dialog open", async () => {
    catalog.probeKiwix.mockRejectedValue(new Error("connection refused"));
    renderModal();
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    fireEvent.click(probeButton());

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("connection refused");
    });
  });

  it("calls onClose after a successful connect", async () => {
    const onConnect = vi.fn().mockResolvedValue(undefined);
    const { onClose } = renderModal({ onConnect });
    fireEvent.change(nameInput(), { target: { value: "wiki" } });
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    fireEvent.click(connectButton());

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledWith({
        name: "wiki",
        serverUrl: "http://localhost:8080",
        zimName: "wikipedia_en_all",
      });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the dialog open and shows the error when connect fails", async () => {
    const onConnect = vi.fn().mockRejectedValue(new Error("name taken"));
    renderModal({ onConnect });
    fireEvent.change(nameInput(), { target: { value: "wiki" } });
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    fireEvent.click(connectButton());

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("name taken");
    });
  });

  it("closes via Cancel when idle", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("disables every action while a connect is in flight", async () => {
    let resolveConnect: (value: void) => void = () => {};
    const onConnect = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveConnect = resolve;
        }),
    );
    renderModal({ onConnect });
    fireEvent.change(nameInput(), { target: { value: "wiki" } });
    fireEvent.change(urlInput(), { target: { value: "http://localhost:8080" } });
    fireEvent.change(zimInput(), { target: { value: "wikipedia_en_all" } });
    fireEvent.click(connectButton());

    await waitFor(() => {
      expect(connectButton()).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(browseButton()).toBeDisabled();

    resolveConnect();
    await waitFor(() => {
      expect(connectButton()).toBeEnabled();
    });
  });
});
