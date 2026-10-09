import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MaterialLibraryPage } from "@/components/reading/library/MaterialLibrary";
import { ReadingLibraryPage } from "@/components/reading/library/ReadingLibrary";
import type {
  ReadingLibraryMaterial,
  ReadingWorkspace,
} from "@/lib/reading-workspace-api";

const mocks = vi.hoisted(() => {
  const interpolate = (key: string, options?: Record<string, unknown>) =>
    options
      ? key.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
          Object.prototype.hasOwnProperty.call(options, name)
            ? String(options[name])
            : match,
        )
      : key;
  return {
    push: vi.fn(),
    replace: vi.fn(),
    query: "",
    library: vi.fn(),
    deleteWorkspace: vi.fn(),
    retryMaterial: vi.fn(),
    deleteMaterial: vi.fn(),
    addMaterial: vi.fn(),
    listCourses: vi.fn(),
    attachResource: vi.fn(),
    t: interpolate,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t, i18n: { language: "en" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  usePathname: () => "/learning/reading",
  useSearchParams: () => new URLSearchParams(mocks.query),
}));

vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: () => ({
    workspaces: [
      { workspace_id: "team", display_name: "Team", status: "ready" },
    ],
    error: "",
  }),
}));

vi.mock("@/lib/learning-library", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/learning-library")>()),
  learningLibrary: mocks.library,
}));

vi.mock("@/lib/reading-workspace-api", () => ({
  deleteReadingWorkspace: mocks.deleteWorkspace,
  retryReadingMaterial: mocks.retryMaterial,
  deleteReadingMaterial: mocks.deleteMaterial,
  addReadingWorkspaceMaterial: mocks.addMaterial,
}));

vi.mock("@/lib/courses-api", () => ({
  listCourses: mocks.listCourses,
  attachCourseResource: mocks.attachResource,
}));

vi.mock("@/components/reading/library/InvidiousAccountFeedback", () => ({
  default: () => null,
}));

vi.mock("@/components/reading/library/FolderDialog", () => ({
  FolderDialog: ({
    collection,
    workspaceId,
    lockWorkspace,
    onClose,
    onSaved,
  }: {
    collection?: { title: string };
    workspaceId?: string;
    lockWorkspace?: boolean;
    onClose: () => void;
    onSaved: (collection: unknown, workspaceId: string) => void;
  }) => (
    <div
      data-testid="folder-dialog"
      data-mode={collection ? "edit" : "create"}
      data-workspace-id={workspaceId ?? ""}
      data-lock={lockWorkspace ? "true" : "false"}
      data-collection={collection?.title ?? ""}
    >
      <button type="button" onClick={onClose}>
        Folder dialog close
      </button>
      <button
        type="button"
        onClick={() => onSaved({ workspace_id: "new-ws" }, "ws-2")}
      >
        Folder dialog save
      </button>
    </div>
  ),
}));

vi.mock("@/components/reading/library/AddMaterialsDialog", () => ({
  AddMaterialsDialog: ({
    mode,
    onClose,
    onDone,
  }: {
    mode: string;
    onClose: () => void;
    onDone: (result?: { workspace?: { workspace_id: string } }) => void;
  }) => (
    <div data-testid="add-materials-dialog" data-mode={mode}>
      <button type="button" onClick={onClose}>
        Add dialog close
      </button>
      <button
        type="button"
        onClick={() =>
          onDone(
            mode === "create"
              ? { workspace: { workspace_id: "created-ws" } }
              : undefined,
          )
        }
      >
        Add dialog done
      </button>
    </div>
  ),
}));

const T0 = 1_700_000_000;

function materialFixture(
  overrides: Partial<ReadingLibraryMaterial> = {},
): ReadingLibraryMaterial {
  return {
    material_id: "mat-1",
    content_id: "content-1",
    filename: "paper.pdf",
    title: "Paper",
    source_kind: "file",
    source_url: "",
    mime: "application/pdf",
    render_mode: "pdf",
    cover_url: "",
    duration_seconds: 0,
    status: "ready",
    progress: 100,
    error_code: "",
    error_detail: "",
    created_at: T0,
    updated_at: T0,
    last_opened_at: 0,
    size_bytes: 1_258_291,
    unit_count: 5,
    collections: [],
    quiz_stars: 0,
    content_workspace_id: "",
    content_workspace_name: "Default workspace",
    ...overrides,
  };
}

function collectionFixture(
  overrides: Partial<ReadingWorkspace> = {},
): ReadingWorkspace {
  return {
    workspace_id: "ws-1",
    title: "Thesis",
    description: "reading list",
    color: "",
    active_material_id: null,
    created_at: T0,
    updated_at: T0 + 300,
    tabs: [],
    content_workspace_id: "",
    content_workspace_name: "Default workspace",
    ...overrides,
  };
}

const tab = (material: ReadingLibraryMaterial, tab_order = 0) => ({
  material,
  tab_order,
  pinned: false,
  opened: false,
  added_at: T0,
});

type LibraryFixtures = {
  materials?: ReadingLibraryMaterial[];
  collections?: ReadingWorkspace[];
  unavailable?: string[];
  failMaterials?: Error;
  failCollections?: Error;
};

function primeLibrary({
  materials = [],
  collections = [],
  unavailable = [],
  failMaterials,
  failCollections,
}: LibraryFixtures = {}) {
  mocks.library.mockImplementation(async (kind: string) => {
    if (kind === "reading") {
      if (failCollections) throw failCollections;
      return {
        items: collections,
        unavailable_workspaces: unavailable,
        can_create: true,
      };
    }
    if (failMaterials) throw failMaterials;
    return {
      items: materials,
      unavailable_workspaces: unavailable,
      can_create: true,
    };
  });
}

function setUrl(search: string, pathname = "/learning/reading") {
  mocks.query = search.replace(/^\?/, "");
  window.history.replaceState({}, "", `${pathname}${search}`);
}

function closestLi(element: Element): HTMLElement {
  const li = element.closest("li");
  if (!li) throw new Error("expected the row to sit inside an <li>");
  return li as HTMLElement;
}

function folderTitles(): (string | null)[] {
  return Array.from(
    document.querySelectorAll<HTMLAnchorElement>(
      'a[href^="/learning/reading/folders/"]',
    ),
  ).map(node => node.querySelector("span.line-clamp-2")?.textContent ?? null);
}

/** The default shelf used by the material-library tests. */
const materialShelf = (): ReadingLibraryMaterial[] => [
  materialFixture({
    material_id: "mat-1",
    title: "Paper",
    collections: [{ workspace_id: "col-1", title: "Thesis" }],
    content_workspace_id: "ws-2",
    content_workspace_name: "Team",
  }),
  materialFixture({
    material_id: "mat-2",
    title: "Lecture notes",
    filename: "ghost.mp3",
    source_kind: "audio",
    render_mode: "audio",
    duration_seconds: 95,
    quiz_stars: 3,
  }),
  materialFixture({
    material_id: "mat-3",
    title: "Clip",
    filename: "clip.mov",
    source_kind: "video",
    render_mode: "video",
    status: "processing",
    progress: 40,
  }),
  materialFixture({
    material_id: "mat-4",
    title: "Broken scan",
    filename: "broken.pdf",
    status: "failed",
    error_detail: "The file could not be parsed.",
  }),
];

const shelfCollections = (): ReadingWorkspace[] => [
  collectionFixture({ workspace_id: "col-1", title: "Thesis" }),
  collectionFixture({
    workspace_id: "col-2",
    title: "Course pack",
    content_workspace_id: "ws-2",
    content_workspace_name: "Team",
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
  mocks.deleteWorkspace.mockResolvedValue({});
  mocks.retryMaterial.mockResolvedValue({});
  mocks.deleteMaterial.mockResolvedValue({});
  mocks.addMaterial.mockResolvedValue({});
  setUrl("");
  primeLibrary();
});

describe("ReadingLibraryPage collections shelf", () => {
  it("renders shelves grouped by workspace with folder facts and open-entry links", async () => {
    primeLibrary({
      collections: [
        collectionFixture({
          workspace_id: "ws-1",
          title: "Thesis",
          tabs: [
            tab(materialFixture()),
            tab(
              materialFixture({
                material_id: "mat-2",
                status: "processing",
                progress: 30,
              }),
            ),
          ],
        }),
        collectionFixture({
          workspace_id: "ws-3",
          title: "Course pack",
          content_workspace_id: "team",
          content_workspace_name: "Team",
          updated_at: T0 + 100,
        }),
      ],
    });
    render(<ReadingLibraryPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(
      await screen.findByRole("region", {
        name: "Workspace Default workspace",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Workspace Team" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 collections")).toBeInTheDocument();
    const thesis = screen.getByRole("link", { name: /Thesis/ });
    expect(thesis).toHaveAttribute("href", "/learning/reading/folders/ws-1");
    expect(thesis).toHaveTextContent("2 files");
    expect(thesis).toHaveTextContent(/2023/);
    expect(within(thesis).getByLabelText("Preparing")).toBeInTheDocument();
    const pack = screen.getByRole("link", { name: /Course pack/ });
    expect(pack).toHaveAttribute(
      "href",
      "/learning/reading/folders/ws-3?dt_workspace=team",
    );
    expect(pack).toHaveTextContent("Empty");
  });

  it("shows the empty-library pitch and opens the create dialog", async () => {
    render(<ReadingLibraryPage />);
    expect(await screen.findByText("No collections yet")).toBeInTheDocument();
    expect(
      screen.getByText(
        "A collection is one reading task: a paper with its survey, every lecture of a course, a few chapters of a book. Everything in it shares the same conversations and annotations.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("0 collections")).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "New collection" })[0],
    );
    const dialog = screen.getByTestId("folder-dialog");
    expect(dialog).toHaveAttribute("data-mode", "create");
    expect(dialog).toHaveAttribute("data-workspace-id", "");
    expect(dialog).toHaveAttribute("data-lock", "false");
  });

  it("routes to the new folder after creating from the header action", async () => {
    render(<ReadingLibraryPage />);
    await screen.findByText("0 collections");
    fireEvent.click(
      screen.getAllByRole("button", { name: "New collection" })[0],
    );
    fireEvent.click(screen.getByRole("button", { name: "Folder dialog save" }));
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        "/learning/reading/folders/new-ws?dt_workspace=ws-2",
      ),
    );
    expect(screen.queryByTestId("folder-dialog")).toBeNull();
  });

  it("filters collections by search, hides the create pitch on no match, and can clear", async () => {
    primeLibrary({
      collections: [
        collectionFixture({ workspace_id: "ws-1", title: "Thesis" }),
        collectionFixture({ workspace_id: "ws-2", title: "Course pack" }),
      ],
    });
    render(<ReadingLibraryPage />);
    await screen.findByRole("link", { name: /Course pack/ });
    const input = screen.getByPlaceholderText("Search collections and materials");
    fireEvent.change(input, { target: { value: "Thesis" } });
    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: /Course pack/ }),
      ).toBeNull(),
    );
    expect(screen.getByRole("link", { name: /Thesis/ })).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(
      await screen.findByText("Nothing matches that."),
    ).toBeInTheDocument();
    expect(screen.queryByText("No collections yet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(
      await screen.findByRole("link", { name: /Course pack/ }),
    ).toBeInTheDocument();
  });

  it("sorts the shelf by recency and by name", async () => {
    primeLibrary({
      collections: [
        collectionFixture({
          workspace_id: "ws-a",
          title: "Zulu notes",
          updated_at: T0 + 300,
        }),
        collectionFixture({
          workspace_id: "ws-b",
          title: "alpha",
          updated_at: T0 + 200,
        }),
        collectionFixture({
          workspace_id: "ws-c",
          title: "Beta",
          updated_at: T0 + 100,
        }),
      ],
    });
    render(<ReadingLibraryPage />);
    await screen.findByRole("link", { name: /Zulu notes/ });
    expect(folderTitles()).toEqual(["Zulu notes", "alpha", "Beta"]);
    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(folderTitles()).toEqual(["alpha", "Beta", "Zulu notes"]);
    fireEvent.click(screen.getByRole("button", { name: "Recent" }));
    expect(folderTitles()).toEqual(["Zulu notes", "alpha", "Beta"]);
  });

  it("shows the error state with retry and never claims an empty library", async () => {
    primeLibrary({
      failMaterials: new Error("offline"),
      failCollections: new Error("offline"),
    });
    render(<ReadingLibraryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
    expect(screen.queryByText("No collections yet")).toBeNull();
    expect(mocks.library).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocks.library).toHaveBeenCalledTimes(4));
  });

  it("warns about unavailable workspaces while showing what loaded", async () => {
    primeLibrary({
      collections: [collectionFixture()],
      unavailable: ["team"],
    });
    render(<ReadingLibraryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some workspaces could not be loaded. Available content is shown.",
    );
    expect(screen.getByRole("link", { name: /Thesis/ })).toBeInTheDocument();
  });

  it("surfaces unsettled materials with retry for failures", async () => {
    primeLibrary({
      collections: [collectionFixture()],
      materials: [
        materialFixture({
          material_id: "mat-f",
          title: "Broken scan",
          status: "failed",
          error_detail: "The file could not be parsed.",
        }),
        materialFixture({
          material_id: "mat-p",
          title: "Slow scan",
          status: "processing",
          progress: 42,
        }),
      ],
    });
    render(<ReadingLibraryPage />);
    expect(
      await screen.findByText(/Broken scan could not be prepared/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The file could not be parsed."),
    ).toBeInTheDocument();
    expect(screen.getByText("Preparing Slow scan")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(mocks.retryMaterial).toHaveBeenCalledWith("mat-f", ""),
    );
  });

  it("opens the folder menu with start-reading and rename branches", async () => {
    primeLibrary({ collections: [collectionFixture()] });
    render(<ReadingLibraryPage />);
    const tile = await screen.findByRole("link", { name: /Thesis/ });
    const li = closestLi(tile);
    const menuButton = within(li).getByRole("button", {
      name: "Collection menu",
    });
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Start reading" }),
    ).toHaveAttribute("href", "/learning/reading/ws-1");
    fireEvent.click(
      screen.getByRole("menuitem", { name: "Rename or recolor" }),
    );
    const dialog = screen.getByTestId("folder-dialog");
    expect(dialog).toHaveAttribute("data-mode", "edit");
    expect(dialog).toHaveAttribute("data-collection", "Thesis");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("deletes a collection from its menu and refreshes", async () => {
    primeLibrary({
      collections: [
        collectionFixture({
          workspace_id: "ws-1",
          title: "Thesis",
          tabs: [
            tab(materialFixture()),
            tab(materialFixture({ material_id: "mat-2" })),
          ],
        }),
      ],
    });
    render(<ReadingLibraryPage />);
    const tile = await screen.findByRole("link", { name: /Thesis/ });
    fireEvent.click(
      within(closestLi(tile)).getByRole("button", { name: "Collection menu" }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: "Delete collection" }),
    );
    expect(
      screen.getByText(
        "“Thesis” and its reading conversations will be deleted. The 2 materials in it stay in your library.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(mocks.deleteWorkspace).toHaveBeenCalledWith("ws-1", ""),
    );
    await waitFor(() =>
      expect(
        screen.queryByText(
          "“Thesis” and its reading conversations will be deleted. The 2 materials in it stay in your library.",
        ),
      ).toBeNull(),
    );
  });

  it("offers per-workspace creation when several workspaces are mixed", async () => {
    primeLibrary({
      collections: [
        collectionFixture({ workspace_id: "ws-1", title: "Default shelf" }),
        collectionFixture({
          workspace_id: "ws-2",
          title: "Team shelf",
          content_workspace_id: "team",
          content_workspace_name: "Team",
          updated_at: T0,
        }),
      ],
    });
    render(<ReadingLibraryPage />);
    await screen.findByRole("link", { name: /Default shelf/ });
    expect(screen.getByLabelText("Filter by workspace")).toBeInTheDocument();
    const here = screen.getAllByRole("button", { name: "New collection here" });
    expect(here).toHaveLength(2);
    fireEvent.click(here[1]);
    expect(screen.getByTestId("folder-dialog")).toHaveAttribute(
      "data-workspace-id",
      "team",
    );
    fireEvent.click(screen.getByRole("button", { name: "Folder dialog close" }));
    fireEvent.click(here[0]);
    expect(screen.getByTestId("folder-dialog")).toHaveAttribute(
      "data-workspace-id",
      "",
    );
  });

  it("narrows a course shelf to referenced collections and locks the workspace", async () => {
    mocks.listCourses.mockResolvedValue([
      {
        id: "course-1",
        name: "My course",
        resources: [{ kind: "reading_workspace", ref_id: "ws-2" }],
      },
    ]);
    primeLibrary({
      collections: [
        collectionFixture({ workspace_id: "ws-1", title: "Private shelf" }),
        collectionFixture({ workspace_id: "ws-2", title: "Course shelf" }),
      ],
    });
    setUrl("?course=course-1");
    render(<ReadingLibraryPage />);
    expect(
      await screen.findByRole("link", { name: /Course shelf/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Private shelf/ })).toBeNull();
    expect(
      await screen.findByRole("link", { name: /My course/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New collection here" }),
    ).toBeNull();
    fireEvent.click(
      screen.getAllByRole("button", { name: "New collection" })[0],
    );
    expect(screen.getByTestId("folder-dialog")).toHaveAttribute(
      "data-lock",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Folder dialog save" }));
    await waitFor(() =>
      expect(mocks.attachResource).toHaveBeenCalledWith("course-1", {
        kind: "reading_workspace",
        label: undefined,
        ref_id: "new-ws",
      }),
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        "/learning/reading/folders/new-ws?dt_workspace=ws-2",
      ),
    );
  });
});

describe("MaterialLibraryPage material list", () => {
  it("renders rows with type facts, collection chips and quiz stars", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-1",
          title: "Paper",
          collections: [
            { workspace_id: "col-1", title: "Thesis" },
            { workspace_id: "col-2", title: "Course pack" },
            { workspace_id: "col-3", title: "Side notes" },
          ],
        }),
        materialFixture({
          material_id: "mat-2",
          title: "Lecture notes",
          filename: "ghost.mp3",
          source_kind: "audio",
          render_mode: "audio",
          duration_seconds: 95,
          quiz_stars: 3,
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    expect(await screen.findByText("2 materials")).toBeInTheDocument();
    const row = closestLi(screen.getByRole("button", { name: "Paper" }));
    expect(
      within(row).getAllByText(/PDF/).length,
    ).toBeGreaterThan(0);
    const chips = within(row).getAllByRole("link");
    expect(
      chips.map(chip => [chip.textContent, chip.getAttribute("href")]),
    ).toEqual([
      ["Thesis", "/learning/reading/folders/col-1"],
      ["Course pack", "/learning/reading/folders/col-2"],
    ]);
    expect(within(row).getByText("+1")).toBeInTheDocument();
    const audio = closestLi(
      screen.getByRole("button", { name: "Lecture notes" }),
    );
    expect(within(audio).getAllByText(/MP3/).length).toBeGreaterThan(0);
    expect(within(audio).getByLabelText("Quiz stars: 3")).toBeInTheDocument();
  });

  it("narrows the list with status filter chips", async () => {
    primeLibrary({
      materials: materialShelf(),
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    expect(
      await screen.findByRole("button", { name: "Paper" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Not in a collection3" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preparing1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Failed1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Failed1" }));
    expect(
      screen.getByRole("button", { name: "Broken scan" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paper" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Preparing1" }));
    expect(screen.getByRole("button", { name: "Clip" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Broken scan" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByRole("button", { name: "Paper" })).toBeInTheDocument();
  });

  it("distinguishes the empty-library, filtered and search empty states", async () => {
    render(<MaterialLibraryPage />);
    expect(
      await screen.findByText("Everything you upload shows up here."),
    ).toBeInTheDocument();
    primeLibrary({
      materials: [
        materialFixture({
          collections: [{ workspace_id: "col-1", title: "Thesis" }],
        }),
      ],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Not in a collection" }),
    );
    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
    fireEvent.change(
      screen.getByPlaceholderText("Search by title, file name or link"),
      { target: { value: "zzz" } },
    );
    expect(
      await screen.findByText("Nothing matches that."),
    ).toBeInTheDocument();
  });

  it("searches by title and file name and restores with the clear button", async () => {
    primeLibrary({
      materials: materialShelf(),
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    await screen.findByRole("button", { name: "Paper" });
    fireEvent.change(
      screen.getByPlaceholderText("Search by title, file name or link"),
      { target: { value: "ghost" } },
    );
    expect(
      screen.getByRole("button", { name: "Lecture notes" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paper" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: "Paper" })).toBeInTheDocument();
  });

  it("opens an assigned material's first collection", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-1",
          title: "Paper",
          collections: [{ workspace_id: "col-1", title: "Thesis" }],
          content_workspace_id: "ws-2",
          content_workspace_name: "Team",
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Paper" }));
    expect(mocks.push).toHaveBeenCalledWith(
      "/learning/reading/col-1?dt_workspace=ws-2",
    );
  });

  it("opens the assign dialog for an unassigned material with its workspace's collections", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-2",
          title: "Lecture notes",
          filename: "ghost.mp3",
          source_kind: "audio",
          render_mode: "audio",
          duration_seconds: 95,
          quiz_stars: 3,
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Lecture notes" }),
    );
    expect(
      screen.getByRole("heading", { name: "Add to a collection" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Thesis/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Course pack/ }),
    ).toBeNull();
  });

  it("assigns a material to a collection and refreshes", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-2",
          title: "Lecture notes",
          filename: "ghost.mp3",
          source_kind: "audio",
          render_mode: "audio",
          duration_seconds: 95,
          quiz_stars: 3,
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Lecture notes" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Thesis/ }));
    await waitFor(() =>
      expect(mocks.addMaterial).toHaveBeenCalledWith("col-1", "mat-2", true),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Add to a collection" }),
      ).toBeNull(),
    );
  });

  it("keeps the assign dialog open and shows the error when assignment fails", async () => {
    mocks.addMaterial.mockRejectedValue(new Error("locked"));
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-2",
          title: "Lecture notes",
          filename: "ghost.mp3",
          source_kind: "audio",
          render_mode: "audio",
          duration_seconds: 95,
          quiz_stars: 3,
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Lecture notes" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Thesis/ }));
    expect(await screen.findByText("locked")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Add to a collection" }),
    ).toBeInTheDocument();
  });

  it("creates a collection from the assign dialog and moves the material in", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-2",
          title: "Lecture notes",
          filename: "ghost.mp3",
          source_kind: "audio",
          render_mode: "audio",
          duration_seconds: 95,
          quiz_stars: 3,
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Lecture notes" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "New collection…" }));
    const dialog = screen.getByTestId("add-materials-dialog");
    expect(dialog).toHaveAttribute("data-mode", "create");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add dialog done" }),
    );
    await waitFor(() =>
      expect(mocks.addMaterial).toHaveBeenCalledWith(
        "created-ws",
        "mat-2",
        true,
      ),
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/learning/reading/created-ws"),
    );
  });

  it("opens the row menu with assign and delete branches", async () => {
    primeLibrary({
      materials: materialShelf(),
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    const row = closestLi(
      await screen.findByRole("button", { name: "Lecture notes" }),
    );
    fireEvent.click(
      within(row).getByRole("button", { name: "Material menu" }),
    );
    expect(
      within(row).getAllByRole("button", { name: "Add to a collection" }),
    ).toHaveLength(2);
    fireEvent.click(within(row).getByRole("button", { name: "Delete material" }));
    expect(
      screen.getByRole("heading", { name: "Delete material" }),
    ).toBeInTheDocument();
  });

  it("deletes a material in use and refreshes", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          collections: [
            { workspace_id: "col-1", title: "Thesis" },
            { workspace_id: "col-9", title: "Held" },
          ],
        }),
      ],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Material menu" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete material" }));
    expect(
      screen.getByText(
        "“Paper” is used by Thesis、Held. Deleting it removes it from those collections, along with its annotations.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(mocks.deleteMaterial).toHaveBeenCalledWith("mat-1", ""),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Delete material" }),
      ).toBeNull(),
    );
  });

  it("keeps the delete dialog open with the error when deletion fails", async () => {
    mocks.deleteMaterial.mockRejectedValue(new Error("nope"));
    primeLibrary({
      materials: [materialFixture()],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Material menu" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete material" }));
    expect(
      screen.getByText("“Paper” and its annotations will be deleted."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("nope")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Delete material" }),
    ).toBeInTheDocument();
  });

  it("retries a failed material from its row", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-4",
          title: "Broken scan",
          filename: "broken.pdf",
          status: "failed",
          error_detail: "The file could not be parsed.",
        }),
      ],
    });
    render(<MaterialLibraryPage />);
    expect(
      await screen.findByText("The file could not be parsed."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(mocks.retryMaterial).toHaveBeenCalledWith("mat-4", ""),
    );
  });

  it("opens the assign dialog for ?assign= and strips the parameter", async () => {
    primeLibrary({
      materials: materialShelf(),
      collections: shelfCollections(),
    });
    setUrl("?assign=mat-2", "/learning/reading/materials");
    render(<MaterialLibraryPage />);
    expect(await screen.findByRole("heading", { name: "Add to a collection" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Thesis/ })).toBeInTheDocument();
    expect(mocks.replace).toHaveBeenCalledWith(
      "/learning/reading/materials",
      { scroll: false },
    );
  });

  it("sends cross-workspace assignment to that workspace's material page", async () => {
    primeLibrary({
      materials: [
        materialFixture({
          material_id: "mat-9",
          title: "Remote paper",
          content_workspace_id: "ws-9",
          content_workspace_name: "Remote",
        }),
      ],
    });
    render(<MaterialLibraryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Remote paper" }));
    expect(mocks.push).toHaveBeenCalledWith(
      "/learning/reading/materials?assign=mat-9&dt_workspace=ws-9",
    );
    expect(
      screen.queryByRole("heading", { name: "Add to a collection" }),
    ).toBeNull();
  });

  it("opens the upload dialog for ?create=1 and drops the flag", async () => {
    primeLibrary({
      materials: [materialFixture()],
      collections: shelfCollections(),
    });
    setUrl("?create=1", "/learning/reading/materials");
    render(<MaterialLibraryPage />);
    expect(screen.getByTestId("add-materials-dialog")).toHaveAttribute(
      "data-mode",
      "upload",
    );
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith("/learning/reading", {
        scroll: false,
      }),
    );
    const calls = mocks.library.mock.calls.length;
    fireEvent.click(
      screen.getByRole("button", { name: "Add dialog done" }),
    );
    await waitFor(() =>
      expect(mocks.library.mock.calls.length).toBeGreaterThan(calls),
    );
    expect(screen.queryByTestId("add-materials-dialog")).toBeNull();
  });

  it("routes new uploads through the destination chooser", async () => {
    primeLibrary({
      materials: [materialFixture()],
      collections: shelfCollections(),
    });
    render(<MaterialLibraryPage />);
    await screen.findByRole("button", { name: "Paper" });
    fireEvent.click(screen.getByRole("button", { name: "Upload material" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByTestId("add-materials-dialog")).toHaveAttribute(
      "data-mode",
      "upload",
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("shows the error state with retry and no rows", async () => {
    primeLibrary({ failMaterials: new Error("offline") });
    render(<MaterialLibraryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("offline");
    expect(screen.queryByRole("button", { name: "Paper" })).toBeNull();
    expect(
      screen.queryByText("Everything you upload shows up here."),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocks.library).toHaveBeenCalledTimes(4));
  });
});
