import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppShell from "@/components/layout/AppShell";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";

const fixture = vi.hoisted(() => ({
  isMobile: false,
  pathname: "/chat",
  push: vi.fn(),
  close: vi.fn(),
}));

vi.mock("@/hooks/useDevice", () => ({
  useDevice: () => ({
    device: fixture.isMobile ? "mobile" : "desktop",
    isMobile: fixture.isMobile,
    isTablet: false,
    isDesktop: !fixture.isMobile,
    isCompact: fixture.isMobile,
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => fixture.pathname,
  useRouter: () => ({ push: fixture.push }),
}));

vi.mock("next/image", () => ({ default: () => null }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({
    enabled: false,
    authenticated: false,
    isAdmin: false,
    userId: null,
    statusAvailable: true,
    loading: false,
    learningPolicy: null,
  }),
}));

vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: () => ({ workspaces: [], error: "" }),
}));

vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    sidebarCollapsed: false,
    setSidebarCollapsed: vi.fn(),
  }),
}));

vi.mock("@/components/layout/AppShell", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/layout/AppShell")>();
  return { ...actual, useSidebarDrawer: () => ({ close: fixture.close }) };
});

vi.mock("@/components/sidebar/VersionBadge", () => ({
  VersionBadge: () => null,
}));

beforeEach(() => {
  fixture.isMobile = false;
  fixture.pathname = "/chat";
});

describe("AppShell navigation below the 768px breakpoint (#366)", () => {
  const renderShell = () =>
    render(
      <AppShell sidebar={<nav aria-label="Sections">SIDEBAR-NAV</nav>}>
        <p>CONTENT</p>
      </AppShell>,
    );

  const panelWrapper = (container: HTMLElement) =>
    container.querySelector('nav[aria-label="Sections"]')?.parentElement ?? null;

  it("keeps the shell free of horizontal scroll and owns a mobile-only top bar", () => {
    fixture.isMobile = true;
    const { container } = renderShell();
    expect(container.firstElementChild?.className).toContain("overflow-hidden");

    const toggle = screen.getByRole("button", { name: "Open navigation" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const topBar = toggle.closest("div");
    expect(topBar?.className).toContain("md:hidden");
    expect(topBar?.className).not.toContain("lg:hidden");
  });

  it("parks the panel off-canvas and inert until the top bar opens it", () => {
    fixture.isMobile = true;
    const { container } = renderShell();
    const wrapper = panelWrapper(container);
    expect(wrapper).not.toBeNull();
    expect(wrapper?.className).toContain("max-md:fixed");
    expect(wrapper?.className).toContain("max-md:-translate-x-full");
    expect(wrapper?.hasAttribute("inert")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(wrapper?.className).toContain("max-md:translate-x-0");
    expect(wrapper?.className).not.toContain("max-md:-translate-x-full");
    expect(wrapper?.hasAttribute("inert")).toBe(false);
  });

  const scrimOf = (container: HTMLElement) =>
    [...container.querySelectorAll('div[aria-hidden="true"]')].find((el) =>
      el.className.includes("fixed"),
    ) ?? null;

  it("dismisses the drawer through a mobile-only scrim", () => {
    fixture.isMobile = true;
    const { container } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));

    const scrim = scrimOf(container);
    expect(scrim?.className).toContain("md:hidden");
    expect(scrim?.className).toContain("fixed inset-0");

    fireEvent.click(scrim as HTMLElement);
    expect(panelWrapper(container)?.className).toContain(
      "max-md:-translate-x-full",
    );
    expect(scrimOf(container)).toBeNull();
  });

  it("hands the screen back to the content on route change", () => {
    fixture.isMobile = true;
    const view = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(panelWrapper(view.container)?.className).toContain(
      "max-md:translate-x-0",
    );

    fixture.pathname = "/chat/session-1";
    view.rerender(
      <AppShell sidebar={<nav aria-label="Sections">SIDEBAR-NAV</nav>}>
        <p>CONTENT</p>
      </AppShell>,
    );
    expect(panelWrapper(view.container)?.className).toContain(
      "max-md:-translate-x-full",
    );
  });

  it("leaves the desktop layout interactive: panel inline and never inert", () => {
    const { container } = renderShell();
    const wrapper = panelWrapper(container);
    expect(wrapper?.hasAttribute("inert")).toBe(false);
    expect(scrimOf(container)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Open navigation" }).closest("div")
        ?.className,
    ).toContain("md:hidden");
  });
});

describe("SidebarShell as the collapsible panel below the 768px breakpoint (#366)", () => {
  it("caps the drawer width below md so it cannot crowd out the content", () => {
    const { container } = render(<SidebarShell />);
    const aside = container.querySelector("aside");
    expect(aside?.className).toContain("max-md:w-[220px]");
    expect(aside?.className).toContain("max-md:max-w-[85vw]");
    expect(aside?.className).toContain("w-[var(--sidebar-width)]");
  });

  it("keeps the desktop collapse toggle and resize handle md-only", () => {
    const { container } = render(<SidebarShell />);
    const collapse = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(collapse.className).toContain("max-md:hidden");

    const resize = screen.getByRole("separator", {
      name: "Resize sidebar",
    });
    expect(resize.className).toContain("max-md:hidden");
  });

  it("drops the drag-resize handle entirely on mobile", () => {
    fixture.isMobile = true;
    render(<SidebarShell />);
    expect(
      screen.queryByRole("separator", { name: "Resize sidebar" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Collapse sidebar" }),
    ).not.toBeNull();
  });
});

describe("chat markdown content below the 768px breakpoint (#366)", () => {
  const tableMarkdown = [
    "| Tool | Purpose | Status |",
    "| --- | --- | --- |",
    "| Search | Find sources | ready |",
    "| Quiz | Practice questions | ready |",
  ].join("\n");

  it("keeps wide tables scrollable inside the message column (simple path)", () => {
    const { container } = render(
      <MarkdownRenderer content={tableMarkdown} />,
    );
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.parentElement?.className).toContain("overflow-x-auto");
    expect(table?.className).toContain("min-w-full");
  });

  it("keeps wide tables scrollable on the rich renderer path", async () => {
    const { container } = render(
      <MarkdownRenderer
        content={`${"```\nconst x = 1;\n```"}\n\n${tableMarkdown}`}
        trackSourceLines
      />,
    );
    await waitFor(() => {
      expect(container.querySelector("table")).not.toBeNull();
    });
    const table = container.querySelector("table");
    expect(table?.parentElement?.className).toContain("overflow-x-auto");
    expect(table?.className).toContain("min-w-full");
  });
});
