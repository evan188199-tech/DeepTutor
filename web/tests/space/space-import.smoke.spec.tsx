/**
 * Smoke regression coverage for the Space import surfaces:
 *   - components/space/ImportWizard.tsx      (Claude Code / Codex / ChatGPT chat import)
 *   - components/space/EduHubImportModal.tsx (EduHub skill import)
 *
 * Both files were on the zero-coverage list of the web test-gap scan
 * (myfork branch scan/web-test-gaps-20261007, summary.json). This spec
 * mocks every network / File System Access boundary and must never require
 * product-code changes.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImportWizard from "@/components/space/ImportWizard";
import EduHubImportModal from "@/components/space/EduHubImportModal";
import {
  ImportScanError,
  type ImportSource,
  type NormalizedSession,
  type ScanResult,
  type SessionRef,
} from "@/lib/chat-import";

type ProgressCb = (done: number, total: number) => void;

const fixture = vi.hoisted(() => ({
  fsSupported: true,
  pickAndScan: vi.fn<() => Promise<ScanResult>>(),
  parseSessions:
    vi.fn<
      (
        source: ImportSource,
        refs: SessionRef[],
        onProgress?: ProgressCb,
      ) => Promise<NormalizedSession[]>
    >(),
  parseChatGptExportFile:
    vi.fn<
      (file: File, onProgress?: ProgressCb) => Promise<NormalizedSession[]>
    >(),
  importChatHistory: vi.fn(),
  importChatHistoryInBatches: vi.fn(),
  newAgentId: vi.fn<() => string>(() => "agent-fixed-id"),
  saveAgent: vi.fn(),
  fetchHubCatalog: vi.fn(),
  fetchHubSkillDetail: vi.fn(),
  installSkillFromHub: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "en" } }),
}));
function translate(key: string, opts?: Record<string, unknown>) {
  if (!opts) return key;
  return key.replace(/\{\{(\w+)\}\}/g, (_, k: string) => String(opts[k] ?? ""));
}

vi.mock("@/lib/chat-import", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/chat-import")>()),
  isFileSystemAccessSupported: () => fixture.fsSupported,
  pickAndScan: () => fixture.pickAndScan(),
  parseSessions: (
    ...args: Parameters<typeof import("@/lib/chat-import").parseSessions>
  ) => fixture.parseSessions(...args),
  parseChatGptExportFile: (
    ...args: Parameters<
      typeof import("@/lib/chat-import").parseChatGptExportFile
    >
  ) => fixture.parseChatGptExportFile(...args),
}));

vi.mock("@/lib/imports-api", () => ({
  importChatHistory: (...args: unknown[]) =>
    fixture.importChatHistory(...args),
  importChatHistoryInBatches: (...args: unknown[]) =>
    fixture.importChatHistoryInBatches(...args),
}));

vi.mock("@/lib/chat-import/agent-store", () => ({
  newAgentId: () => fixture.newAgentId(),
  saveAgent: (...args: unknown[]) => fixture.saveAgent(...args),
}));

vi.mock("@/lib/skills-api", () => ({
  fetchHubCatalog: (...args: unknown[]) => fixture.fetchHubCatalog(...args),
  fetchHubSkillDetail: (...args: unknown[]) =>
    fixture.fetchHubSkillDetail(...args),
  installSkillFromHub: (...args: unknown[]) =>
    fixture.installSkillFromHub(...args),
}));

// EduHubImportModal lazy-loads the markdown renderer via next/dynamic.
// Render the markdown body through a synchronous stub: DetailView already
// strips frontmatter before handing content over, so the stub still exercises
// the real stripping logic without suspense plumbing.
vi.mock("next/dynamic", () => ({
  default: () => function MarkdownStub(props: { content: string }) {
    return <div data-testid="skill-markdown">{props.content}</div>;
  },
}));

/* ── shared fixtures ──────────────────────────────────────────────────── */

function makeRef(externalId: string, cwd: string): SessionRef {
  return {
    externalId,
    provisionalTitle: `Conversation ${externalId}`,
    cwd,
    date: "2026-10-08",
    lastModified: 1_760_000_000_000,
    sizeBytes: 128,
    handle: { kind: "file" } as unknown as SessionRef["handle"],
  };
}

function makeScanResult(): ScanResult {
  return {
    source: "claude_code",
    handle: { name: ".claude" } as unknown as ScanResult["handle"],
    projects: [
      {
        cwd: "/home/dev/alpha",
        label: "alpha",
        sessions: [makeRef("s1", "/home/dev/alpha"), makeRef("s2", "/home/dev/alpha")],
      },
      {
        cwd: "/home/dev/beta",
        label: "beta",
        sessions: [makeRef("s3", "/home/dev/beta")],
      },
    ],
  };
}

function makeNormalized(externalId: string): NormalizedSession {
  return {
    external_id: externalId,
    title: `Normalized ${externalId}`,
    source_cwd: "/home/dev/alpha",
    created_at: 1_760_000_000,
    updated_at: 1_760_000_000,
    messages: [{ role: "user", content: "hello" }],
  };
}

const hubListing = {
  slug: "algebra-coach",
  name: "Algebra Coach",
  summary: "Step-by-step algebra help",
  version: "1.2.3",
  downloads: 120,
  stars: 34,
  owner: "alice",
  ownerUrl: "https://hub.example/@alice",
};
const hubListing2 = {
  slug: "vocab-drills",
  name: "Vocab Drills",
  summary: "Daily vocabulary practice",
  version: "0.4.0",
  downloads: 50,
  stars: 9,
  owner: "bob",
  ownerUrl: "",
};
const hubCatalog = {
  hub: "eduhub",
  webUrl: "https://hub.example",
  skills: [hubListing, hubListing2],
};
const hubDetail = {
  ...hubListing,
  content: "---\nname: algebra-coach\n---\n# Playbook body",
  tags: ["math", "coach"],
  webUrl: "https://hub.example/skills/algebra-coach",
};

/* ── ImportWizard ─────────────────────────────────────────────────────── */

function renderWizard() {
  const onClose = vi.fn();
  const onImported = vi.fn();
  render(<ImportWizard onClose={onClose} onImported={onImported} />);
  return { onClose, onImported };
}

async function openSelectPhase() {
  fireEvent.click(screen.getByRole("button", { name: "Select folder" }));
  await screen.findByText("Agent name");
}

describe("ImportWizard", () => {
  beforeEach(() => {
    fixture.fsSupported = true;
    fixture.pickAndScan.mockReset();
    fixture.parseSessions.mockReset();
    fixture.parseChatGptExportFile.mockReset();
    fixture.importChatHistory.mockReset();
    fixture.importChatHistoryInBatches.mockReset();
    fixture.saveAgent.mockReset();
    fixture.newAgentId.mockClear();
  });

  it("renders the intro step, disables folder pick without File System Access, and closes", () => {
    fixture.fsSupported = false;
    const { onClose } = renderWizard();
    expect(
      screen.getByRole("button", { name: "Select folder" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "Your browser doesn't support folder access, but you can still import a ChatGPT JSON export.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("steps from folder scan to the select phase with every unit pre-selected", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    const { onClose } = renderWizard();
    await openSelectPhase();
    expect(
      screen.getByText("alpha"),
    ).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(
      screen.getByText("2 projects · 3 conversations"),
    ).toBeInTheDocument();
    expect(screen.getByText("· 3 selected")).toBeInTheDocument();
    const toggles = screen.getAllByRole("button", { name: "Select" });
    expect(toggles).toHaveLength(2);
    expect(toggles[0]).toHaveAttribute("aria-pressed", "true");
    expect(toggles[1]).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    ).toBeInTheDocument();
    expect(
      (screen.getByLabelText("Agent name") as HTMLInputElement).value,
    ).toBe("Claude Code");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps the import button in sync as units are toggled, cleared and re-selected", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    renderWizard();
    await openSelectPhase();
    const toggles = screen.getAllByRole("button", { name: "Select" });
    fireEvent.click(toggles[1]);
    expect(
      screen.getByRole("button", { name: "Import 2 conversations" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    const importButton = screen.getByRole("button", { name: "Import" });
    expect(importButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    ).toBeEnabled();
  });

  it("shows the empty-scan state when the folder has no readable conversations", async () => {
    fixture.pickAndScan.mockResolvedValue({
      ...makeScanResult(),
      projects: [],
    });
    renderWizard();
    fireEvent.click(screen.getByRole("button", { name: "Select folder" }));
    await screen.findByText("No conversations found");
    expect(
      screen.queryByLabelText("Agent name"),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("maps an unrecognized folder to the error view and recovers via Try again", async () => {
    fixture.pickAndScan.mockRejectedValue(
      new ImportScanError("not_recognized"),
    );
    renderWizard();
    fireEvent.click(screen.getByRole("button", { name: "Select folder" }));
    await screen.findByText("Couldn't import");
    expect(
      screen.getByText(
        "This folder doesn't look like a .claude or .codex home. Please select the right folder.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      screen.getByRole("button", { name: "Select folder" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Couldn't import")).toBeNull();
  });

  it("returns to the intro step without an error when the picker is aborted", async () => {
    fixture.pickAndScan.mockRejectedValue(new ImportScanError("aborted"));
    renderWizard();
    fireEvent.click(screen.getByRole("button", { name: "Select folder" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select folder" }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Couldn't import")).toBeNull();
  });

  it("imports the selected projects, registers the agent, and closes via Done", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    fixture.parseSessions.mockResolvedValue([
      makeNormalized("s1"),
      makeNormalized("s2"),
    ]);
    fixture.importChatHistory.mockResolvedValue({ imported: 2, skipped: 1 });
    const { onImported } = renderWizard();
    await openSelectPhase();
    fireEvent.change(screen.getByLabelText("Agent name"), {
      target: { value: "My Agent" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    );
    await screen.findByText("Imported 2 conversations");
    expect(
      screen.getByText("1 skipped (already imported or empty)."),
    ).toBeInTheDocument();
    expect(fixture.parseSessions).toHaveBeenCalledTimes(1);
    const [source, refs] = fixture.parseSessions.mock.calls[0];
    expect(source).toBe("claude_code");
    expect(refs).toHaveLength(3);
    expect(fixture.importChatHistory).toHaveBeenCalledWith(
      "claude_code",
      [makeNormalized("s1"), makeNormalized("s2")],
      { id: "agent-fixed-id", name: "My Agent" },
    );
    expect(fixture.saveAgent).toHaveBeenCalledTimes(1);
    expect(fixture.saveAgent.mock.calls[0][0]).toMatchObject({
      id: "agent-fixed-id",
      name: "My Agent",
      source: "claude_code",
      folderName: ".claude",
      scope: {
        kind: "projects",
        cwds: ["/home/dev/alpha", "/home/dev/beta"],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("still finishes the import when the agent registry write fails", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    fixture.parseSessions.mockResolvedValue([makeNormalized("s1")]);
    fixture.importChatHistory.mockResolvedValue({ imported: 1, skipped: 0 });
    fixture.saveAgent.mockRejectedValue(new Error("quota exceeded"));
    const { onImported } = renderWizard();
    await openSelectPhase();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    );
    await screen.findByText("Imported 1 conversations");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("locks the modal and blocks closing while an import is in flight, then recovers", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    fixture.parseSessions.mockResolvedValue([makeNormalized("s1")]);
    let resolveImport!: (v: { imported: number; skipped: number }) => void;
    fixture.importChatHistory.mockImplementation(
      () =>
        new Promise(resolve => {
          resolveImport = resolve;
        }),
    );
    const { onClose } = renderWizard();
    await openSelectPhase();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    );
    await screen.findByText("Working…");
    expect(
      screen.queryByRole("button", { name: "Close" }),
    ).toBeNull();
    fireEvent.mouseDown(screen.getByRole("dialog").parentElement!);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    resolveImport({ imported: 2, skipped: 0 });
    await screen.findByText("Imported 2 conversations");
  });

  it("surfaces a generic error when the import submission fails", async () => {
    fixture.pickAndScan.mockResolvedValue(makeScanResult());
    fixture.parseSessions.mockResolvedValue([makeNormalized("s1")]);
    fixture.importChatHistory.mockRejectedValue(new Error("boom"));
    renderWizard();
    await openSelectPhase();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 3 conversations" }),
    );
    await screen.findByText("Couldn't import");
    expect(
      screen.getByText("Something went wrong while importing. Please try again."),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("imports a ChatGPT export end-to-end through the hidden file input", async () => {
    const normalized = [makeNormalized("c1"), makeNormalized("c2")];
    fixture.parseChatGptExportFile.mockResolvedValue(normalized);
    fixture.importChatHistoryInBatches.mockResolvedValue({
      imported: 5,
      skipped: 0,
    });
    const clickSpy = vi
      .spyOn(HTMLInputElement.prototype, "click")
      .mockImplementation(() => {});
    renderWizard();
    fireEvent.click(
      screen.getByRole("button", { name: "Select ChatGPT export" }),
    );
    expect(clickSpy).toHaveBeenCalledTimes(1);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File(["[]"], "conversations.json", { type: "application/json" }),
        ],
      },
    });
    await screen.findByText("Imported 5 conversations");
    expect(
      screen.getByText(
        "They're ready in your space — open one to keep chatting.",
      ),
    ).toBeInTheDocument();
    expect(fixture.importChatHistoryInBatches).toHaveBeenCalledTimes(1);
    const [source, payload, options] =
      fixture.importChatHistoryInBatches.mock.calls[0];
    expect(source).toBe("chatgpt");
    expect(payload).toEqual(normalized);
    expect(typeof options.onProgress).toBe("function");
    expect(input.value).toBe("");
  });

  it("rejects an unreadable ChatGPT export with the invalid-export message", async () => {
    fixture.parseChatGptExportFile.mockRejectedValue(
      new (await import("@/lib/chat-import")).ImportScanError("invalid_export"),
    );
    renderWizard();
    fireEvent.click(
      screen.getByRole("button", { name: "Select ChatGPT export" }),
    );
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File(["not json"], "conversations.json", {
            type: "application/json",
          }),
        ],
      },
    });
    await screen.findByText("Couldn't import");
    expect(
      screen.getByText(
        "This file doesn't contain readable ChatGPT conversations. Select the conversations.json file from an official ChatGPT data export.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      screen.getByRole("button", { name: "Select ChatGPT export" }),
    ).toBeInTheDocument();
  });
});

/* ── EduHubImportModal ────────────────────────────────────────────────── */

function renderHub(props: { installedNames?: Set<string> } = {}) {
  const onClose = vi.fn();
  const onInstalled = vi.fn();
  render(
    <EduHubImportModal
      onClose={onClose}
      onInstalled={onInstalled}
      installedNames={props.installedNames}
    />,
  );
  return { onClose, onInstalled };
}

async function openHub(props: { installedNames?: Set<string> } = {}) {
  const handle = renderHub(props);
  await screen.findByText("Algebra Coach");
  return handle;
}

describe("EduHubImportModal", () => {
  beforeEach(() => {
    fixture.fetchHubCatalog.mockReset();
    fixture.fetchHubSkillDetail.mockReset();
    fixture.installSkillFromHub.mockReset();
    fixture.fetchHubCatalog.mockResolvedValue(hubCatalog);
  });

  it("loads the catalog and renders listings with counts and hub links", async () => {
    await openHub();
    expect(fixture.fetchHubCatalog).toHaveBeenCalledWith({ limit: 100 });
    expect(screen.getByText("Vocab Drills")).toBeInTheDocument();
    expect(screen.getByText("Step-by-step algebra help")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open EduHub" })).toHaveAttribute(
      "href",
      "https://hub.example/skills",
    );
  });

  it("shows an error panel with retry when the catalog cannot be reached", async () => {
    fixture.fetchHubCatalog
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(hubCatalog);
    const { onClose } = renderHub();
    await screen.findByText("Couldn't reach EduHub.");
    expect(screen.getByText("network down")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Algebra Coach");
    expect(fixture.fetchHubCatalog).toHaveBeenCalledTimes(2);
  });

  it("filters skills by search query and shows the no-match state", async () => {
    await openHub();
    const search = screen.getByPlaceholderText("Search skills…");
    fireEvent.change(search, { target: { value: "algebra" } });
    expect(screen.getByText("Algebra Coach")).toBeInTheDocument();
    expect(screen.queryByText("Vocab Drills")).toBeNull();
    fireEvent.change(search, { target: { value: "zzz-no-match" } });
    await screen.findByText("No skills match your search.");
    fireEvent.change(search, { target: { value: "" } });
    await screen.findByText("Vocab Drills");
  });

  it("marks pre-installed skills and switches their button to re-download", async () => {
    await openHub({ installedNames: new Set(["vocab-drills"]) });
    expect(screen.getAllByText("Installed")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Re-download" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download" }),
    ).toBeInTheDocument();
  });

  it("opens the detail view, strips frontmatter, and goes back", async () => {
    fixture.fetchHubSkillDetail.mockResolvedValue(hubDetail);
    await openHub();
    fireEvent.click(
      screen.getByRole("button", { name: "View details: Algebra Coach" }),
    );
    expect(fixture.fetchHubSkillDetail).toHaveBeenCalledWith("algebra-coach");
    await screen.findByText("v1.2.3");
    expect(screen.getByText("math")).toBeInTheDocument();
    expect(screen.getByText("coach")).toBeInTheDocument();
    await screen.findByTestId("skill-markdown");
    expect(screen.getByTestId("skill-markdown").textContent).toBe(
      "# Playbook body",
    );
    expect(
      screen.getByRole("link", { name: "View on EduHub" }),
    ).toHaveAttribute("href", "https://hub.example/skills/algebra-coach");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await screen.findByPlaceholderText("Search skills…");
  });

  it("shows the detail error message when the skill detail request fails", async () => {
    fixture.fetchHubSkillDetail.mockRejectedValue(
      new Error("detail unavailable"),
    );
    await openHub();
    fireEvent.click(
      screen.getByRole("button", { name: "View details: Algebra Coach" }),
    );
    await screen.findByText("detail unavailable");
    expect(screen.getByText("Algebra Coach")).toBeInTheDocument();
  });

  it("installs a skill through the eduhub ref and flips it to installed", async () => {
    fixture.installSkillFromHub.mockResolvedValue({
      name: "Algebra Coach",
      version: "1.2.3",
      verdict: { status: "verified", detail: "" },
    });
    const { onInstalled } = await openHub();
    fireEvent.click(screen.getAllByRole("button", { name: "Download" })[0]);
    await screen.findByText("Installed");
    expect(fixture.installSkillFromHub).toHaveBeenCalledWith(
      "eduhub:algebra-coach",
      { force: false },
    );
    expect(onInstalled).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Re-download" }),
    ).toBeInTheDocument();
  });

  it("surfaces install failures on the card and offers Retry", async () => {
    fixture.installSkillFromHub.mockRejectedValue(new Error("quota exceeded"));
    const { onInstalled } = await openHub();
    fireEvent.click(screen.getAllByRole("button", { name: "Download" })[0]);
    await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByText("quota exceeded")).toBeInTheDocument();
    expect(onInstalled).not.toHaveBeenCalled();
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("closes via the X button, overlay click, and Escape — but not on inner clicks", async () => {
    const { onClose } = await openHub();
    fireEvent.click(screen.getByPlaceholderText("Search skills…"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("uses the first Escape to leave the detail view and the second to close", async () => {
    fixture.fetchHubSkillDetail.mockResolvedValue(hubDetail);
    const { onClose } = await openHub();
    fireEvent.click(
      screen.getByRole("button", { name: "View details: Algebra Coach" }),
    );
    await screen.findByText("v1.2.3");
    fireEvent.keyDown(window, { key: "Escape" });
    await screen.findByPlaceholderText("Search skills…");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
