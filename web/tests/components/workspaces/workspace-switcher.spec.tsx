import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "@/components/workspaces/WorkspaceSwitcher";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

const selectWorkspace = vi.hoisted(() => vi.fn());
const useChatWorkspaces = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams(),
}));

vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: (...args: unknown[]) => useChatWorkspaces(...args),
}));

vi.mock("@/lib/workspace-scope", () => ({
  selectWorkspace: (...args: unknown[]) => selectWorkspace(...args),
}));

function row(
  overrides: Partial<ChatWorkspaceRegistration>,
): ChatWorkspaceRegistration {
  return {
    workspace_id: "ws-1",
    kind: "workspace",
    follows_root: false,
    display_name: "Alpha",
    path: "/data/alpha",
    archived: false,
    created_at: "2026-10-12T00:00:00Z",
    status: "ready",
    error: "",
    ...overrides,
  } as ChatWorkspaceRegistration;
}

function renderSwitcher() {
  return render(<WorkspaceSwitcher />);
}

const select = () =>
  screen.getByLabelText("Active workspace") as HTMLSelectElement;

describe("WorkspaceSwitcher", () => {
  beforeEach(() => {
    selectWorkspace.mockReset();
    searchParams.mockReturnValue({ get: () => null });
    useChatWorkspaces.mockReturnValue({
      workspaces: [row({})],
      error: "",
    });
  });

  it("lists the default workspace first and ready workspaces after it", () => {
    useChatWorkspaces.mockReturnValue({
      workspaces: [
        row({ workspace_id: "ws-1", display_name: "Alpha" }),
        row({ workspace_id: "ws-2", display_name: "Beta" }),
      ],
      error: "",
    });
    renderSwitcher();

    const options = Array.from(select().options).map((o) => o.value);
    expect(options).toEqual(["", "ws-1", "ws-2"]);
    expect(select().value).toBe("");
  });

  it("hides archived workspaces unless one of them is active", () => {
    useChatWorkspaces.mockReturnValue({
      workspaces: [
        row({ workspace_id: "ws-live", display_name: "Live" }),
        row({ workspace_id: "ws-gone", display_name: "Gone", archived: true }),
      ],
      error: "",
    });
    const { rerender } = renderSwitcher();
    expect(screen.queryByRole("option", { name: /Archived/ })).toBeNull();

    searchParams.mockReturnValue({ get: (k: string) =>
      k === "dt_workspace" ? "ws-gone" : null });
    rerender(<WorkspaceSwitcher />);
    expect(
      screen.getByRole("option", { name: "Gone (Archived)" }),
    ).toBeInTheDocument();
  });

  it("disables workspaces that are not ready", () => {
    useChatWorkspaces.mockReturnValue({
      workspaces: [
        row({ workspace_id: "ws-bad", display_name: "Bad", status: "invalid" }),
      ],
      error: "",
    });
    renderSwitcher();
    expect(
      (screen.getByRole("option", { name: "Bad" }) as HTMLOptionElement)
        .disabled,
    ).toBe(true);
  });

  it("marks an active workspace missing from the list as unavailable", () => {
    searchParams.mockReturnValue({
      get: (k: string) => (k === "dt_workspace" ? "ws-vanished" : null),
    });
    renderSwitcher();
    expect(
      screen.getByRole("option", { name: "Workspace unavailable" }),
    ).toHaveProperty("value", "ws-vanished");
  });

  it("switches to the chosen workspace", () => {
    useChatWorkspaces.mockReturnValue({
      workspaces: [row({ workspace_id: "ws-2", display_name: "Beta" })],
      error: "",
    });
    renderSwitcher();

    fireEvent.change(select(), { target: { value: "ws-2" } });
    expect(selectWorkspace).toHaveBeenCalledTimes(1);
    expect(selectWorkspace).toHaveBeenCalledWith("ws-2");
  });

  it("falls back to the legacy query parameter for the active id", () => {
    searchParams.mockReturnValue({
      get: (k: string) => (k === "workspace" ? "ws-legacy" : null),
    });
    useChatWorkspaces.mockReturnValue({
      workspaces: [row({ workspace_id: "ws-legacy" })],
      error: "",
    });
    renderSwitcher();
    expect(select().value).toBe("ws-legacy");
  });

  it("surfaces the workspace load failure as an alert", () => {
    useChatWorkspaces.mockReturnValue({
      workspaces: [],
      error: "registrations endpoint down",
    });
    renderSwitcher();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "registrations endpoint down",
    );
  });

  it("reports a failed draft save through the window event", () => {
    renderSwitcher();
    expect(screen.queryByRole("alert")).toBeNull();

    act(() => {
      window.dispatchEvent(new window.Event("deeptutor:workspace-switch-error"));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not save the draft. Free browser storage before switching workspaces.",
    );
  });

  it("links to workspace management", () => {
    renderSwitcher();
    expect(
      screen.getByRole("link", { name: "Manage workspaces" }),
    ).toHaveAttribute("href", "/settings/workspace");
  });
});
