import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ComponentProps, ReactNode } from "react";

import {
  SidebarHome,
  SidebarNav,
} from "@/components/sidebar/SidebarNav";
import {
  DEFAULT_COLLAPSED_NAV,
  PRIMARY_NAV_HREFS,
} from "@/components/sidebar/nav-entries";
import {
  NAV_LAYOUT_STORAGE_KEY,
  readNavLayout,
} from "@/lib/sidebar-layout";
import {
  ActivityBody,
  buildSessionActivity,
  type SessionActivity,
  type SpaceReferenceSummary,
} from "@/components/chat/home/SessionActivityPanel";
import type {
  MessageAttachment,
  MessageItem,
} from "@/features/chat/ChatStateAdapter";

const MORE_EXPANDED_KEY = "deeptutor.sidebar.moreExpanded";
const LOCKED = "Locked — contact your administrator to get access.";
const MODULE_ORDER = PRIMARY_NAV_HREFS.filter((href) => href !== "/chat");

const fixture = vi.hoisted(() => {
  const t = (key: string, values?: Record<string, string | number>) =>
    key.replace(/\{\{(\w+)\}\}/g, (_match: string, name: string) =>
      String(values?.[name] ?? `{{${name}}}`)
    );
  return {
    t,
    pathname: "/chat",
    hasCapability: true,
    allowedSurfaces: null as readonly string[] | null,
    listSessions: vi.fn(),
    listNotebooks: vi.fn(),
    bookList: vi.fn(),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => fixture.pathname,
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    prefetch,
    onClick,
    ...props
  }: ComponentProps<"a"> & { children?: ReactNode; prefetch?: boolean }) => (
    <a
      {...props}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/components/access/CapabilityAccessContext", () => ({
  useCapabilityAccess: () => ({ has: () => fixture.hasCapability }),
}));

vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({
    enabled: false,
    authenticated: false,
    isAdmin: false,
    userId: null,
    statusAvailable: true,
    loading: false,
    learningPolicy:
      fixture.allowedSurfaces === null
        ? null
        : { allowedSurfaces: fixture.allowedSurfaces },
  }),
}));

vi.mock("@/lib/session-api", () => ({
  listSessions: fixture.listSessions,
}));

vi.mock("@/lib/notebook-api", () => ({
  listNotebooks: fixture.listNotebooks,
}));

vi.mock("@/lib/book-api", () => ({
  bookApi: { list: fixture.bookList },
}));

function renderNav(overrides?: Partial<ComponentProps<typeof SidebarNav>>) {
  const onHomeClick = vi.fn();
  const onNavigate = vi.fn();
  const view = render(
    <SidebarNav
      collapsed={false}
      onHomeClick={onHomeClick}
      onNavigate={onNavigate}
      {...overrides}
    />
  );
  return { ...view, onHomeClick, onNavigate };
}

function visibleHrefs(): Array<string | null> {
  return [...document.querySelectorAll("a[href]")].map((a) =>
    a.getAttribute("href")
  );
}

function openArrangeMenu(label: string) {
  fireEvent.click(screen.getByRole("button", { name: `Arrange ${label}` }));
  return screen.getByRole("menu");
}

function foldedIntoClosedDisclosure(el: HTMLElement): boolean {
  return el.closest('div[aria-hidden="true"]') !== null;
}

function anchorFor(href: string): HTMLAnchorElement {
  const anchor = document.querySelector(`a[href="${href}"]`);
  if (!(anchor instanceof HTMLAnchorElement)) {
    throw new Error(`expected an anchor for ${href}`);
  }
  return anchor;
}

beforeEach(() => {
  window.localStorage.clear();
  fixture.pathname = "/chat";
  fixture.hasCapability = true;
  fixture.allowedSurfaces = null;
  fixture.listSessions.mockResolvedValue([]);
  fixture.listNotebooks.mockResolvedValue([]);
  fixture.bookList.mockResolvedValue({ books: [] });
});

it("renders the shipped arrangement with two features folded into More", () => {
  renderNav();
  expect(visibleHrefs()).toEqual([...MODULE_ORDER]);
  const more = screen.getByRole("button", { name: /^More/ });
  expect(more).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("2")).toHaveAttribute("aria-hidden", "false");
  expect(foldedIntoClosedDisclosure(anchorFor("/co-writer"))).toBe(true);
  expect(foldedIntoClosedDisclosure(anchorFor("/agents"))).toBe(true);
  expect(foldedIntoClosedDisclosure(anchorFor("/partners"))).toBe(false);
});

it("highlights the active route and its sub-routes", () => {
  fixture.pathname = "/space";
  const { unmount } = renderNav();
  const active = screen.getByRole("link", { name: "Learning Space" });
  expect(active).toHaveClass("bg-[var(--accent)]");
  expect(screen.getByRole("link", { name: "Partners" })).not.toHaveClass(
    "bg-[var(--accent)]"
  );
  unmount();
  fixture.pathname = "/learning/topic-1";
  renderNav();
  expect(
    screen.getByRole("link", { name: "Personalized Learning" })
  ).toHaveClass("bg-[var(--accent)]");
});

it("expanding More reveals folded features and is remembered across remounts", () => {
  const { unmount } = renderNav();
  fireEvent.click(screen.getByRole("button", { name: /^More/ }));
  expect(screen.getByRole("button", { name: /^More/ })).toHaveAttribute(
    "aria-expanded",
    "true"
  );
  const cowriter = screen.getByRole("link", { name: "Co-Writer" });
  expect(foldedIntoClosedDisclosure(cowriter)).toBe(false);
  expect(screen.getByText("2").getAttribute("aria-hidden")).toBe("true");
  expect(window.localStorage.getItem(MORE_EXPANDED_KEY)).toBe("1");
  unmount();
  renderNav();
  expect(screen.getByRole("button", { name: /^More/ })).toHaveAttribute(
    "aria-expanded",
    "true"
  );
  expect(screen.getByRole("link", { name: "Co-Writer" })).toBeInTheDocument();
});

it("folds a visible feature into More from its arrange menu", () => {
  renderNav();
  const menu = openArrangeMenu("Partners");
  expect(menu).toHaveAttribute("aria-label", "Arrange sidebar");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move to More" }));
  expect(
    anchorFor("/partners").closest('div[aria-hidden="false"]')
  ).not.toBeNull();
  expect(screen.getByText("3")).toBeInTheDocument();
  expect(readNavLayout()).toEqual({
    order: [...MODULE_ORDER],
    collapsed: [...DEFAULT_COLLAPSED_NAV, "/partners"],
  });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("moves a folded feature out of More back to its saved position", () => {
  window.localStorage.setItem(
    NAV_LAYOUT_STORAGE_KEY,
    JSON.stringify({ order: [...PRIMARY_NAV_HREFS], collapsed: ["/partners"] })
  );
  renderNav();
  expect(
    screen.queryByRole("link", { name: "Partners" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^More/ }));
  openArrangeMenu("Partners");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move out of More" }));
  expect(screen.getByRole("link", { name: "Partners" })).toBeInTheDocument();
  expect(readNavLayout()?.collapsed).toEqual([]);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^More/ })
  ).not.toBeInTheDocument();
});

it("resets a customized arrangement back to the shipped one", () => {
  window.localStorage.setItem(
    NAV_LAYOUT_STORAGE_KEY,
    JSON.stringify({
      order: [...PRIMARY_NAV_HREFS].reverse(),
      collapsed: [],
    })
  );
  renderNav();
  expect(screen.queryByRole("button", { name: /^More/ })).not.toBeInTheDocument();
  openArrangeMenu("Task Board");
  fireEvent.click(screen.getByRole("menuitem", { name: "Reset sidebar order" }));
  expect(readNavLayout()).toEqual({
    order: [...PRIMARY_NAV_HREFS],
    collapsed: [...DEFAULT_COLLAPSED_NAV],
  });
  expect(screen.getByText("2")).toBeInTheDocument();
});

it("hides the reset action until the arrangement is customized", () => {
  renderNav();
  openArrangeMenu("Partners");
  expect(
    screen.queryByRole("menuitem", { name: "Reset sidebar order" })
  ).not.toBeInTheDocument();
});

it("closes the arrange menu on Escape and on an outside press", () => {
  renderNav();
  openArrangeMenu("Partners");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  openArrangeMenu("Partners");
  fireEvent.mouseDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("renders locked features as disabled rows with a lock hint", () => {
  fixture.hasCapability = false;
  renderNav();
  expect(
    screen.queryByRole("link", { name: "Partners" })
  ).not.toBeInTheDocument();
  const row = screen.getByLabelText(`Partners — ${LOCKED}`);
  expect(row).toHaveAttribute("aria-disabled", "true");
  expect(
    screen.getByRole("button", { name: "Arrange Partners" })
  ).toBeInTheDocument();
});

it("filters module rows under a learning policy and drops the More group", () => {
  fixture.allowedSurfaces = ["reading"];
  renderNav();
  expect(visibleHrefs()).toEqual(["/learning"]);
  expect(
    screen.queryByRole("button", { name: /^More/ })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Partners" })
  ).not.toBeInTheDocument();
});

it("reorders rows with the keyboard and persists the arrangement", () => {
  renderNav();
  const firstRow = screen.getByRole("button", {
    name: "Arrange Partners",
  }).parentElement as HTMLElement;
  fireEvent.keyDown(firstRow, { key: "ArrowDown", altKey: true });
  expect(readNavLayout()).toEqual({
    order: ["/learning", ...MODULE_ORDER.filter((h) => h !== "/learning")],
    collapsed: [...DEFAULT_COLLAPSED_NAV],
  });
  const firstAfter = screen.getByRole("button", {
    name: "Arrange Personalized Learning",
  }).parentElement as HTMLElement;
  expect(firstRow).not.toBe(firstAfter);
  expect(firstAfter.previousElementSibling).toBeNull();
});

it("renders the icon rail with an overflow menu for folded features", () => {
  const { onHomeClick, onNavigate } = renderNav({ collapsed: true });
  expect(visibleHrefs()).toEqual([
    "/partners",
    "/learning",
    "/space",
    "/kanban",
  ]);
  const overflow = screen.getByRole("button", { name: "More" });
  expect(overflow).toHaveAttribute("aria-haspopup", "menu");
  expect(overflow).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(overflow);
  expect(overflow).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("menu")).toHaveAttribute("aria-label", "More");
  fireEvent.click(screen.getByRole("menuitem", { name: "Co-Writer" }));
  expect(onNavigate).toHaveBeenCalledTimes(1);
  expect(onHomeClick).not.toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(overflow).toHaveAttribute("aria-expanded", "false");
});

it("toggles the rail overflow menu closed on a second press", () => {
  renderNav({ collapsed: true });
  const overflow = screen.getByRole("button", { name: "More" });
  fireEvent.click(overflow);
  expect(screen.getByRole("menu")).toBeInTheDocument();
  fireEvent.click(overflow);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("hides the rail overflow when nothing is folded", () => {
  window.localStorage.setItem(
    NAV_LAYOUT_STORAGE_KEY,
    JSON.stringify({ order: [...PRIMARY_NAV_HREFS], collapsed: [] })
  );
  renderNav({ collapsed: true });
  expect(
    screen.queryByRole("button", { name: "More" })
  ).not.toBeInTheDocument();
});

it("locks rail rows without the required capability", () => {
  fixture.hasCapability = false;
  renderNav({ collapsed: true });
  expect(
    screen.queryByRole("link", { name: "Partners" })
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText(`Partners — ${LOCKED}`)).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("renders the home row with the home click contract and active highlight", () => {
  const onHomeClick = vi.fn();
  render(<SidebarHome onHomeClick={onHomeClick} />);
  const link = screen.getByRole("link", { name: "Home" });
  expect(link).toHaveAttribute("href", "/chat");
  expect(link).toHaveClass("bg-[var(--accent)]");
  fireEvent.click(link);
  expect(onHomeClick).toHaveBeenCalledTimes(1);
});

it("hides the home row under a learning policy without the chat surface", () => {
  fixture.allowedSurfaces = ["reading"];
  const { container } = render(<SidebarHome onHomeClick={vi.fn()} />);
  expect(container).toBeEmptyDOMElement();
});

it("locks the home row without the llm capability", () => {
  fixture.hasCapability = false;
  render(<SidebarHome onHomeClick={vi.fn()} />);
  expect(
    screen.queryByRole("link", { name: "Home" })
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText(`Home — ${LOCKED}`)).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("renders a compact home row on the icon rail", () => {
  const onHomeClick = vi.fn();
  render(<SidebarHome collapsed onHomeClick={onHomeClick} />);
  const link = screen.getByRole("link", { name: "Home" });
  expect(link).toHaveAttribute("href", "/chat");
  fireEvent.click(link);
  expect(onHomeClick).toHaveBeenCalledTimes(1);
});

const emptySpace = (): SpaceReferenceSummary => ({
  historySessionIds: [],
  bookPageCount: 0,
  bookIds: [],
  bookPages: new Map(),
  notebookRecordCount: 0,
  notebookIds: [],
  questionEntryIds: [],
  personas: [],
  memoryKinds: [],
});

function makeActivity(partial: Partial<SessionActivity> = {}): SessionActivity {
  const space = partial.space ?? emptySpace();
  const tools = partial.tools ?? [];
  const knowledgeBases = partial.knowledgeBases ?? [];
  const attachments = partial.attachments ?? [];
  const artifacts = partial.artifacts ?? [];
  const isEmpty =
    tools.length === 0 &&
    knowledgeBases.length === 0 &&
    attachments.length === 0 &&
    artifacts.length === 0 &&
    space.historySessionIds.length === 0 &&
    space.bookIds.length === 0 &&
    space.notebookIds.length === 0 &&
    space.questionEntryIds.length === 0 &&
    space.personas.length === 0 &&
    space.memoryKinds.length === 0;
  return { tools, knowledgeBases, space, attachments, artifacts, isEmpty };
}

function renderActivity(
  activity: SessionActivity,
  open = true,
  configSection?: ReactNode
) {
  const onOpenAttachment = vi.fn();
  render(
    <ActivityBody
      activity={activity}
      open={open}
      onOpenAttachment={onOpenAttachment}
      configSection={configSection}
    />
  );
  return { onOpenAttachment };
}

it("shows the empty-activity guidance when nothing was used", () => {
  renderActivity(makeActivity());
  expect(screen.getByText("Session activity")).toBeInTheDocument();
  expect(
    screen.getByText(/As you chat, the tools and references/)
  ).toBeInTheDocument();
  expect(screen.queryByText("Tools used")).not.toBeInTheDocument();
  expect(screen.queryByText("Space")).not.toBeInTheDocument();
});

it("keeps a config section without guidance on an empty activity", () => {
  renderActivity(
    makeActivity(),
    true,
    <div data-testid="config-section">config</div>
  );
  expect(screen.queryByText(/As you chat/)).not.toBeInTheDocument();
  expect(screen.getByTestId("config-section")).toBeInTheDocument();
});

it("maps tool and knowledge base usage into sections with counts", () => {
  renderActivity(
    makeActivity({
      tools: [
        { name: "web_search", count: 2 },
        { name: "rag", count: 1 },
      ],
      knowledgeBases: ["textbook-kb"],
    })
  );
  expect(screen.getByText("Tools used")).toBeInTheDocument();
  expect(screen.getByText("web_search")).toBeInTheDocument();
  expect(screen.getByText("×2")).toBeInTheDocument();
  expect(screen.getByText("rag")).toBeInTheDocument();
  expect(screen.getByText("×1")).toBeInTheDocument();
  expect(screen.getByText("Knowledge bases")).toBeInTheDocument();
  expect(screen.getByText("textbook-kb")).toBeInTheDocument();
});

it("maps space references into subsections without resolving titles while closed", () => {
  const space = emptySpace();
  space.historySessionIds = ["sess-12345678-abcd"];
  space.bookIds = ["book-1"];
  space.bookPages = new Map([["book-1", ["p1", "p2"]]]);
  space.notebookIds = ["nb-1"];
  space.questionEntryIds = [42];
  space.personas = ["Tutor-X"];
  space.memoryKinds = ["summary"];
  renderActivity(makeActivity({ space }), false);
  expect(fixture.listSessions).not.toHaveBeenCalled();
  expect(fixture.listNotebooks).not.toHaveBeenCalled();
  expect(fixture.bookList).not.toHaveBeenCalled();
  expect(
    screen.getByRole("link", { name: /Chat history/ })
  ).toHaveAttribute("href", "/space/chat-history");
  expect(screen.getByRole("link", { name: /Books/ })).toHaveAttribute(
    "href",
    "/learning/books"
  );
  expect(screen.getByRole("link", { name: /Notebooks/ })).toHaveAttribute(
    "href",
    "/notebooks"
  );
  expect(
    screen.getByRole("link", { name: /Question bank/ })
  ).toHaveAttribute("href", "/space/questions");
  expect(screen.getByRole("link", { name: /Persona/ })).toHaveAttribute(
    "href",
    "/space/personas"
  );
  expect(screen.getByRole("link", { name: /Memory/ })).toHaveAttribute(
    "href",
    "/memory"
  );
  expect(screen.getByText("sess-12345678-abcd")).toBeInTheDocument();
  expect(screen.getByText("sess-123")).toBeInTheDocument();
  expect(screen.getByText("2 page(s)")).toBeInTheDocument();
  expect(screen.getByText("Question #42")).toBeInTheDocument();
  expect(screen.getByText("Tutor-X")).toBeInTheDocument();
  expect(screen.getByText("summary")).toBeInTheDocument();
});

it("resolves lazy titles from sessions, notebooks and books while open", async () => {
  fixture.listSessions.mockResolvedValue([
    {
      session_id: "sess-1",
      title: "My Old Chat",
      created_at: 0,
      updated_at: 0,
      message_count: 0,
      last_message: "",
    },
  ]);
  fixture.listNotebooks.mockResolvedValue([{ id: "nb-1", name: "Chem Notes" }]);
  fixture.bookList.mockResolvedValue({
    books: [{ id: "book-1", title: "Algebra" }],
  });
  const space = emptySpace();
  space.historySessionIds = ["sess-1"];
  space.notebookIds = ["nb-1"];
  space.bookIds = ["book-1"];
  renderActivity(makeActivity({ space }), true);
  await waitFor(() =>
    expect(screen.getByText("My Old Chat")).toBeInTheDocument()
  );
  expect(screen.getByText("Chem Notes")).toBeInTheDocument();
  expect(screen.getByText("Algebra")).toBeInTheDocument();
  expect(fixture.listSessions).toHaveBeenCalledTimes(1);
  expect(fixture.listSessions).toHaveBeenCalledWith(200);
});

it("falls back to raw ids when title lookups fail", async () => {
  fixture.listSessions.mockRejectedValue(new Error("network down"));
  const space = emptySpace();
  space.historySessionIds = ["sess-abcdef99"];
  renderActivity(makeActivity({ space }), true);
  await waitFor(() => expect(fixture.listSessions).toHaveBeenCalledTimes(1));
  expect(screen.getByText("sess-abcdef99")).toBeInTheDocument();
});

it("separates generated artifacts from uploads and opens them on click", () => {
  const artifact: MessageAttachment = {
    type: "file",
    filename: "report.txt",
    generated: true,
    size_bytes: 2048,
    url: "/files/outputs/2026/10/report.txt",
  };
  const upload: MessageAttachment = { type: "image", filename: "photo.svg" };
  const { onOpenAttachment } = renderActivity(
    makeActivity({
      artifacts: [{ messageIndex: 0, attachment: artifact }],
      attachments: [{ messageIndex: 1, attachment: upload }],
    })
  );
  expect(screen.getByText("Generated files")).toBeInTheDocument();
  expect(screen.getByText("Attachments")).toBeInTheDocument();
  expect(screen.getByText("TXT · 2.0 KB")).toBeInTheDocument();
  const tooltipTexts = screen
    .getAllByRole("tooltip")
    .map((node) => node.textContent);
  expect(tooltipTexts).toContain("report.txt. 2026/10/report.txt");
  expect(tooltipTexts).toContain("photo.svg");
  fireEvent.click(screen.getByRole("button", { name: /report\.txt/ }));
  expect(onOpenAttachment).toHaveBeenCalledTimes(1);
  expect(onOpenAttachment).toHaveBeenNthCalledWith(1, artifact);
  fireEvent.click(screen.getByRole("button", { name: /photo\.svg/ }));
  expect(onOpenAttachment).toHaveBeenCalledTimes(2);
  expect(onOpenAttachment).toHaveBeenNthCalledWith(2, upload);
});

it("falls back to untitled for attachments without a filename", () => {
  renderActivity(
    makeActivity({
      attachments: [{ messageIndex: 0, attachment: { type: "file" } }],
    })
  );
  expect(screen.getAllByText("untitled").length).toBeGreaterThan(0);
});

it("builds the activity from a transcript through the re-exported fold", () => {
  const messages: MessageItem[] = [
    {
      role: "assistant",
      content: "",
      events: [
        {
          type: "tool_call",
          content: "",
          metadata: { tool: "web_search" },
          source: "tool",
          stage: "responding",
          timestamp: 0,
        },
      ],
      requestSnapshot: {
        content: "",
        enabledTools: [],
        knowledgeBases: ["kb-a"],
        language: "en",
      },
    },
    {
      role: "assistant",
      content: "",
      attachments: [
        {
          type: "file",
          filename: "out.txt",
          generated: true,
          size_bytes: 10,
          url: "/files/outputs/out.txt",
        },
      ],
    },
  ];
  renderActivity(buildSessionActivity(messages));
  expect(screen.getByText("web_search")).toBeInTheDocument();
  expect(screen.getByText("×1")).toBeInTheDocument();
  expect(screen.getByText("kb-a")).toBeInTheDocument();
  expect(screen.getByText("Generated files")).toBeInTheDocument();
  expect(screen.getByText("out.txt")).toBeInTheDocument();
});
