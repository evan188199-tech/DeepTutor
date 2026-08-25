"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { listNotebooks, type NotebookSummary } from "@/lib/notebook-api";
import {
  captureTimestamp,
  claimPairingCode,
  createVideoNote,
  deleteVideoNote,
  formatPosition,
  getSessionCommand,
  listDevices,
  listRemoteSessions,
  listVideoNotes,
  revokeDevice,
  sendSessionCommand,
  updateVideoNote,
  type CapturedTimestamp,
  type RemoteNote,
  type RemoteSession,
} from "@/lib/video-learning-remote-api";

const NOTEBOOK_STORAGE_KEY = "deeptutor.video-learning.notebook-id";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForCommand(sessionId: string, commandId: string) {
  for (let i = 0; i < 20; i += 1) {
    const command = await getSessionCommand(sessionId, commandId);
    if (command.status === "acked" || command.status === "failed" || command.status === "expired") {
      return command;
    }
    await sleep(250);
  }
  throw new Error("Command timed out waiting for iPad acknowledgement");
}

function noteKey(note: RemoteNote) {
  return `${note.notebook_id}:${note.record_id}`;
}

export default function VideoLearningRemotePage() {
  const [code, setCode] = useState("");
  const [sessions, setSessions] = useState<RemoteSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [notes, setNotes] = useState<RemoteNote[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [notebookId, setNotebookId] = useState<string>("");
  const [devices, setDevices] = useState<Array<{ device_id: string; device_name: string; active: boolean }>>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingNotes, setLoadingNotes] = useState(false);

  const [composerOpen, setComposerOpen] = useState(false);
  const [composerBody, setComposerBody] = useState("");
  const [captured, setCaptured] = useState<CapturedTimestamp | null>(null);

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editingBody, setEditingBody] = useState("");

  const selected = useMemo(
    () => sessions.find((session) => session.session_id === selectedSessionId) || sessions[0] || null,
    [sessions, selectedSessionId],
  );

  useEffect(() => {
    try {
      const saved = localStorage.getItem(NOTEBOOK_STORAGE_KEY) || "";
      if (saved) setNotebookId(saved);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!notebookId) return;
    try {
      localStorage.setItem(NOTEBOOK_STORAGE_KEY, notebookId);
    } catch {
      /* ignore */
    }
  }, [notebookId]);

  const refresh = useCallback(async () => {
    const [nextSessions, nextDevices, nextNotebooks] = await Promise.all([
      listRemoteSessions(),
      listDevices(),
      listNotebooks().catch(() => [] as NotebookSummary[]),
    ]);
    setSessions(nextSessions);
    setDevices(nextDevices);
    setNotebooks(nextNotebooks.filter((item) => !item.unreadable));

    const preferredNotebook =
      nextNotebooks.find((item) => item.id === notebookId) ||
      nextNotebooks.find((item) => item.name === "Video Learning") ||
      null;
    if (preferredNotebook && preferredNotebook.id !== notebookId) {
      setNotebookId(preferredNotebook.id);
    }

    const active =
      nextSessions.find((session) => session.session_id === selectedSessionId) || nextSessions[0] || null;
    if (active) {
      setSelectedSessionId(active.session_id);
      setLoadingNotes(true);
      try {
        setNotes(await listVideoNotes(active.video_id, preferredNotebook?.id || notebookId || undefined));
      } finally {
        setLoadingNotes(false);
      }
    } else {
      setNotes([]);
    }
  }, [notebookId, selectedSessionId]);

  useEffect(() => {
    void refresh().catch((err) => setError(String(err.message || err)));
    const timer = setInterval(() => {
      void refresh().catch(() => undefined);
    }, 1000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function onClaim() {
    setBusy(true);
    setError("");
    try {
      await claimPairingCode(code.trim());
      setCode("");
      setStatus("iPad claimed");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function runCommand(payload: { type: string; position_ms?: number; delta_ms?: number }) {
    if (!selected) return;
    if (!selected.online) {
      setError("iPad session is offline");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const command = await sendSessionCommand(selected.session_id, payload);
      const result = await waitForCommand(selected.session_id, command.command_id);
      if (result.status !== "acked") {
        throw new Error(result.error || `Command ${result.status}`);
      }
      setStatus(`${payload.type} ok`);
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onMarkHighlight() {
    if (!selected) return;
    if (!selected.online) {
      setError("iPad offline — you can edit existing notes, but cannot capture a live timestamp.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await captureTimestamp(selected.session_id);
      setCaptured(next);
      setComposerBody("");
      setComposerOpen(true);
      setStatus(`Captured ${formatPosition(next.position_ms)}`);
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveCapturedNote() {
    if (!selected || !captured || !composerBody.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createVideoNote(captured.video_id || selected.video_id, {
        body: composerBody.trim(),
        position_ms: captured.position_ms,
        title: captured.title || selected.title,
        instance_origin: captured.instance_origin || selected.instance_origin,
        notebook_id: notebookId || undefined,
      });
      setComposerBody("");
      setComposerOpen(false);
      setCaptured(null);
      setStatus("Note saved to Notebook");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onJumpNote(note: RemoteNote) {
    if (!selected?.online) {
      setError("iPad offline — jump is unavailable.");
      return;
    }
    await runCommand({ type: "seek", position_ms: note.position_ms });
  }

  async function onSaveEdit(note: RemoteNote) {
    if (!editingBody.trim()) return;
    setBusy(true);
    setError("");
    try {
      await updateVideoNote(note.notebook_id, note.record_id, editingBody.trim());
      setEditingKey(null);
      setEditingBody("");
      setStatus("Note updated");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(note: RemoteNote) {
    setBusy(true);
    setError("");
    try {
      await deleteVideoNote(note.notebook_id, note.record_id);
      setStatus("Note deleted");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4 px-4 py-4 pb-28">
      <header className="sticky top-0 z-20 -mx-4 space-y-1 border-b border-[var(--border)] bg-[var(--background)]/95 px-4 py-3 backdrop-blur">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Video Learning</h1>
            <p className="text-sm text-[var(--muted-foreground)]">
              Control the iPad player and capture timestamped Notebook notes.
            </p>
          </div>
          <span
            className={`mt-1 rounded-full px-2 py-0.5 text-xs ${
              selected?.online
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
            }`}
          >
            {selected?.online ? "online" : "offline"}
          </span>
        </div>
        {selected ? (
          <div className="pt-1 text-sm">
            <div className="font-medium">{selected.title || selected.video_id}</div>
            <div className="text-[var(--muted-foreground)]">
              {formatPosition(selected.position_ms)} / {formatPosition(selected.duration_ms)} ·{" "}
              {selected.playback_state}
            </div>
          </div>
        ) : (
          <p className="pt-1 text-sm text-[var(--muted-foreground)]">No live Invidious session yet.</p>
        )}
      </header>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Pair iPad</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-base"
            inputMode="numeric"
            placeholder="6-digit code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <button
            className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
            disabled={busy || code.trim().length < 4}
            onClick={() => void onClaim()}
          >
            Claim
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Playback</h2>
        <div className="grid grid-cols-4 gap-2">
          <button
            className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
            disabled={busy || !selected?.online}
            onClick={() => void runCommand({ type: "seek", delta_ms: -10000 })}
          >
            -10s
          </button>
          <button
            className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
            disabled={busy || !selected?.online}
            onClick={() => void runCommand({ type: "pause" })}
          >
            Pause
          </button>
          <button
            className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
            disabled={busy || !selected?.online}
            onClick={() => void runCommand({ type: "play" })}
          >
            Play
          </button>
          <button
            className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
            disabled={busy || !selected?.online}
            onClick={() => void runCommand({ type: "seek", delta_ms: 10000 })}
          >
            +10s
          </button>
        </div>
        {!selected?.online && (
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">
            Offline: existing Notebook notes stay editable; live capture and remote commands are blocked.
          </p>
        )}
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">Notes</h2>
          <button
            className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
            disabled={busy || !selected?.online}
            onClick={() => void onMarkHighlight()}
          >
            Mark highlight
          </button>
        </div>

        <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
          Notebook
          <select
            className="mt-1 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)]"
            value={notebookId}
            onChange={(event) => setNotebookId(event.target.value)}
          >
            <option value="">Video Learning (auto)</option>
            {notebooks.map((notebook) => (
              <option key={notebook.id} value={notebook.id}>
                {notebook.name}
              </option>
            ))}
          </select>
        </label>

        {composerOpen && captured && (
          <div className="mb-3 space-y-2 rounded-md border border-[var(--border)] bg-[var(--muted)]/20 p-3">
            <div className="text-xs text-[var(--muted-foreground)]">
              Writing at {formatPosition(captured.position_ms)}
            </div>
            <textarea
              className="min-h-28 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-base"
              placeholder="Write the highlight note…"
              value={composerBody}
              onChange={(event) => setComposerBody(event.target.value)}
              autoFocus
            />
            <div className="flex gap-2">
              <button
                className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
                disabled={busy || !composerBody.trim()}
                onClick={() => void onSaveCapturedNote()}
              >
                Save note
              </button>
              <button
                className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                disabled={busy}
                onClick={() => {
                  setComposerOpen(false);
                  setCaptured(null);
                  setComposerBody("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {loadingNotes && notes.length === 0 ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading notes…</p>
        ) : (
          <ul className="space-y-2">
            {notes.map((note) => {
              const key = noteKey(note);
              const editing = editingKey === key;
              return (
                <li key={key} className="rounded-md border border-[var(--border)] p-3">
                  <button
                    className="text-left text-xs font-medium text-sky-600 underline dark:text-sky-300"
                    disabled={busy || !selected?.online}
                    onClick={() => void onJumpNote(note)}
                  >
                    {formatPosition(note.position_ms)}
                  </button>
                  {editing ? (
                    <div className="mt-2 space-y-2">
                      <textarea
                        className="min-h-24 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
                        value={editingBody}
                        onChange={(event) => setEditingBody(event.target.value)}
                      />
                      <div className="flex gap-2">
                        <button
                          className="rounded-md bg-[var(--foreground)] px-3 py-1.5 text-xs text-[var(--background)] disabled:opacity-50"
                          disabled={busy || !editingBody.trim()}
                          onClick={() => void onSaveEdit(note)}
                        >
                          Save
                        </button>
                        <button
                          className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs"
                          disabled={busy}
                          onClick={() => {
                            setEditingKey(null);
                            setEditingBody("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-1 whitespace-pre-wrap text-sm">{note.body}</div>
                  )}
                  {!editing && (
                    <div className="mt-2 flex gap-3 text-xs text-[var(--muted-foreground)]">
                      <button
                        className="underline"
                        disabled={busy}
                        onClick={() => {
                          setEditingKey(key);
                          setEditingBody(note.body);
                        }}
                      >
                        Edit
                      </button>
                      <button className="underline" disabled={busy} onClick={() => void onDelete(note)}>
                        Delete
                      </button>
                      <a className="underline" href={`/notebook?notebook=${encodeURIComponent(note.notebook_id)}`}>
                        Open Notebook
                      </a>
                    </div>
                  )}
                </li>
              );
            })}
            {notes.length === 0 && (
              <li className="text-sm text-[var(--muted-foreground)]">
                No notes for this video yet. Tap Mark highlight while the iPad is online.
              </li>
            )}
          </ul>
        )}
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Devices</h2>
        <ul className="space-y-2">
          {devices.map((device) => (
            <li key={device.device_id} className="flex items-center justify-between gap-2 text-sm">
              <span>
                {device.device_name || device.device_id} {device.active ? "" : "(revoked)"}
              </span>
              {device.active && (
                <button
                  className="text-xs underline"
                  onClick={() =>
                    void revokeDevice(device.device_id)
                      .then(refresh)
                      .catch((err) => setError(String(err.message || err)))
                  }
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
          {devices.length === 0 && (
            <li className="text-sm text-[var(--muted-foreground)]">No paired devices.</li>
          )}
        </ul>
      </section>

      {(status || error) && (
        <div className="text-sm">
          {status && <p className="text-[var(--muted-foreground)]">{status}</p>}
          {error && <p className="text-red-500">{error}</p>}
        </div>
      )}
    </div>
  );
}
