"use client";

import {
  learningEventColor,
  learningEventCoversTime,
  timelineStyle,
  type LearningEvent,
} from "@/lib/video-learning-marks";

export function LearningTimeline({
  events,
  duration,
  currentTime,
  onSeek,
}: {
  events: LearningEvent[];
  duration: number;
  currentTime: number;
  onSeek: (seconds: number) => void;
}) {
  const total = Math.max(duration, 1);
  const playhead = Math.min(100, Math.max(0, (currentTime / total) * 100));

  return (
    <div className="border-b border-[var(--border)] px-3 py-2">
      <div
        className="relative h-7 cursor-pointer"
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
          onSeek(Math.max(0, ratio * total));
        }}
      >
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded bg-[var(--border)]" />
        {events.map((event) => {
          const style = timelineStyle(event, total);
          const active = learningEventCoversTime(event, currentTime);
          return (
            <button
              key={event.id}
              type="button"
              title={event.note || event.quote || event.kind}
              aria-label={event.kind}
              className="absolute top-1/2 h-3 -translate-y-1/2 rounded-sm"
              style={{
                left: style.left,
                width: style.width,
                backgroundColor: learningEventColor(event),
                opacity: active ? 1 : 0.72,
                boxShadow: active ? `0 0 0 2px ${learningEventColor(event)}55` : undefined,
              }}
              onClick={(clickEvent) => {
                clickEvent.stopPropagation();
                onSeek(event.start_seconds);
              }}
            />
          );
        })}
        <div
          className="pointer-events-none absolute top-0 h-full w-0.5 bg-[var(--foreground)]"
          style={{ left: `${playhead}%` }}
        />
      </div>
    </div>
  );
}
