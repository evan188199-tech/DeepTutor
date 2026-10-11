"use client";

import { useMemo, useRef, useState } from "react";
import { Brain, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import { useOutsideClick } from "@/hooks/use-outside-click";
import Tooltip from "@/shared/ui/Tooltip";
import ToolbarLabel from "./ToolbarLabel";
import type { LLMSelection } from "@/features/chat/model/protocol";
import {
  llmSelectionWithReasoningEffort,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import {
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
} from "@/lib/reasoning-effort";

/**
 * Per-conversation reasoning-effort override (#641).
 *
 * Sits next to the model selector and shows only the levels the resolved
 * model/provider supports; models without a knob render nothing and their
 * turns keep sending a bare profile/model selection. "" is "Auto": no
 * override is attached and the profile/model default applies unchanged.
 */
export default function ReasoningEffortSelector({
  options,
  activeDefault,
  value,
  placement = "top",
  onChange,
}: {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  value: LLMSelection | null;
  placement?: "top" | "bottom";
  onChange: (selection: LLMSelection | null) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const {
    expanded,
    linger,
    triggerProps: lingerProps,
  } = useLingerExpand(open, 1200);

  const selectedSelection = value ?? activeDefault;
  const selectedOption = useMemo(
    () =>
      options.find((option) => sameLLMSelection(option, selectedSelection)) ??
      null,
    [options, selectedSelection],
  );
  const effort = value?.reasoning_effort ?? "";
  const effortOptions = useMemo(
    () =>
      selectedOption
        ? selectedOption.supported_reasoning_efforts !== undefined
          ? reasoningEffortOptionsFromSupportedLevels(
              selectedOption.supported_reasoning_efforts,
            )
          : reasoningEffortOptions(
              selectedOption.provider,
              selectedOption.model,
              effort,
              selectedOption.declared_reasoning ?? null,
            )
        : [],
    [selectedOption, effort],
  );

  useOutsideClick(rootRef, open, () => {
    setOpen(false);
    linger();
  });

  // Unsupported model/provider: hide instead of disabling — an unusable
  // control next to the send button reads as a broken state (#641).
  if (effortOptions.length === 0) return null;

  const triggerLabel = effort
    ? (effortOptions.find((option) => option.value === effort)?.label ?? effort)
    : t("Auto");
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  return (
    <div ref={rootRef} className="relative">
      {/* Shares the composer selectors' spring and hover delay. */}
      <Tooltip label={t("Reasoning")} suppressed={open} side="top">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-label={t("Reasoning")}
          aria-expanded={open}
          {...lingerProps}
          className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
            open
              ? "bg-[var(--muted)] text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          }`}
        >
          <Brain size={16} strokeWidth={1.7} />
          <ToolbarLabel expanded={expanded}>
            <span className="min-w-0">{triggerLabel}</span>
            <ChevronDown
              size={13}
              className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
            />
          </ToolbarLabel>
        </button>
      </Tooltip>

      {open && (
        <div
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(220px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="max-h-[280px] overflow-y-auto py-1">
            {effortOptions.map((option) => {
              const selected = option.value === effort;
              return (
                <button
                  key={option.value || "auto"}
                  type="button"
                  onClick={() => {
                    onChange(
                      llmSelectionWithReasoningEffort(
                        selectedSelection,
                        option.value,
                      ),
                    );
                    setOpen(false);
                    linger();
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                    selected
                      ? "bg-[var(--primary)]/[0.06]"
                      : "hover:bg-[var(--muted)]/45"
                  }`}
                >
                  <Brain
                    size={14}
                    strokeWidth={1.7}
                    className={`shrink-0 ${
                      selected
                        ? "text-[var(--primary)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {option.label}
                  </span>
                  {selected && (
                    <Check
                      size={14}
                      strokeWidth={2}
                      className="shrink-0 text-[var(--primary)]"
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
