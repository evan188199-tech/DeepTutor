import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LogoutButton } from "@/components/auth/LogoutButton";

const logout = vi.hoisted(() => vi.fn());
const routerReplace = vi.hoisted(() => vi.fn());
const useAuthStatus = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

vi.mock("@/lib/auth", () => ({
  logout: (...args: unknown[]) => logout(...args),
}));

vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: (...args: unknown[]) => useAuthStatus(...args),
}));

function renderButton(collapsed = false) {
  return render(<LogoutButton collapsed={collapsed} />);
}

describe("LogoutButton", () => {
  beforeEach(() => {
    logout.mockReset();
    routerReplace.mockReset();
    logout.mockResolvedValue(undefined);
  });

  it("renders nothing while auth is disabled", () => {
    useAuthStatus.mockReturnValue({ enabled: false });
    const { container } = renderButton();
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders a labelled button when auth is enabled and logs out on click", async () => {
    useAuthStatus.mockReturnValue({ enabled: true });
    renderButton();

    const button = screen.getByRole("button", { name: "Sign out" });
    expect(button).toHaveTextContent("Sign out");

    fireEvent.click(button);

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
      expect(logout).toHaveBeenCalledWith();
    });
    expect(routerReplace).toHaveBeenCalledTimes(1);
    expect(routerReplace).toHaveBeenCalledWith("/login");
    // Redirect only after the server session is gone.
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(
      routerReplace.mock.invocationCallOrder[0],
    );
  });

  it("renders the collapsed icon-only variant with an accessible name", async () => {
    useAuthStatus.mockReturnValue({ enabled: true });
    renderButton(true);

    const button = screen.getByRole("button", { name: "Sign out" });
    expect(button).not.toHaveTextContent("Sign out");

    fireEvent.click(button);
    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
    });
    expect(routerReplace).toHaveBeenCalledWith("/login");
  });

  it("does not redirect while the logout request is still pending", async () => {
    useAuthStatus.mockReturnValue({ enabled: true });
    let resolveLogout: (() => void) | undefined;
    logout.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLogout = resolve;
        }),
    );
    renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(routerReplace).not.toHaveBeenCalled();

    resolveLogout?.();
    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith("/login");
    });
  });
});
