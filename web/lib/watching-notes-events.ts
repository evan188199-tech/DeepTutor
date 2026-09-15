export const WATCHING_OPEN_NOTES_EVENT = "dt:watching-open-notes";
export const WATCHING_NOTES_CHANGED_EVENT = "dt:watching-notes-changed";
export const WATCHING_SEEK_EVENT = "dt:watching-seek";

function emit(name: string, detail: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function openWatchingNotesInInspector(materialId: string) {
  emit(WATCHING_OPEN_NOTES_EVENT, { materialId });
}

export function notifyWatchingNotesChanged(materialId: string) {
  emit(WATCHING_NOTES_CHANGED_EVENT, { materialId });
}

export function seekWatchingVideo(seconds: number) {
  emit(WATCHING_SEEK_EVENT, { seconds });
}
