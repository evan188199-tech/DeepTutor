import type {
  TimedCue,
  TimedSegment,
  VideoLearningMark,
  VideoMarkKind,
  VideoNote,
} from "./video-learning-api";

export const VIDEO_MARK_KINDS = ["key_point", "question", "review"] as const;

export const VIDEO_MARK_COLORS: Record<VideoMarkKind, string> = {
  key_point: "#b45309",
  question: "#1d4ed8",
  review: "#be123c",
};

export const VIDEO_NOTE_COLOR = "#64748b";

export type LearningEventKind = VideoMarkKind | "note";
export type LearningEventFilter = LearningEventKind | "all";

export interface LearningEvent {
  id: string;
  kind: LearningEventKind;
  start_seconds: number;
  end_seconds: number;
  quote: string;
  note: string;
  author: "user" | "assistant";
  reviewed_at?: string;
}

export function uniqueSortedIndexes(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isInteger(value) && value >= 0))].sort(
    (left, right) => left - right
  );
}

export function rangeFromCues(
  cues: TimedCue[],
  indexes: number[]
): { start_seconds: number; end_seconds: number; quote: string } | null {
  const selected = uniqueSortedIndexes(indexes)
    .map((index) => cues[index])
    .filter((cue): cue is TimedCue => Boolean(cue));
  if (!selected.length) return null;
  return {
    start_seconds: Math.min(...selected.map((cue) => cue.start)),
    end_seconds: Math.max(...selected.map((cue) => cue.end)),
    quote: selected
      .map((cue) => cue.text.trim())
      .filter(Boolean)
      .join(" "),
  };
}

export function locatorsForRange(
  segments: TimedSegment[],
  start: number,
  end: number
): { start_locator: number; end_locator: number } {
  const overlapping = segments.filter((segment) => segment.end >= start && segment.start <= end);
  if (!overlapping.length) return { start_locator: 0, end_locator: 0 };
  return {
    start_locator: overlapping[0].locator,
    end_locator: overlapping[overlapping.length - 1].locator,
  };
}

export function isPointMark(mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">): boolean {
  return mark.end_seconds <= mark.start_seconds;
}

export function markCoversTime(
  mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">,
  time: number
): boolean {
  if (isPointMark(mark)) return Math.abs(time - mark.start_seconds) <= 1;
  return time >= mark.start_seconds && time <= mark.end_seconds;
}

export function marksAtTime(marks: VideoLearningMark[], time: number): VideoLearningMark[] {
  return marks.filter((mark) => markCoversTime(mark, time));
}

export function sortMarks(marks: VideoLearningMark[]): VideoLearningMark[] {
  return [...marks].sort(
    (left, right) =>
      left.start_seconds - right.start_seconds ||
      left.end_seconds - right.end_seconds ||
      left.mark_id.localeCompare(right.mark_id)
  );
}

export function filterMarks(
  marks: VideoLearningMark[],
  kind: VideoMarkKind | "all"
): VideoLearningMark[] {
  const sorted = sortMarks(marks);
  return kind === "all" ? sorted : sorted.filter((mark) => mark.kind === kind);
}

export function learningEventsFromLearning(
  notes: VideoNote[] = [],
  marks: VideoLearningMark[] = []
): LearningEvent[] {
  return [
    ...notes.map((note) => ({
      id: note.note_id,
      kind: "note" as const,
      start_seconds: note.time_seconds,
      end_seconds: note.time_seconds,
      quote: "",
      note: note.text,
      author: "user" as const,
    })),
    ...marks.map((mark) => ({
      id: mark.mark_id,
      kind: mark.kind,
      start_seconds: mark.start_seconds,
      end_seconds: mark.end_seconds,
      quote: mark.quote,
      note: mark.note,
      author: mark.author,
      reviewed_at: mark.reviewed_at,
    })),
  ];
}

export function sortLearningEvents(events: LearningEvent[]): LearningEvent[] {
  return [...events].sort(
    (left, right) =>
      left.start_seconds - right.start_seconds ||
      left.end_seconds - right.end_seconds ||
      left.kind.localeCompare(right.kind) ||
      left.id.localeCompare(right.id)
  );
}

export function filterLearningEvents(
  events: LearningEvent[],
  filter: LearningEventFilter
): LearningEvent[] {
  const sorted = sortLearningEvents(events);
  return filter === "all" ? sorted : sorted.filter((event) => event.kind === filter);
}

export function learningEventCoversTime(
  event: Pick<LearningEvent, "start_seconds" | "end_seconds">,
  time: number
): boolean {
  if (event.end_seconds <= event.start_seconds) {
    return Math.abs(time - event.start_seconds) <= 1;
  }
  return time >= event.start_seconds && time <= event.end_seconds;
}

export function timelineStyle(
  event: Pick<LearningEvent, "start_seconds" | "end_seconds">,
  duration: number
): { left: string; width: string } {
  const total = Math.max(duration, 1);
  const left = (Math.max(0, event.start_seconds) / total) * 100;
  const span = Math.max(event.end_seconds - event.start_seconds, 0);
  const width = Math.max((span / total) * 100, 0.8);
  return { left: asPercent(left), width: asPercent(width) };
}

export function learningEventColor(event: Pick<LearningEvent, "kind">): string {
  return event.kind === "note" ? VIDEO_NOTE_COLOR : VIDEO_MARK_COLORS[event.kind];
}

function asPercent(value: number): string {
  return `${Math.round(value * 10000) / 10000}%`;
}

export function cueIndexesFromSelection(root: ParentNode | null, selection: Selection | null): number[] {
  if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return [];
  const indexes: number[] = [];
  for (let rangeIndex = 0; rangeIndex < selection.rangeCount; rangeIndex += 1) {
    const range = selection.getRangeAt(rangeIndex);
    const ancestor = range.commonAncestorContainer;
    const ancestorElement = ancestor instanceof Element ? ancestor : ancestor.parentElement;
    if (!ancestorElement || !root.contains(ancestorElement)) continue;
    const nodes = ancestorElement.querySelectorAll("[data-cue-index]");
    const candidates = [ancestorElement, ...Array.from(nodes)];
    for (const node of candidates) {
      if (!(node instanceof HTMLElement)) continue;
      if (!node.hasAttribute("data-cue-index")) continue;
      if (!range.intersectsNode(node)) continue;
      const index = Number(node.getAttribute("data-cue-index"));
      if (Number.isInteger(index)) indexes.push(index);
    }
  }
  return uniqueSortedIndexes(indexes);
}

export function formatWatchTime(value: number): string {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatMarkRange(mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">): string {
  if (isPointMark(mark)) return formatWatchTime(mark.start_seconds);
  return `${formatWatchTime(mark.start_seconds)} – ${formatWatchTime(mark.end_seconds)}`;
}
