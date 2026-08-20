"use client";

import { useCallback, useMemo } from "react";
import VisualizationViewer from "@/components/visualize/VisualizationViewer";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";
import type { IframeLearningOutcome } from "@/lib/iframe-html";
import type { VisualizeResult } from "@/lib/visualize-types";

export interface InteractiveBlockProps {
  block: Block;
  onLearningOutcome?: (block: Block, outcome: IframeLearningOutcome) => void;
}

export default function InteractiveBlock({
  block,
  onLearningOutcome,
}: InteractiveBlockProps) {
  const { t } = useTranslation();
  const code =
    (block.payload?.code as
      | { language?: string; content?: string }
      | undefined) || {};
  const content = String(code.content || "");
  const description = block.payload?.description
    ? String(block.payload.description)
    : "";
  const chartType = block.payload?.chart_type
    ? String(block.payload.chart_type)
    : "interactive";
  const rawLearningObjectives = block.payload?.learning_objectives;
  const learningObjectiveIds = useMemo(
    () =>
      Array.isArray(rawLearningObjectives)
        ? rawLearningObjectives
            .map((ref) =>
              ref && typeof ref === "object" && "id" in ref
                ? String((ref as { id?: unknown }).id || "")
                : "",
            )
            .filter(Boolean)
        : [],
    [rawLearningObjectives],
  );
  const handleLearningOutcome = useCallback(
    (outcome: IframeLearningOutcome) => onLearningOutcome?.(block, outcome),
    [block, onLearningOutcome],
  );

  if (!content.trim()) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-4 text-xs italic text-[var(--muted-foreground)]">
        {t("(Interactive payload is empty)")}
      </div>
    );
  }

  const result: VisualizeResult = {
    response: description,
    render_type: "html",
    code: { language: "html", content },
    analysis: {
      render_type: "html",
      description,
      data_description: "",
      chart_type: chartType,
      visual_elements: [],
      rationale: "",
    },
    review: {
      optimized_code: "",
      changed: false,
      review_notes: "",
    },
  };

  return (
    <figure className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-sm">
      <VisualizationViewer
        result={result}
        learningObjectiveIds={learningObjectiveIds}
        onLearningOutcome={onLearningOutcome ? handleLearningOutcome : undefined}
      />
      {description && (
        <figcaption className="mt-3 text-xs leading-snug text-[var(--muted-foreground)]">
          <MarkdownRenderer content={description} variant="default" />
        </figcaption>
      )}
    </figure>
  );
}
