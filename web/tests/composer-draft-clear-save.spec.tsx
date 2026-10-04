import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * Draft persistence is IndexedDB-backed. The send path clears the stored
 * draft after handing the text to the chat; when that clear fails the old
 * draft survives and the composer restores already-sent text on the next
 * mount. These tests pin the two halves of the contract: a failed clear is
 * visible to the learner, a successful one stays silent.
 */
const drafts = vi.hoisted(() => ({
  save: vi.fn(async () => {}),
  read: vi.fn(async () => undefined),
}));

vi.mock("@/lib/workspace-drafts", () => ({
  saveWorkspaceDraft: drafts.save,
  readWorkspaceDraft: drafts.read,
}));

const { default: ChatComposer } = await import(
  "@/components/chat/home/ChatComposer"
);
const { CHAT_CAPABILITIES } = await import(
  "@/features/capabilities/presentation"
);

function renderComposer() {
  return render(
    <ChatComposer
      composerRef={{ current: null }}
      capMenuRef={{ current: null }}
      capBtnRef={{ current: null }}
      spaceMenuRef={{ current: null }}
      spaceBtnRef={{ current: null }}
      dragCounter={{ current: 0 }}
      dragging={false}
      capMenuOpen={false}
      spaceMenuOpen={false}
      hasMessages={false}
      attachments={[]}
      attachmentError={null}
      activeCap={CHAT_CAPABILITIES[0]}
      knowledgeBases={[]}
      llmOptions={[]}
      activeLLMDefault={null}
      llmSelection={null}
      llmOptionsLoading={false}
      llmOptionsError={false}
      selectedNotebookRecords={[]}
      selectedBookReferences={[]}
      selectedHistorySessions={[]}
      selectedAgentSessions={[]}
      selectedQuestionEntries={[]}
      notebookReferenceGroups={[]}
      selectedPersona={null}
      selectedMemoryFiles={[]}
      selectedKnowledgeBases={[]}
      isStreaming={false}
      isVisualizeMode={false}
      capabilityNeedsConfig={false}
      capabilityConfigConfirmed={false}
      onRequestConfigConfirm={() => undefined}
      capabilities={[]}
      onSetCapMenuOpen={() => undefined}
      onSetSpaceMenuOpen={() => undefined}
      onToggleKB={() => undefined}
      onSelectLLM={() => undefined}
      onSelectNotebookPicker={() => undefined}
      onSelectBookPicker={() => undefined}
      onSelectHistoryPicker={() => undefined}
      onSelectAgentsPicker={() => undefined}
      onSelectQuestionBankPicker={() => undefined}
      onSelectPersonaPicker={() => undefined}
      onSelectMemoryPicker={() => undefined}
      onClearPersona={() => undefined}
      onToggleMemoryFile={() => undefined}
      onSend={() => undefined}
      onRemoveAttachment={() => undefined}
      onRemoveHistory={() => undefined}
      onRemoveAgent={() => undefined}
      onRemoveBookReference={() => undefined}
      onRemoveNotebook={() => undefined}
      onRemoveQuestion={() => undefined}
      onDragEnter={() => undefined}
      onDragLeave={() => undefined}
      onDragOver={() => undefined}
      onDrop={() => undefined}
      onPaste={() => undefined}
      onAddFiles={() => undefined}
      onSelectCapability={() => undefined}
      onCancelStreaming={() => undefined}
    />,
  );
}

async function sendText(text: string) {
  const user = userEvent.setup();
  renderComposer();
  await user.type(screen.getByRole("textbox"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(drafts.save).toHaveBeenCalledTimes(1));
}

describe("clearing the stored draft after send", () => {
  beforeEach(() => {
    drafts.save.mockClear();
    drafts.read.mockClear();
  });

  it("shows a hint when the clear fails, so the surviving draft is no longer invisible", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    drafts.save.mockRejectedValueOnce(new Error("indexedDB unavailable"));

    await sendText("hello");

    expect(await screen.findByRole("status")).toBeTruthy();
    await waitFor(() => expect(warn).toHaveBeenCalled());
  });

  it("stays silent when the clear succeeds", async () => {
    await sendText("hello");

    expect(drafts.save).toHaveBeenCalledWith({
      text: "",
      attachments: [],
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("dismisses the clear-failure hint once the user starts typing a new draft", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    drafts.save.mockRejectedValueOnce(new Error("indexedDB unavailable"));

    await sendText("hello");
    expect(await screen.findByRole("status")).toBeTruthy();

    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "new draft");

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("neither clears nor warns when the draft restore itself failed", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    drafts.read.mockRejectedValueOnce(new Error("indexedDB unavailable"));

    const user = userEvent.setup();
    renderComposer();
    // The restore-failure warning is the marker that restoreFailedRef is set;
    // only then is the send path's clear-skipping behavior in force.
    await waitFor(() =>
      expect(warn).toHaveBeenCalledWith(
        "[ChatComposer] workspace draft restore failed; keeping the stored draft untouched",
        expect.anything(),
      ),
    );

    await user.type(screen.getByRole("textbox"), "typed after failed restore");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(drafts.save).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
    expect(warn).not.toHaveBeenCalledWith(
      "Failed to clear the workspace draft after send:",
      expect.anything(),
    );
  });
});
