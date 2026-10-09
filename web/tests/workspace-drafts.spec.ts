import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import {
  readWorkspaceDraft,
  saveWorkspaceDraft,
  transferWorkspaceDraft,
  type WorkspaceDraft,
} from "@/lib/workspace-drafts";

const auth = vi.hoisted(() => ({
  status: null as
    | { enabled: boolean; authenticated: boolean; user_id?: string }
    | null,
}));

vi.mock("@/lib/auth", () => ({
  fetchAuthStatus: () => Promise.resolve(auth.status),
}));

const DB_NAME = "deeptutor-workspace-drafts";

type StoredDraft = WorkspaceDraft | string | null;

interface FakeRequest<T> {
  result: T | undefined;
  error: unknown;
  onupgradeneeded: (() => void) | null;
  onsuccess: (() => void) | null;
  onerror: (() => void) | null;
}

function makeRequest<T>(): FakeRequest<T> {
  return {
    result: undefined,
    error: null,
    onupgradeneeded: null,
    onsuccess: null,
    onerror: null,
  };
}

interface FakeDbState {
  version: number;
  records: Map<string, StoredDraft>;
}

const databases = new Map<string, FakeDbState>();

function makeDatabase(state: FakeDbState) {
  return {
    close: vi.fn(),
    createObjectStore: vi.fn(),
    transaction(_name: string, _mode: IDBTransactionMode) {
      const tx = {
        oncomplete: null as (() => void) | null,
        onerror: null as (() => void) | null,
        onabort: null as (() => void) | null,
        objectStore() {
          return {
            get(key: string) {
              const request = makeRequest<StoredDraft>();
              request.result = state.records.get(key);
              return request;
            },
            put(value: StoredDraft, key: string) {
              state.records.set(key, value);
              return makeRequest<IDBValidKey>();
            },
            delete(key: string) {
              state.records.delete(key);
              return makeRequest<undefined>();
            },
          };
        },
      };
      queueMicrotask(() => tx.oncomplete?.());
      return tx;
    },
  };
}

function fakeOpen(_name: string, version: number) {
  const request = makeRequest<IDBDatabase>();
  queueMicrotask(() => {
    const existing = databases.get(DB_NAME);
    if (existing && existing.version !== version) {
      request.error = new DOMException(
        "The requested version is lower than the existing version.",
        "VersionError",
      );
      request.onerror?.();
      return;
    }
    const fresh = !existing;
    const state = existing ?? { version, records: new Map<string, StoredDraft>() };
    state.version = version;
    databases.set(DB_NAME, state);
    request.result = makeDatabase(state) as unknown as IDBDatabase;
    if (fresh) request.onupgradeneeded?.();
    request.onsuccess?.();
  });
  return request;
}

function draftStore(): FakeDbState {
  const state = databases.get(DB_NAME);
  if (!state) throw new Error("drafts database was never opened");
  return state;
}

function setWorkspace(id: string) {
  window.history.replaceState(null, "", id ? `/chat?dt_workspace=${id}` : "/chat");
}

function textDraft(text: string, filename?: string): WorkspaceDraft {
  return {
    text,
    attachments: filename ? [{ filename }] : [],
  };
}

beforeEach(() => {
  databases.clear();
  auth.status = { enabled: true, authenticated: true, user_id: "user-1" };
  vi.stubGlobal("indexedDB", { open: fakeOpen });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("saveWorkspaceDraft / readWorkspaceDraft", () => {
  it("round-trips a draft with text and attachments", async () => {
    setWorkspace("ws-alpha");
    const draft: WorkspaceDraft = {
      text: "hello draft",
      attachments: [
        { filename: "notes.pdf", base64: "AAAA", mimeType: "application/pdf" },
      ],
    };

    await saveWorkspaceDraft(draft);

    await expect(readWorkspaceDraft()).resolves.toEqual(draft);
  });

  it("keeps drafts isolated per workspace", async () => {
    setWorkspace("ws-alpha");
    await saveWorkspaceDraft(textDraft("alpha"));

    setWorkspace("ws-beta");
    await expect(readWorkspaceDraft()).resolves.toBeUndefined();
  });

  it("keeps drafts isolated per pathname", async () => {
    setWorkspace("ws-alpha");
    await saveWorkspaceDraft(textDraft("chat draft"));

    await expect(readWorkspaceDraft("ws-alpha", "/learning")).resolves.toBeUndefined();
  });

  it("keeps drafts isolated per account identity", async () => {
    setWorkspace("ws-alpha");
    await saveWorkspaceDraft(textDraft("mine"));
    auth.status = { enabled: true, authenticated: true, user_id: "user-2" };

    await expect(readWorkspaceDraft()).resolves.toBeUndefined();
  });

  it("clears the stored draft when an empty draft is saved", async () => {
    setWorkspace("ws-alpha");
    await saveWorkspaceDraft(textDraft("temporary"));

    await saveWorkspaceDraft({ text: "", attachments: [] });

    await expect(readWorkspaceDraft()).resolves.toBeUndefined();
    expect(draftStore().records.size).toBe(0);
  });

  it("resolves undefined when nothing has been saved yet", async () => {
    setWorkspace("ws-alpha");

    await expect(readWorkspaceDraft()).resolves.toBeUndefined();
  });

  it("rejects saving when the account identity is unavailable", async () => {
    setWorkspace("ws-alpha");
    auth.status = { enabled: true, authenticated: false };

    await expect(saveWorkspaceDraft(textDraft("unsaved"))).rejects.toThrow(
      "Account identity is unavailable for saving drafts.",
    );
    expect(databases.has(DB_NAME)).toBe(false);
  });

  it("rejects reading when the account identity is unavailable", async () => {
    setWorkspace("ws-alpha");
    auth.status = { enabled: true, authenticated: false };

    await expect(readWorkspaceDraft()).rejects.toThrow(
      "Account identity is unavailable for saving drafts.",
    );
  });

  it("stores under the local-admin identity when auth is disabled without a user id", async () => {
    setWorkspace("ws-alpha");
    auth.status = { enabled: false, authenticated: false };

    await saveWorkspaceDraft(textDraft("local only"));

    expect([...draftStore().records.keys()]).toEqual(["local-admin:ws-alpha:/chat"]);
  });

  it("rejects saving when the drafts database hits a version conflict", async () => {
    setWorkspace("ws-alpha");
    databases.set(DB_NAME, {
      version: 2,
      records: new Map<string, StoredDraft>(),
    });

    await expect(saveWorkspaceDraft(textDraft("blocked"))).rejects.toThrow(
      DOMException,
    );
    expect(databases.get(DB_NAME)?.records.size).toBe(0);
  });

  it("rejects reading when the drafts database hits a version conflict", async () => {
    setWorkspace("ws-alpha");
    databases.set(DB_NAME, {
      version: 2,
      records: new Map<string, StoredDraft>(),
    });

    await expect(readWorkspaceDraft()).rejects.toThrow(DOMException);
  });

  it("hands back a corrupted stored record untouched instead of throwing", async () => {
    setWorkspace("ws-alpha");
    await saveWorkspaceDraft(textDraft("soon corrupted"));
    const [key] = [...draftStore().records.keys()];
    draftStore().records.set(key, "not-a-draft-payload");

    await expect(readWorkspaceDraft()).resolves.toBe("not-a-draft-payload");
  });
});

describe("transferWorkspaceDraft", () => {
  it("does nothing when the destination is the current workspace", async () => {
    setWorkspace("ws-a");

    await transferWorkspaceDraft("ws-a");

    expect(databases.has(DB_NAME)).toBe(false);
  });

  it("merges destination text with a blank line and keeps prior attachments first", async () => {
    setWorkspace("ws-a");
    await saveWorkspaceDraft(textDraft("outgoing", "a.txt"));
    await saveWorkspaceDraft(textDraft("already there", "b.txt"), "ws-b", "/chat");

    await transferWorkspaceDraft("ws-b");

    const merged = await readWorkspaceDraft("ws-b", "/chat");
    expect(merged?.text).toBe("already there\n\noutgoing");
    expect(merged?.attachments.map((item) => item.filename)).toEqual([
      "b.txt",
      "a.txt",
    ]);
    await expect(readWorkspaceDraft("ws-a")).resolves.toBeUndefined();
    expect(draftStore().records.size).toBe(1);
  });

  it("leaves the destination untouched when the source has no draft", async () => {
    setWorkspace("ws-a");

    await transferWorkspaceDraft("ws-b");

    await expect(readWorkspaceDraft("ws-b", "/chat")).resolves.toBeUndefined();
    expect(draftStore().records.size).toBe(0);
  });

  it("transfers attachment-only drafts without inventing text", async () => {
    setWorkspace("ws-a");
    await saveWorkspaceDraft({ text: "", attachments: [{ filename: "c.txt" }] });

    await transferWorkspaceDraft("ws-b");

    const merged = await readWorkspaceDraft("ws-b", "/chat");
    expect(merged?.text).toBe("");
    expect(merged?.attachments.map((item) => item.filename)).toEqual(["c.txt"]);
  });
});
