"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Sparkles, Square, Volume2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  listReadingExtensions,
  runReadingExtension,
  type ReadingExtensionManifest,
  type ReadingExtensionResult,
} from "@/lib/reading-api";

type VocabularyTerm = {
  term: string;
  meaning: string;
  usage: string;
};

type QuizQuestion = {
  id?: string;
  prompt: string;
  choices: string[];
  correct_choice_index?: number;
};

type TranslationResult = {
  translation: string;
  alternatives: string[];
  note: string;
};

export function ReadingExtensionBar({
  materialId,
  locator,
  selectionLocator,
  selection,
  onError,
}: {
  materialId: string;
  locator: number;
  /**
   * The unit the selection was made in, when there is one.
   *
   * `locator` is the *viewport* locator and drifts as the reader scrolls. The
   * server verifies the quote against the text of the unit it is told about
   * and 400s when they disagree, so a selection has to travel with its own.
   */
  selectionLocator?: number;
  selection?: string;
  onError: (message: string) => void;
}) {
  const { i18n, t } = useTranslation();
  const [extensions, setExtensions] = useState<ReadingExtensionManifest[]>([]);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<ReadingExtensionResult | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [speechLoading, setSpeechLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const speechEpochRef = useRef(0);

  function clearServerAudio() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }

  function stopSpeaking() {
    speechEpochRef.current += 1;
    window.speechSynthesis?.cancel();
    clearServerAudio();
    setSpeechLoading(false);
    setSpeaking(false);
  }

  useEffect(() => {
    let active = true;
    void listReadingExtensions()
      .then((rows) => {
        if (active) setExtensions(rows);
      })
      .catch((error) => {
        if (active)
          onError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      active = false;
    };
  }, [onError]);

  // Two effects, because the two things they clean up move on different
  // clocks. A result belongs to the document: keyed on `locator` as well, an
  // ordinary scroll erased a card the reader was still reading, since
  // `locator` is the scroll-derived *viewport* locator.
  useEffect(() => {
    setResult(null);
  }, [materialId]);

  // Speech, on the other hand, must stop the moment the reader navigates
  // away from the passage being read aloud — so this one keeps both keys.
  useEffect(() => {
    return () => {
      speechEpochRef.current += 1;
      window.speechSynthesis?.cancel();
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
      setSpeechLoading(false);
      setSpeaking(false);
    };
  }, [locator, materialId]);

  const actions = useMemo(
    () =>
      extensions.flatMap((extension) =>
        extension.actions.map((action) => ({ extension, action })),
      ),
    [extensions],
  );

  async function playServerTts(
    text: string,
    epoch: number,
  ): Promise<boolean> {
    const resp = await apiFetch(apiUrl("/api/voice/tts"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (epoch !== speechEpochRef.current) return true;
    if (!resp.ok) return false;
    const blob = await resp.blob();
    if (epoch !== speechEpochRef.current) return true;
    clearServerAudio();
    const url = URL.createObjectURL(blob);
    audioUrlRef.current = url;
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => {
      clearServerAudio();
      setSpeaking(false);
    };
    audio.onerror = () => {
      clearServerAudio();
      setSpeaking(false);
    };
    await audio.play();
    if (epoch !== speechEpochRef.current) {
      clearServerAudio();
      return true;
    }
    setSpeaking(true);
    return true;
  }

  function playBrowserSpeech(
    text: string,
    locale: string,
    epoch: number,
  ): boolean {
    if (epoch !== speechEpochRef.current) return true;
    if (!("speechSynthesis" in window)) return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = locale;
    const voice = pickSpeechVoice(window.speechSynthesis.getVoices(), locale);
    if (voice) utterance.voice = voice;
    utterance.rate = 0.95;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
    setSpeaking(true);
    return true;
  }

  async function run(
    extension: ReadingExtensionManifest,
    action: ReadingExtensionManifest["actions"][number],
  ) {
    const key = `${extension.id}:${action.id}`;
    setBusy(key);
    try {
      const next = await runReadingExtension(
        materialId,
        extension.id,
        action.id,
        {
          locator: selection?.trim() ? (selectionLocator ?? locator) : locator,
          selection: selection || "",
          locale: i18n.language,
        },
      );
      setResult(next);
      if (next.type === "browser_speech") {
        const text = String(next.payload.text || "").trim();
        const locale = String(next.payload.locale || i18n.language);
        if (!text) {
          onError(t("No speech voice is available in this browser."));
          return;
        }
        stopSpeaking();
        const epoch = speechEpochRef.current;
        setSpeechLoading(true);
        try {
          const played = await playServerTts(text, epoch);
          if (epoch !== speechEpochRef.current) return;
          if (!played && !playBrowserSpeech(text, locale, epoch)) {
            onError(
              t(
                "Speech is unavailable. Configure TTS in Settings → Voice, or use a browser with speech support.",
              ),
            );
          }
        } catch {
          if (epoch !== speechEpochRef.current) return;
          if (!playBrowserSpeech(text, locale, epoch)) {
            onError(
              t(
                "Speech is unavailable. Configure TTS in Settings → Voice, or use a browser with speech support.",
              ),
            );
          }
        } finally {
          if (epoch === speechEpochRef.current) setSpeechLoading(false);
        }
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  if (actions.length === 0) return null;
  return (
    <>
      <div className="flex shrink-0 gap-1.5 overflow-x-auto border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--muted)_25%,transparent)] px-2.5 py-2">
        {actions.map(({ extension, action }) => {
          const key = `${extension.id}:${action.id}`;
          const needsSelection =
            action.requires.includes("selection") && !selection?.trim();
          // `busy === key`, not `Boolean(busy)`: an action can take the full
          // 30s server timeout, and disabling all six meanwhile is
          // indistinguishable from the toolbar being broken.
          const disabled = busy === key || needsSelection;
          const builtInLabel = builtInActionLabel(extension.id, action.id);
          return (
            <button
              key={key}
              type="button"
              disabled={disabled}
              title={
                needsSelection
                  ? t("Select text in the document first.")
                  : undefined
              }
              onClick={() => void run(extension, action)}
              className="inline-flex h-8 min-w-[88px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-50"
            >
              {busy === key ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              <span className="truncate">
                {builtInLabel ? t(builtInLabel) : action.label}
              </span>
            </button>
          );
        })}
      </div>
      {speaking || speechLoading ? (
        <div
          role="status"
          className="flex shrink-0 items-center gap-2 border-b border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--muted-foreground)]"
        >
          {speechLoading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Volume2 size={14} />
          )}
          <span>
            {speechLoading ? t("Preparing speech") : t("Reading aloud")}
          </span>
          <button
            type="button"
            aria-label={t("Stop reading aloud")}
            title={t("Stop reading aloud")}
            onClick={stopSpeaking}
            className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--foreground)] transition hover:bg-[var(--muted)]"
          >
            <Square size={12} fill="currentColor" />
          </button>
        </div>
      ) : null}
      {result && result.type !== "browser_speech" ? (
        <ExtensionResult
          result={result}
          closeLabel={t("Close")}
          onClose={() => setResult(null)}
        />
      ) : null}
    </>
  );
}

function pickSpeechVoice(
  voices: SpeechSynthesisVoice[],
  locale: string,
): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const normalized = locale.toLowerCase().replace("_", "-");
  const language = normalized.split("-")[0] || normalized;
  const exact =
    voices.find((voice) => voice.lang.toLowerCase().replace("_", "-") === normalized) ||
    null;
  if (exact) return exact;
  const sameLanguage = voices.filter((voice) =>
    voice.lang.toLowerCase().replace("_", "-").startsWith(`${language}-`) ||
    voice.lang.toLowerCase().replace("_", "-") === language,
  );
  if (!sameLanguage.length) return null;
  const preferred = sameLanguage.find((voice) => {
    const name = voice.name.toLowerCase();
    return (
      name.includes("premium") ||
      name.includes("enhanced") ||
      name.includes("neural") ||
      name.includes("natural") ||
      name.includes("tingting") ||
      name.includes("meijia") ||
      name.includes("xiaoxiao")
    );
  });
  return preferred || sameLanguage[0] || null;
}

function builtInActionLabel(extensionId: string, actionId: string) {
  if (extensionId === "read_aloud" && actionId === "read") {
    return "Read aloud";
  }
  if (extensionId === "guided_learning" && actionId === "guide") {
    return "Guide me";
  }
  if (extensionId === "vocabulary" && actionId === "explain") {
    return "Explain vocabulary";
  }
  if (extensionId === "quiz" && actionId === "start") {
    return "Quiz me";
  }
  if (extensionId === "translation" && actionId === "translate_en") {
    return "Translate to English";
  }
  if (extensionId === "translation" && actionId === "translate_zh") {
    return "Translate to Chinese";
  }
  return "";
}

function ExtensionResult({
  result,
  closeLabel,
  onClose,
}: {
  result: ReadingExtensionResult;
  closeLabel: string;
  onClose: () => void;
}) {
  const questions = Array.isArray(result.payload.questions)
    ? (result.payload.questions as QuizQuestion[])
    : [];
  const items = Array.isArray(result.payload.items)
    ? result.payload.items.map(String)
    : [];
  const steps = Array.isArray(result.payload.steps)
    ? result.payload.steps.map(String)
    : [];
  const terms: VocabularyTerm[] = Array.isArray(result.payload.terms)
    ? result.payload.terms
        .map((row) => {
          if (typeof row !== "object" || row === null) return null;
          const term = row as Partial<VocabularyTerm>;
          return {
            term: String(term.term || ""),
            meaning: String(term.meaning || ""),
            usage: String(term.usage || ""),
          };
        })
        .filter((row): row is VocabularyTerm => row !== null)
    : [];
  const translation: TranslationResult = {
    translation: String(result.payload.translation || ""),
    alternatives: Array.isArray(result.payload.alternatives)
      ? result.payload.alternatives.map(String)
      : [],
    note: String(result.payload.note || ""),
  };
  const body = String(result.payload.body || result.payload.overview || "");
  return (
    <section className="relative shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-3 py-3 text-xs text-[var(--foreground)]">
      <button
        type="button"
        onClick={onClose}
        aria-label={closeLabel}
        className="absolute right-2 top-2 text-[var(--muted-foreground)]"
      >
        <X size={14} />
      </button>
      <h3 className="pr-6 font-semibold">{result.title}</h3>
      {result.message ? (
        <p className="mt-1 text-[var(--muted-foreground)]">{result.message}</p>
      ) : null}
      {body ? <p className="mt-2 whitespace-pre-wrap">{body}</p> : null}
      {translation.translation ? (
        <p className="mt-2 whitespace-pre-wrap font-medium">
          {translation.translation}
        </p>
      ) : null}
      {translation.note ? (
        <p className="mt-1 text-[var(--muted-foreground)]">
          {translation.note}
        </p>
      ) : null}
      {translation.alternatives.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--muted-foreground)]">
          {translation.alternatives.map((alternative, index) => (
            <li key={`${index}-${alternative}`}>{alternative}</li>
          ))}
        </ul>
      ) : null}
      {items.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {items.map((item, index) => (
            <li key={`${index}-${item}`}>{item}</li>
          ))}
        </ul>
      ) : null}
      {steps.length ? (
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          {steps.map((step, index) => (
            <li key={`${index}-${step}`}>{step}</li>
          ))}
        </ol>
      ) : null}
      {terms.length ? (
        <dl className="mt-2 space-y-2">
          {terms.map((term, index) => (
            <div
              key={`${index}-${term.term}`}
              className="border-t border-[var(--border)] pt-2 first:border-t-0 first:pt-0"
            >
              <dt className="font-medium">{term.term}</dt>
              <dd className="mt-1 text-[var(--muted-foreground)]">
                {term.meaning}
              </dd>
              <dd className="mt-1 text-[var(--muted-foreground)]">
                {term.usage}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {questions.length ? <QuizQuestions questions={questions} /> : null}
    </section>
  );
}

function QuizQuestions({ questions }: { questions: QuizQuestion[] }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, number>>({});

  return questions.map((question, index) => {
    const key = question.id || String(index);
    const selected = answers[key];
    const correctChoiceIndex = Number.isInteger(question.correct_choice_index)
      ? Number(question.correct_choice_index)
      : -1;
    const canGrade =
      correctChoiceIndex >= 0 && correctChoiceIndex < question.choices.length;
    if (!canGrade) {
      return (
        <div key={key} className="mt-3">
          <p className="font-medium">{question.prompt}</p>
          <ol className="mt-1 list-inside list-[upper-alpha] space-y-0.5 text-[var(--muted-foreground)]">
            {question.choices.map((choice) => (
              <li key={choice}>{choice}</li>
            ))}
          </ol>
        </div>
      );
    }
    return (
      <fieldset key={key} className="mt-3">
        <legend className="font-medium">{question.prompt}</legend>
        <div className="mt-1 grid gap-1">
          {question.choices.map((choice, choiceIndex) => (
            <button
              key={choice}
              type="button"
              aria-pressed={selected === choiceIndex}
              onClick={() =>
                setAnswers((current) => ({ ...current, [key]: choiceIndex }))
              }
              className="rounded-md border border-[var(--border)] px-2 py-1.5 text-left text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] aria-pressed:bg-[var(--muted)] aria-pressed:text-[var(--foreground)]"
            >
              {String.fromCharCode(65 + choiceIndex)}. {choice}
            </button>
          ))}
        </div>
        {selected !== undefined ? (
          <p
            role="status"
            className={`mt-1 font-medium ${
              selected === correctChoiceIndex
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-amber-600 dark:text-amber-400"
            }`}
          >
            {selected === correctChoiceIndex ? t("Correct") : t("Incorrect")}
          </p>
        ) : null}
      </fieldset>
    );
  });
}
