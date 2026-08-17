"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  AudioLines,
  Bookmark,
  BookmarkPlus,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ChevronsDownUp,
  ChevronsUpDown,
  ClipboardList,
  Columns2,
  Download,
  Eye,
  Flag,
  Keyboard,
  Languages,
  ListChecks,
  Loader2,
  MousePointerClick,
  Pencil,
  Trash2,
  Type,
  Volume2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  annotationApi,
  bilingualApi,
  immersiveReadingApi,
  type BilingualAnnotation,
  type BilingualBookmark,
  type BilingualExportStyle,
  type BilingualNavigation,
  type BilingualPairing,
  type BilingualReadingPosition,
  type BilingualSection,
  type ChapterMapEntry,
  type DictionaryResult,
  ApiRequestError,
} from "@/lib/immersive-reading-api";
import { extractDictionaryWord, type DictionaryAnchorRect } from "@/lib/dictionary-ui";
import {
  playWordPronunciation,
  subscribePronunciationState,
  type PronunciationPlaybackState,
  type WordPronunciationAccent,
} from "@/lib/word-pronunciation";
import {
  BILINGUAL_CLICK_LOOKUP_STORAGE_KEY,
  BILINGUAL_DUAL_PANE_MEDIA_QUERY,
  BILINGUAL_FONT_FAMILY_STORAGE_KEY,
  BILINGUAL_FONT_SIZE_STORAGE_KEY,
  BILINGUAL_READER_MODE_STORAGE_KEY,
  BILINGUAL_THEME_STORAGE_KEY,
  parseBilingualFontFamily,
  parseBilingualFontSize,
  parseBilingualReaderMode,
  parseBilingualTheme,
  parseStoredBoolean,
  readerShortcutFromKeyboardEvent,
  scrollPaneToGroup,
  shouldIgnoreLookupTarget,
  visibleGroupFromElements,
  wordRangeAtPoint,
  type BilingualFontFamily,
  type BilingualFontSize,
  type BilingualReaderMode,
  type BilingualTheme,
} from "@/lib/bilingual-reader-ux";
import {
  getCachedWord,
  setCachedWord,
  getCachedTranslation,
  setCachedTranslation,
} from "@/lib/dictionary-cache";
import DictionaryPanel from "@/components/common/DictionaryPanel";
import MiniDictionaryTooltip from "@/components/common/MiniDictionaryTooltip";
import TranslationTaskBoardPanel from "@/components/translation/TranslationTaskBoard";
import { translationTaskApi } from "@/lib/translation-tasks-api";
import { apiFetch } from "@/lib/api";

interface BilingualReaderProps {
  pairingId: string;
  onBack: () => void;
  initialChapterId?: string;
  initialGroupIndex?: number;
  onVocabularyAdded: () => void;
  onToast: (message: string) => void;
  onErrorToast: (message: string) => void;
}

type IssueType = "misalignment" | "wrong_chapter" | "missing_translation" | "translation_error" | "other";
type DictionaryPresentation = "mini" | "full";

const THEME_STYLES: Record<BilingualTheme, CSSProperties> = {
  system: {},
  sepia: {
    backgroundColor: "#f8f1e3",
    color: "#2d241e",
    "--background": "#f8f1e3",
    "--foreground": "#2d241e",
    "--card": "#efe6d5",
    "--muted": "#e8deca",
    "--muted-foreground": "#786b5e",
    "--border": "#dfd3be",
    "--primary": "#8c4f27",
    "--primary-foreground": "#ffffff",
  } as CSSProperties,
  dark: {
    backgroundColor: "#18181b",
    color: "#fafafa",
    "--background": "#18181b",
    "--foreground": "#fafafa",
    "--card": "#27272a",
    "--muted": "#3f3f46",
    "--muted-foreground": "#a1a1aa",
    "--border": "#3f3f46",
    "--primary": "#60a5fa",
    "--primary-foreground": "#000000",
  } as CSSProperties,
  oled: {
    backgroundColor: "#000000",
    color: "#f1f5f9",
    "--background": "#000000",
    "--foreground": "#f1f5f9",
    "--card": "#0a0a0a",
    "--muted": "#171717",
    "--muted-foreground": "#94a3b8",
    "--border": "#262626",
    "--primary": "#38bdf8",
    "--primary-foreground": "#000000",
  } as CSSProperties,
};

const FONT_SIZE_STYLES: Record<BilingualFontSize, { en: string; zh: string }> = {
  sm: { en: "text-[14px] leading-[1.65]", zh: "text-[13px] leading-[1.65]" },
  base: { en: "text-[16px] leading-[1.8]", zh: "text-[14px] leading-[1.8]" },
  lg: { en: "text-[18px] leading-[1.9]", zh: "text-[16px] leading-[1.9]" },
  xl: { en: "text-[20px] leading-[2.0]", zh: "text-[18px] leading-[2.0]" },
  "2xl": { en: "text-[22px] leading-[2.1]", zh: "text-[20px] leading-[2.1]" },
};

function rangePointFromOffsets(container: HTMLElement, start: number, end: number): Range | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let cursor = 0;
  let currentNode: Node | null;
  let rangeStart: { node: Node; offset: number } | null = null;
  let rangeEnd: { node: Node; offset: number } | null = null;
  while ((currentNode = walker.nextNode())) {
    const text = currentNode.textContent || "";
    const nodeEnd = cursor + text.length;
    if (!rangeStart && start >= cursor && start <= nodeEnd) {
      rangeStart = { node: currentNode, offset: start - cursor };
    }
    if (end >= cursor && end <= nodeEnd) {
      rangeEnd = { node: currentNode, offset: end - cursor };
      break;
    }
    cursor = nodeEnd;
  }
  if (!rangeStart || !rangeEnd) return null;
  const range = document.createRange();
  range.setStart(rangeStart.node, rangeStart.offset);
  range.setEnd(rangeEnd.node, rangeEnd.offset);
  return range;
}

function normalizeFingerprint(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, " ")
    .replace(/[\s\u200b]+/g, " ")
    .trim();
}

function groupIndexFromNode(node: Node | null, fallback: number): number {
  const element = node instanceof Element ? node : node?.parentElement;
  const group = element?.closest<HTMLElement>("[data-group-index]");
  const value = Number(group?.dataset.groupIndex);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function dictionarySeedFromGroup(group: { en: string[] } | undefined): string {
  const words = (group?.en?.join(" ") || "").match(/[A-Za-z][A-Za-z'-]*/g) || [];
  const stopWords = new Set([
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "from", "by", "as", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "he", "she", "they", "we",
  ]);
  return (
    words.find((word) => word.length >= 4 && !stopWords.has(word.toLowerCase())) ||
    words[0] ||
    ""
  );
}

export function BilingualReader({
  pairingId,
  onBack,
  initialChapterId,
  initialGroupIndex = 0,
  onVocabularyAdded,
  onToast,
  onErrorToast,
}: BilingualReaderProps) {
  const { t } = useTranslation();
  const [pairing, setPairing] = useState<BilingualPairing | null>(null);
  const [section, setSection] = useState<BilingualSection | null>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [preferredReaderMode, setPreferredReaderMode] = useState<BilingualReaderMode>(() =>
    parseBilingualReaderMode(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_READER_MODE_STORAGE_KEY),
    ),
  );
  const [theme, setTheme] = useState<BilingualTheme>(() =>
    parseBilingualTheme(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_THEME_STORAGE_KEY),
    ),
  );
  const [fontSize, setFontSize] = useState<BilingualFontSize>(() =>
    parseBilingualFontSize(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_FONT_SIZE_STORAGE_KEY),
    ),
  );
  const [fontFamily, setFontFamily] = useState<BilingualFontFamily>(() =>
    parseBilingualFontFamily(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_FONT_FAMILY_STORAGE_KEY),
    ),
  );
  const [dualPaneSupported, setDualPaneSupported] = useState(false);
  const [expandAll, setExpandAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [annotations, setAnnotations] = useState<BilingualAnnotation[]>([]);
  const [bookmarks, setBookmarks] = useState<BilingualBookmark[]>([]);
  const [navigation, setNavigation] = useState<BilingualNavigation | null>(null);
  const [flagTarget, setFlagTarget] = useState<number | null>(null);
  const [showReview, setShowReview] = useState(false);
  const [showBookmarks, setShowBookmarks] = useState(false);
  const [showTaskBoard, setShowTaskBoard] = useState(false);
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const [showAppearanceModal, setShowAppearanceModal] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportStyle, setExportStyle] = useState<BilingualExportStyle>("folded");
  const [exportFontFamily, setExportFontFamily] = useState("Noto Serif CJK TC");
  const [exportCss, setExportCss] = useState("");
  const [chapterTaskSummaries, setChapterTaskSummaries] = useState<Array<{ chapter_id: string; completed: boolean }>>([]);
  const [activeGroup, setActiveGroup] = useState(0);
  const [manualOpenGroups, setManualOpenGroups] = useState<Set<number>>(new Set());
  const [manualClosedGroups, setManualClosedGroups] = useState<Set<number>>(new Set());
  const [hoveredGroup, setHoveredGroup] = useState<number | null>(null);
  const [pinnedHoverGroup, setPinnedHoverGroup] = useState<number | null>(null);
  const [clickLookupEnabled, setClickLookupEnabled] = useState(() =>
    typeof window === "undefined"
      ? false
      : parseStoredBoolean(window.localStorage.getItem(BILINGUAL_CLICK_LOOKUP_STORAGE_KEY)),
  );
  const [audioState, setAudioState] = useState<PronunciationPlaybackState>({
    isPlaying: false,
    word: null,
    accent: null,
  });
  const contentRef = useRef<HTMLDivElement>(null);
  const inlinePaneRef = useRef<HTMLDivElement>(null);
  const englishPaneRef = useRef<HTMLDivElement>(null);
  const chinesePaneRef = useRef<HTMLDivElement>(null);
  const dualSyncGuardRef = useRef(0);
  const pendingPositionRef = useRef<BilingualReadingPosition | null>(null);
  const pendingGroupJumpRef = useRef(false);
  const scrollPercentRef = useRef(0);
  const visibleGroupRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const sectionRequestRef = useRef(0);
  const [dictPopover, setDictPopover] = useState<{
    word: string;
    context: string;
    anchor: DictionaryAnchorRect;
    selectedText: string;
    initialMode: "dictionary" | "translate";
    groupIndex: number;
    presentation: DictionaryPresentation;
  } | null>(null);
  const [dictResult, setDictResult] = useState<DictionaryResult | null>(null);
  const [dictLoading, setDictLoading] = useState(false);
  const [dictError, setDictError] = useState<string | null>(null);
  const [savingWord, setSavingWord] = useState(false);
  const dictReqIdRef = useRef(0);
  const dictAbortRef = useRef<AbortController | null>(null);
  const lastSelectionRef = useRef("");
  const miniLookupRef = useRef<{ word: string; at: number }>({ word: "", at: 0 });
  const lastCompletedChapterCountRef = useRef<number | null>(null);

  const readerMode: BilingualReaderMode =
    preferredReaderMode === "dual" && !dualPaneSupported ? "inline" : preferredReaderMode;

  useEffect(() => {
    return subscribePronunciationState(setAudioState);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_READER_MODE_STORAGE_KEY, preferredReaderMode);
  }, [preferredReaderMode]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_FONT_SIZE_STORAGE_KEY, fontSize);
  }, [fontSize]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_FONT_FAMILY_STORAGE_KEY, fontFamily);
  }, [fontFamily]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_CLICK_LOOKUP_STORAGE_KEY, String(clickLookupEnabled));
  }, [clickLookupEnabled]);

  useEffect(() => {
    const query = window.matchMedia(BILINGUAL_DUAL_PANE_MEDIA_QUERY);
    const update = () => setDualPaneSupported(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      bilingualApi.get(pairingId),
      bilingualApi.readingPosition(pairingId),
      bilingualApi.navigation(pairingId),
      bilingualApi.bookmarks(pairingId),
    ])
      .then(([pairingData, positionData, navigationData, bookmarkData]) => {
        if (cancelled) return;
        setPairing(pairingData);
        const saved = positionData.position;
        const targetIndex = initialChapterId
          ? (pairingData.chapter_map || []).findIndex((chapter) => chapter.id === initialChapterId)
          : -1;
        const target = targetIndex >= 0 ? pairingData.chapter_map?.[targetIndex] : undefined;
        if (targetIndex >= 0 && target) {
          pendingPositionRef.current = {
            pairing_id: pairingId,
            chapter_id: target.id,
            chapter_index: targetIndex,
            group_index: Math.max(0, initialGroupIndex),
            epub_cfi: "",
            section_href: target.english,
            scroll_percent: 0,
            text_fingerprint: "",
            updated_at: saved?.updated_at || 0,
          };
          pendingGroupJumpRef.current = true;
        } else {
          pendingPositionRef.current = saved;
        }
        setNavigation(navigationData.navigation);
        setBookmarks(bookmarkData.bookmarks);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    annotationApi.list(pairingId, "open").then((data) => {
      if (!cancelled) setAnnotations(data.annotations);
    });
    return () => {
      cancelled = true;
    };
  }, [initialChapterId, initialGroupIndex, pairingId]);

  useEffect(() => {
    let cancelled = false;
    translationTaskApi.list({ sourceType: "bilingual", sourceId: pairingId })
      .then((board) => {
        if (!cancelled) setChapterTaskSummaries(board.chapters || []);
        lastCompletedChapterCountRef.current = (board.chapters || []).filter(
          (chapter) => chapter.completed,
        ).length;
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pairingId]);

  const loadChapter = useCallback(
    (index: number, options?: { recordHistory?: boolean }) => {
      if (!pairing?.chapter_map?.length) return;
      const clamped = Math.max(0, Math.min(index, pairing.chapter_map.length - 1));
      const entry = pairing.chapter_map[clamped];
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      const requestId = ++sectionRequestRef.current;
      if (options?.recordHistory !== false) {
        void bilingualApi
          .recordNavigation(pairingId, {
            chapter_index: clamped,
            group_index: 0,
            epub_cfi: "",
            section_href: entry.english,
            scroll_percent: 0,
            text_fingerprint: "",
          })
          .then((result) => setNavigation(result.navigation))
          .catch(() => undefined);
      }
      setChapterIndex(clamped);
      setSectionLoading(true);
      bilingualApi
        .section(pairingId, entry.id)
        .then((nextSection) => {
          if (sectionRequestRef.current !== requestId) return;
          setSection(nextSection);
        })
        .catch(() => {
          if (sectionRequestRef.current !== requestId) return;
          setSection(null);
        })
        .finally(() => {
          if (sectionRequestRef.current !== requestId) return;
          setSectionLoading(false);
        });
    },
    [pairing, pairingId],
  );

  useEffect(() => {
    if (pairing?.aligned && pairing.chapter_map?.length) {
      const saved = pendingPositionRef.current;
      loadChapter(saved?.chapter_index ?? 0, { recordHistory: false });
    }
  }, [pairing, loadChapter]);

  const handleTaskBoardChange = useCallback(
    (board: { chapters?: Array<{ chapter_id: string; completed: boolean }> }) => {
      const summaries = board.chapters || [];
      setChapterTaskSummaries(summaries);
      const completedCount = summaries.filter((chapter) => chapter.completed).length;
      const previousCount = lastCompletedChapterCountRef.current;
      lastCompletedChapterCountRef.current = completedCount;
      if (previousCount !== null && completedCount > previousCount) {
        loadChapter(chapterIndex, { recordHistory: false });
      }
    },
    [chapterIndex, loadChapter],
  );

  useEffect(() => {
    const content = readerMode === "dual" ? englishPaneRef.current : inlinePaneRef.current;
    const saved = pendingPositionRef.current;
    if (!content || sectionLoading || !section) return;
    if (!saved) {
      content.scrollTop = 0;
      if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, 0);
      scrollPercentRef.current = 0;
      visibleGroupRef.current = 0;
      setActiveGroup(0);
      return;
    }
    const sameChapter = saved.chapter_id === section.chapter;
    let groupIndex = sameChapter ? saved.group_index : 0;
    if (sameChapter && saved.text_fingerprint) {
      const fingerprint = normalizeFingerprint(saved.text_fingerprint);
      const matched = section.groups.findIndex((group) =>
        normalizeFingerprint(group.en.join(" ")) === fingerprint,
      );
      if (matched >= 0) groupIndex = matched;
    }
    visibleGroupRef.current = groupIndex;
    setActiveGroup(groupIndex);
    if (pendingGroupJumpRef.current && sameChapter) {
      const groupElement = content.querySelector<HTMLElement>(
        `[data-group-index="${groupIndex}"]`,
      );
      if (groupElement) {
        content.scrollTop = Math.max(0, groupElement.offsetTop - 24);
        if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, groupIndex);
        const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
        scrollPercentRef.current = Math.max(
          0,
          Math.min(100, (content.scrollTop / maxScroll) * 100),
        );
        pendingGroupJumpRef.current = false;
        pendingPositionRef.current = null;
        return;
      }
    }
    const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
    scrollPercentRef.current = sameChapter ? saved.scroll_percent : 0;
    content.scrollTop = (maxScroll * scrollPercentRef.current) / 100;
    if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, groupIndex);
    pendingPositionRef.current = null;
  }, [readerMode, section, sectionLoading]);

  const currentPositionInput = useCallback(() => {
    const entry = pairing?.chapter_map?.[chapterIndex];
    const group = section?.groups?.[visibleGroupRef.current];
    return {
      chapter_index: chapterIndex,
      group_index: visibleGroupRef.current,
      epub_cfi: "",
      section_href: entry?.english || "",
      scroll_percent: scrollPercentRef.current,
      text_fingerprint: normalizeFingerprint(group?.en?.join(" ") || "").slice(0, 500),
    };
  }, [chapterIndex, pairing, section]);

  const savePosition = useCallback(() => {
    const entry = pairing?.chapter_map?.[chapterIndex];
    if (!pairing || !section || !entry || section.chapter !== entry.id) return;
    void bilingualApi.updateReadingPosition(pairingId, currentPositionInput()).catch(() => {
      // Position restoration is best-effort; reading remains usable if persistence fails.
    });
  }, [chapterIndex, currentPositionInput, pairing, pairingId, section]);

  const savePositionRef = useRef(savePosition);

  useEffect(() => {
    savePositionRef.current = savePosition;
  }, [savePosition]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      savePositionRef.current();
    };
  }, []);

  useEffect(() => {
    if (readerMode !== "dual") {
      const content = inlinePaneRef.current;
      if (!content) return;
      const handleScroll = () => {
        const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
        scrollPercentRef.current = Math.max(0, Math.min(100, (content.scrollTop / maxScroll) * 100));
        const elements = Array.from(content.querySelectorAll<HTMLElement>("[data-group-index]"));
        const visible = visibleGroupFromElements(
          elements,
          content.scrollTop,
          content.clientHeight,
          visibleGroupRef.current,
        );
        visibleGroupRef.current = visible;
        setActiveGroup(visible);
        if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = window.setTimeout(savePosition, 1000);
      };
      content.addEventListener("scroll", handleScroll, { passive: true });
      return () => {
        content.removeEventListener("scroll", handleScroll);
        if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      };
    }

    const english = englishPaneRef.current;
    const chinese = chinesePaneRef.current;
    if (!english || !chinese) return;
    const handleDualScroll = (source: HTMLDivElement, other: HTMLDivElement) => {
      if (performance.now() < dualSyncGuardRef.current) return;
      const elements = Array.from(source.querySelectorAll<HTMLElement>("[data-group-index]"));
      const visible = visibleGroupFromElements(
        elements,
        source.scrollTop,
        source.clientHeight,
        visibleGroupRef.current,
      );
      if (visible !== visibleGroupRef.current) {
        visibleGroupRef.current = visible;
        setActiveGroup(visible);
        dualSyncGuardRef.current = performance.now() + 100;
        scrollPaneToGroup(other, visible, "auto", 48);
      }
      if (source === english) {
        const maxScroll = Math.max(1, english.scrollHeight - english.clientHeight);
        scrollPercentRef.current = Math.max(0, Math.min(100, (english.scrollTop / maxScroll) * 100));
      }
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(savePosition, 1000);
    };
    const onEnglishScroll = () => handleDualScroll(english, chinese);
    const onChineseScroll = () => handleDualScroll(chinese, english);
    english.addEventListener("scroll", onEnglishScroll, { passive: true });
    chinese.addEventListener("scroll", onChineseScroll, { passive: true });
    return () => {
      english.removeEventListener("scroll", onEnglishScroll);
      chinese.removeEventListener("scroll", onChineseScroll);
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, [readerMode, savePosition, section]);

  useEffect(() => {
    setManualOpenGroups(new Set());
    setManualClosedGroups(new Set());
    setHoveredGroup(null);
    setPinnedHoverGroup(null);
    if (readerMode === "dual") {
      scrollPaneToGroup(englishPaneRef.current, visibleGroupRef.current, "auto", 48);
      scrollPaneToGroup(chinesePaneRef.current, visibleGroupRef.current, "auto", 48);
    } else {
      scrollPaneToGroup(inlinePaneRef.current, visibleGroupRef.current, "auto", 48);
    }
  }, [chapterIndex, readerMode]);

  useEffect(() => {
    setManualOpenGroups(new Set());
    setManualClosedGroups(new Set());
  }, [expandAll]);

  // Cancel any pending dictionary lookup when chapter changes.
  useEffect(() => {
    dictAbortRef.current?.abort();
    dictReqIdRef.current++;
    setDictPopover(null);
    setDictResult(null);
    setDictLoading(false);
  }, [chapterIndex, pairingId]);

  // Cancel on unmount.
  useEffect(() => {
    return () => {
      dictAbortRef.current?.abort();
    };
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await apiFetch(bilingualApi.exportUrl(pairingId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style: exportStyle,
          font_family: exportFontFamily,
          custom_css: exportCss,
        }),
      });
      if (!response.ok) throw new Error(t("Export failed."));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${pairing?.en_title || "bilingual"}_${exportStyle}.epub`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      onToast(t("EPUB exported successfully."));
      setShowExportDialog(false);
    } catch (err) {
      onErrorToast(err instanceof Error ? err.message : t("Export failed."));
    } finally {
      setExporting(false);
    }
  };

  const handleAddBookmark = useCallback(async () => {
    try {
      const input = currentPositionInput();
      const group = section?.groups?.[input.group_index];
      const bookmark = await bilingualApi.addBookmark(
        pairingId,
        input,
        "",
        group?.en?.join(" ") || "",
      );
      setBookmarks((prev) => [bookmark, ...prev]);
      setShowBookmarks(true);
    } catch {
      // Keep reading if bookmark persistence fails.
    }
  }, [currentPositionInput, pairingId, section]);

  const handleJumpBookmark = async (bookmark: BilingualBookmark) => {
    pendingPositionRef.current = bookmark;
    try {
      const result = await bilingualApi.recordNavigation(pairingId, {
        chapter_index: bookmark.chapter_index,
        group_index: bookmark.group_index,
        epub_cfi: bookmark.epub_cfi,
        section_href: bookmark.section_href,
        scroll_percent: bookmark.scroll_percent,
        text_fingerprint: bookmark.text_fingerprint,
      });
      setNavigation(result.navigation);
    } catch {
      // Navigation history is best-effort.
    }
    loadChapter(bookmark.chapter_index, { recordHistory: false });
  };

  const handleNavigateHistory = async (direction: "back" | "forward") => {
    try {
      const result =
        direction === "back"
          ? await bilingualApi.navigateBack(pairingId)
          : await bilingualApi.navigateForward(pairingId);
      setNavigation(result.navigation);
      pendingPositionRef.current = result.position;
      loadChapter(result.position.chapter_index, { recordHistory: false });
    } catch {
      // Disabled buttons normally prevent this path.
    }
  };

  const handleRenameBookmark = async (bookmarkId: string, title: string) => {
    try {
      const updated = await bilingualApi.renameBookmark(pairingId, bookmarkId, title);
      setBookmarks((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch {
      // Keep the old title if rename fails.
    }
  };

  const handleDeleteBookmark = async (bookmarkId: string) => {
    try {
      await bilingualApi.deleteBookmark(pairingId, bookmarkId);
      setBookmarks((prev) => prev.filter((item) => item.id !== bookmarkId));
    } catch {
      // Ignore delete failures.
    }
  };

  const handleFlag = async (groupIndex: number, issueType: IssueType, note: string) => {
    if (!pairing?.chapter_map?.[chapterIndex]) return;
    const chapterId = pairing.chapter_map[chapterIndex].id;
    try {
      const ann = await annotationApi.add(pairingId, {
        chapter_id: chapterId,
        group_index: groupIndex,
        issue_type: issueType,
        note,
      });
      setAnnotations((prev) => [...prev, ann]);
    } catch {
      // ignore
    }
    setFlagTarget(null);
  };

  const handleResolveAnnotation = async (annotationId: string) => {
    try {
      await annotationApi.resolve(pairingId, annotationId, true);
      setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
    } catch {
      // ignore
    }
  };

  const handleDictionaryLookup = useCallback(async (word: string, context: string) => {
    dictAbortRef.current?.abort();
    const controller = new AbortController();
    dictAbortRef.current = controller;
    const reqId = ++dictReqIdRef.current;

    // Client-side cache: instant display for previously looked-up words.
    const cached = getCachedWord(word);
    if (cached) {
      setDictResult(cached);
      setDictError(null);
      setDictLoading(false);
      return;
    }

    setDictLoading(true);
    setDictResult(null);
    setDictError(null);
    try {
      const result = await immersiveReadingApi.dictionary(word, context, controller.signal);
      if (reqId !== dictReqIdRef.current) return;
      setCachedWord(word, result);
      setDictResult(result);
    } catch (err) {
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      const msg = err instanceof Error ? err.message : String(err);
      const status = err instanceof ApiRequestError ? err.status : undefined;
      if (status === 503) {
        setDictError(msg || t("Dictionary service unavailable. Check the active model in settings."));
      } else if (status === 504) {
        setDictError(t("Dictionary lookup timed out. The local model may still be loading."));
      } else {
        setDictError(t("Lookup failed.") + " " + msg);
      }
    } finally {
      if (reqId === dictReqIdRef.current) setDictLoading(false);
    }
  }, [t]);

  const handleTranslateText = useCallback(async (text: string) => {
    dictAbortRef.current?.abort();
    const controller = new AbortController();
    dictAbortRef.current = controller;
    const reqId = ++dictReqIdRef.current;
    const targetLang = "Chinese";
    setDictLoading(true);
    setDictResult(null);
    // Client-side cache: instant display for previously translated text.
    const cached = getCachedTranslation(text, targetLang);
    if (cached) {
      setDictResult({
        word: text.length > 30 ? text.slice(0, 30) + "\u2026" : text,
        phonetic: "",
        definitions: [],
        context_note: cached,
      });
      setDictError(null);
      setDictLoading(false);
      return;
    }
    try {
      const result = await immersiveReadingApi.translate(text, targetLang, controller.signal);
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      setCachedTranslation(text, targetLang, result.translation);
      setDictResult({
        word: text.length > 30 ? text.slice(0, 30) + "\u2026" : text,
        phonetic: "",
        definitions: [],
        context_note: result.translation,
      });
      setDictError(null);
    } catch (err) {
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      const status = err instanceof ApiRequestError ? err.status : undefined;
      const msg = err instanceof Error ? err.message : String(err);
      let errorMessage: string;
      if (status === 504) {
        errorMessage = t("Translation timed out. The model may still be loading.");
      } else if (status === 503) {
        errorMessage = msg || t("Translation service unavailable. Please try again.");
      } else if (status === 429) {
        errorMessage = t("Rate limit exceeded. Please wait a moment.");
      } else if (status && status >= 500) {
        errorMessage = t("Translation service unavailable. Please try again.");
      } else {
        errorMessage = t("Translation failed.") + (msg ? ` ${msg}` : "");
      }
      setDictError(errorMessage);
    } finally {
      if (reqId === dictReqIdRef.current) setDictLoading(false);
    }
  }, [t]);

  const handleTextSelection = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() || "";
    if (!selection || !text || selection.rangeCount === 0 || !contentRef.current) {
      lastSelectionRef.current = "";
      return;
    }
    if (
      miniLookupRef.current.word === text &&
      performance.now() - miniLookupRef.current.at < 400
    ) {
      return;
    }
    const anchor = selection.anchorNode;
    if (!anchor || !contentRef.current.contains(anchor)) {
      return;
    }
    if (lastSelectionRef.current === text) return;
    lastSelectionRef.current = text;
    // Get the sentence containing the selection for context.
    const fullText = selection.anchorNode.parentElement?.closest("p")?.textContent || "";
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const word = extractDictionaryWord(text);
    // Single English word → dictionary mode. Multi-word / sentence → translate.
    const isSingleWord = !!word;
    const selectedText = isSingleWord ? word : text.slice(0, 2000);
    if (!selectedText.trim()) return;
    const context = fullText.slice(0, 2000);
    const initialMode: "dictionary" | "translate" = isSingleWord ? "dictionary" : "translate";
    const groupIndex = groupIndexFromNode(anchor, visibleGroupRef.current);
    setDictPopover({
      word: isSingleWord ? word : selectedText,
      context,
      selectedText,
      initialMode,
      groupIndex,
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      presentation: "full",
    });
    if (isSingleWord) {
      handleDictionaryLookup(word, context);
    } else {
      handleTranslateText(selectedText);
    }
  }, [handleDictionaryLookup, handleTranslateText]);

  const openWordLookupAtPoint = useCallback(
    (x: number, y: number, target: EventTarget | null) => {
      if (shouldIgnoreLookupTarget(target)) return;
      const surface = contentRef.current;
      const targetNode = target instanceof Node ? target : null;
      const targetElement = target instanceof Element ? target : targetNode?.parentElement;
      const paragraph = targetElement?.closest("p");
      if (!surface || !paragraph || !surface.contains(paragraph)) return;

      const range = wordRangeAtPoint(paragraph, x, y);
      if (!range) return;
      const word = extractDictionaryWord(range.toString());
      if (!word) return;
      const rect = range.getBoundingClientRect();
      const anchor: DictionaryAnchorRect =
        rect.width || rect.height
          ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
          : { left: x, right: x + 1, top: y, bottom: y + 1 };
      const context = (paragraph.textContent || "").slice(0, 2000);
      miniLookupRef.current = { word, at: performance.now() };
      setDictPopover({
        word,
        context,
        selectedText: word,
        initialMode: "dictionary",
        groupIndex: groupIndexFromNode(range.startContainer, visibleGroupRef.current),
        anchor,
        presentation: "mini",
      });
      handleDictionaryLookup(word, context);
    },
    [handleDictionaryLookup],
  );

  const handleSentenceClick = useCallback((event: MouseEvent) => {
    if (event.detail !== 3) return;
    const target = event.target as Node | null;
    const paragraph = target instanceof Element ? target.closest("p") : null;
    const caretRange = document.caretRangeFromPoint?.(event.clientX, event.clientY);
    if (!paragraph || !caretRange) return;
    const text = paragraph.textContent || "";
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    let cursor = 0;
    let offset = 0;
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const content = node.textContent || "";
      if (node === caretRange.startContainer) {
        offset = cursor + Math.min(caretRange.startOffset, content.length);
        break;
      }
      cursor += content.length;
    }
    let start = 0;
    for (const match of text.slice(0, offset).matchAll(/[.!?。！？]+["'”’]?\s+/g)) {
      start = (match.index ?? 0) + match[0].length;
    }
    const boundary = text.slice(offset).match(/[^.!?。！？]+[.!?。！？]+["'”’]?/);
    const end = boundary ? Math.min(text.length, offset + boundary[0].length) : text.length;
    start = Math.max(0, Math.min(start, end));
    const range = rangePointFromOffsets(paragraph, start, end);
    const sentence = text.slice(start, end).trim();
    if (!range || !sentence) return;
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const rect = range.getBoundingClientRect();
    lastSelectionRef.current = sentence;
    setDictPopover({
      word: sentence.length > 30 ? sentence.slice(0, 30) + "…" : sentence,
      context: text.slice(0, 2000),
      selectedText: sentence,
      initialMode: "translate",
      groupIndex: groupIndexFromNode(paragraph, visibleGroupRef.current),
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      presentation: "full",
    });
    void handleTranslateText(sentence);
  }, [handleTranslateText]);

  useEffect(() => {
    const ref = contentRef.current;
    if (!ref) return;
    let timer: number | null = null;
    const handleClickLookup = (event: MouseEvent) => {
      if (
        event.detail !== 1 ||
        !clickLookupEnabled ||
        window.getSelection()?.toString().trim()
      ) {
        return;
      }
      openWordLookupAtPoint(event.clientX, event.clientY, event.target);
    };
    const scheduleSelection = () => {
      if (timer !== null) window.clearTimeout(timer);
      // Mobile browsers may finish the native selection after pointerup.
      timer = window.setTimeout(handleTextSelection, 80);
    };
    ref.addEventListener("pointerup", scheduleSelection);
    ref.addEventListener("click", handleSentenceClick);
    ref.addEventListener("click", handleClickLookup);
    document.addEventListener("selectionchange", scheduleSelection);
    return () => {
      ref.removeEventListener("pointerup", scheduleSelection);
      ref.removeEventListener("click", handleSentenceClick);
      ref.removeEventListener("click", handleClickLookup);
      document.removeEventListener("selectionchange", scheduleSelection);
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [
    clickLookupEnabled,
    handleSentenceClick,
    handleTextSelection,
    openWordLookupAtPoint,
    sectionLoading,
  ]);

  const handleDictLookupClick = () => {
    if (!dictPopover) return;
    handleDictionaryLookup(dictPopover.word, dictPopover.context);
  };

  const handleTranslateSelection = async () => {
    if (!dictPopover) return;
    handleTranslateText(dictPopover.selectedText || dictPopover.word);
  };

  const handlePronounce = useCallback(
    (accent: WordPronunciationAccent) => {
      const word =
        extractDictionaryWord(dictPopover?.word || "") ||
        dictionarySeedFromGroup(section?.groups?.[activeGroup]);
      if (!word) return;
      void playWordPronunciation(word, accent, {
        onError: (error) => {
          onToast(typeof error === "string" ? error : error.message);
        },
      });
    },
    [activeGroup, dictPopover?.word, onToast, section],
  );

  const handleOpenFullDictionary = useCallback(() => {
    setDictPopover((current) => (current ? { ...current, presentation: "full" } : current));
  }, []);

  const closeDictionary = useCallback(() => {
    lastSelectionRef.current = "";
    dictAbortRef.current?.abort();
    dictReqIdRef.current++;
    setDictPopover(null);
    setDictResult(null);
    setDictError(null);
    setDictLoading(false);
  }, []);

  const moveGroup = useCallback(
    (delta: number) => {
      if (!section?.groups?.length) return;
      const next = Math.max(0, Math.min(activeGroup + delta, section.groups.length - 1));
      visibleGroupRef.current = next;
      setActiveGroup(next);
      closeDictionary();
      if (readerMode === "dual") {
        scrollPaneToGroup(englishPaneRef.current, next, "smooth", 60);
        scrollPaneToGroup(chinesePaneRef.current, next, "smooth", 60);
      } else {
        scrollPaneToGroup(inlinePaneRef.current, next, "smooth", 60);
      }
    },
    [activeGroup, closeDictionary, readerMode, section],
  );

  const toggleTranslation = useCallback((groupIndex = activeGroup) => {
    if (readerMode === "hover") {
      setPinnedHoverGroup((current) => (current === groupIndex ? null : groupIndex));
      return;
    }
    if (readerMode === "dual") {
      onToast(t("Translations are always visible in dual-pane mode."));
      return;
    }
    const isOpen = expandAll
      ? !manualClosedGroups.has(groupIndex)
      : manualOpenGroups.has(groupIndex);
    setManualOpenGroups((current) => {
      const next = new Set(current);
      if (isOpen) next.delete(groupIndex);
      else next.add(groupIndex);
      return next;
    });
    setManualClosedGroups((current) => {
      const next = new Set(current);
      if (isOpen) next.add(groupIndex);
      else next.delete(groupIndex);
      return next;
    });
  }, [activeGroup, expandAll, manualClosedGroups, manualOpenGroups, onToast, readerMode, t]);

  const lookupFromKeyboard = useCallback(() => {
    const group = section?.groups?.[activeGroup];
    const word = dictionarySeedFromGroup(group);
    if (!word || !group) return;
    const surface = readerMode === "dual" ? englishPaneRef.current : contentRef.current;
    const paragraph = surface?.querySelector<HTMLElement>(
      `[data-group-index="${activeGroup}"]`,
    )?.querySelector("p");
    const rect = paragraph?.getBoundingClientRect();
    const anchor: DictionaryAnchorRect = rect ?? {
      left: window.innerWidth / 2 - 20,
      right: window.innerWidth / 2 + 20,
      top: Math.max(24, window.innerHeight / 2 - 20),
      bottom: Math.max(44, window.innerHeight / 2 + 20),
    };
    const context = group.en.join(" ");
    setDictPopover({
      word,
      context,
      selectedText: word,
      initialMode: "dictionary",
      groupIndex: activeGroup,
      anchor,
      presentation: "full",
    });
    handleDictionaryLookup(word, context);
  }, [activeGroup, handleDictionaryLookup, readerMode, section]);

  useEffect(() => {
    const modalOpen =
      flagTarget !== null ||
      showReview ||
      showBookmarks ||
      showTaskBoard ||
      showExportDialog ||
      showAppearanceModal ||
      showShortcutsModal;

    const onKeyDown = (event: KeyboardEvent) => {
      const shortcut = readerShortcutFromKeyboardEvent(event, { modalOpen });
      if (!shortcut) return;

      if (shortcut === "close-modal") {
        if (showShortcutsModal) setShowShortcutsModal(false);
        else if (showExportDialog) setShowExportDialog(false);
        else if (showAppearanceModal) setShowAppearanceModal(false);
        else if (showTaskBoard) setShowTaskBoard(false);
        else if (showBookmarks) setShowBookmarks(false);
        else if (showReview) setShowReview(false);
        else if (flagTarget !== null) setFlagTarget(null);
        else if (dictPopover) closeDictionary();
        return;
      }

      event.preventDefault();
      switch (shortcut) {
        case "next-group":
          moveGroup(1);
          break;
        case "previous-group":
          moveGroup(-1);
          break;
        case "toggle-translation":
          toggleTranslation();
          break;
        case "lookup":
          lookupFromKeyboard();
          break;
        case "bookmark":
          void handleAddBookmark();
          break;
        case "pronounce":
          handlePronounce("en-US");
          break;
        case "pronounce-uk":
          handlePronounce("en-GB");
          break;
        case "toggle-shortcuts":
          setShowShortcutsModal((value) => !value);
          break;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    closeDictionary,
    dictPopover,
    flagTarget,
    handleAddBookmark,
    handlePronounce,
    lookupFromKeyboard,
    moveGroup,
    showBookmarks,
    showExportDialog,
    showAppearanceModal,
    showReview,
    showShortcutsModal,
    showTaskBoard,
    toggleTranslation,
  ]);

  const handleSaveVocabulary = async () => {
    if (!dictPopover || !pairing || savingWord) return;
    const chapter = pairing.chapter_map?.[chapterIndex];
    if (!chapter) return;
    setSavingWord(true);
    try {
      const word = extractDictionaryWord(dictPopover.selectedText) || dictPopover.word;
      const { lookup_warning } = await immersiveReadingApi.addWord(
        word,
        dictPopover.context,
        pairing.en_document_id,
        pairing.en_title,
        chapter.en_title || chapter.english,
        {
          pairing_id: pairingId,
          chapter_id: chapter.id,
          chapter_index: chapterIndex,
          group_index: dictPopover.groupIndex,
        },
      );
      onVocabularyAdded();
      onToast(
        lookup_warning
          ? `${t("Added to vocabulary")} — ${t("Definition unavailable")}`
          : t("Added to vocabulary"),
      );
      closeDictionary();
    } catch (cause) {
      onErrorToast(
        cause instanceof Error ? cause.message : String(cause),
      );
    } finally {
      setSavingWord(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!pairing) return null;

  if (!pairing.aligned) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <Languages className="size-10 text-[var(--muted-foreground)]" />
        <p className="text-[var(--muted-foreground)]">
          {t("This pairing has not been aligned yet.")}
        </p>
      </div>
    );
  }

  const chapters: ChapterMapEntry[] = pairing.chapter_map || [];
  const currentChapter = chapters[chapterIndex];
  const currentChapterCompleted = chapterTaskSummaries.find(
    (item) => item.chapter_id === currentChapter?.id,
  )?.completed;
  const flaggedGroups = new Set(
    annotations
      .filter((a) => a.chapter_id === currentChapter?.id)
      .map((a) => a.group_index),
  );
  const peekGroup = pinnedHoverGroup ?? hoveredGroup;
  const bookmarkedGroups = new Set(
    bookmarks
      .filter((bookmark) => bookmark.chapter_id === currentChapter?.id)
      .map((bookmark) => bookmark.group_index),
  );
  const groupIsOpen = (index: number) =>
    manualClosedGroups.has(index)
      ? false
      : manualOpenGroups.has(index) || expandAll;
  const totalGroups = section?.groups?.length || 0;
  const progressPercent =
    totalGroups > 0 ? Math.round(((activeGroup + 1) / totalGroups) * 100) : 0;

  const renderGroups = (pane: "combined" | "english" | "chinese") => {
    if (!section) return null;
    return (
      <>
        {pane !== "chinese" && section.en_title && (
          <h2 className="mb-4 text-xl font-bold">{section.en_title}</h2>
        )}
        {section.groups.map((group, gi) => (
          <BilingualGroup
            key={`${pane}-${gi}`}
            group={group}
            index={gi}
            mode={readerMode}
            pane={pane}
            open={groupIsOpen(gi)}
            active={activeGroup === gi}
            isBookmarked={bookmarkedGroups.has(gi)}
            fontSize={fontSize}
            fontFamily={fontFamily}
            peekVisible={readerMode === "hover" && peekGroup === gi}
            isFlagged={flaggedGroups.has(gi)}
            onSelect={() => {
              setActiveGroup(gi);
              visibleGroupRef.current = gi;
            }}
            onToggle={() => toggleTranslation(gi)}
            onFlag={() => setFlagTarget(gi)}
            onPointerEnter={() => setHoveredGroup(gi)}
            onPointerLeave={() =>
              setHoveredGroup((current) => (current === gi ? null : current))
            }
            onPeekToggle={() =>
              setPinnedHoverGroup((current) => (current === gi ? null : gi))
            }
          />
        ))}
        {section.groups.length === 0 && (
          <p className="py-8 text-center text-[var(--muted-foreground)]">
            {t("No aligned content in this chapter.")}
          </p>
        )}
      </>
    );
  };

  return (
    <div
      className="flex h-full flex-col transition-colors duration-200"
      style={THEME_STYLES[theme]}
    >
      <div className="h-1 w-full overflow-hidden bg-[var(--border)]/40">
        <div
          className="h-full bg-[var(--primary)] transition-all duration-300"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Toolbar */}
      <div className="flex min-w-0 items-center gap-2 overflow-x-auto border-b border-[var(--border)] px-4 py-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{pairing.en_title}</span>
          <span className="truncate text-xs text-[var(--muted-foreground)]">
            {currentChapter?.en_title || currentChapter?.id} · {chapterIndex + 1}/{chapters.length}
            {totalGroups > 0 ? ` · ${activeGroup + 1}/${totalGroups} (${progressPercent}%)` : ""}
            {currentChapterCompleted ? ` · ${t("Chapter translated")}` : ""}
            {annotations.length > 0 && ` · ${annotations.length} ${t("flagged")}`}
          </span>
        </div>
        <button
          onClick={() => void handleNavigateHistory("back")}
          disabled={!navigation?.can_back}
          className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
          title={t("Back")}
        >
          <ArrowLeft size={16} />
        </button>
        <button
          onClick={() => void handleNavigateHistory("forward")}
          disabled={!navigation?.can_forward}
          className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
          title={t("Forward")}
        >
          <ArrowRight size={16} />
        </button>
        <button
          onClick={() => void handleAddBookmark()}
          className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          title={t("Bookmark this position")}
        >
          <BookmarkPlus size={16} />
        </button>
        <button
          onClick={() => setShowBookmarks((value) => !value)}
          className={`rounded-md p-1.5 hover:bg-[var(--muted)] ${
            showBookmarks
              ? "text-[var(--primary)]"
              : "text-[var(--muted-foreground)]"
          }`}
          title={t("Bookmarks")}
        >
          <Bookmark size={16} />
        </button>
        <button
          onClick={() => setShowTaskBoard((value) => !value)}
          className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          title={t("Translate this chapter")}
        >
          <ListChecks size={16} />
        </button>
        {readerMode === "inline" && (
          <button
            type="button"
            onClick={() => setExpandAll((v) => !v)}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            title={expandAll ? t("Collapse all") : t("Expand all")}
          >
            {expandAll ? <ChevronsDownUp size={15} /> : <ChevronsUpDown size={15} />}
          </button>
        )}
        {annotations.length > 0 && (
          <button
            onClick={() => setShowReview(true)}
            className="flex items-center gap-1 rounded-lg bg-amber-500/10 px-2 py-1.5 text-xs font-medium text-amber-600 hover:bg-amber-500/20"
            title={t("Review flagged issues")}
          >
            <ClipboardList size={14} />
            {annotations.length}
          </button>
        )}
        <button
          type="button"
          onClick={() => setShowExportDialog(true)}
          className="flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
        >
          <Download size={14} />
          <span className="hidden sm:inline">{t("Export EPUB")}</span>
        </button>
      </div>

      {/* Chapter navigation */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-1.5">
        <div
          data-reader-control
          className="flex shrink-0 items-center gap-1 rounded-lg bg-[var(--muted)] p-0.5"
          role="group"
          aria-label={t("Reader mode")}
        >
          {([
            { value: "inline", icon: ChevronsUpDown, label: t("Inline") },
            { value: "dual", icon: Columns2, label: t("Dual pane") },
            { value: "hover", icon: Eye, label: t("Hover peek") },
          ] as const).map(({ value, icon: Icon, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setPreferredReaderMode(value)}
              disabled={value === "dual" && !dualPaneSupported}
              aria-pressed={readerMode === value}
              title={label}
              className={`flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-xs transition disabled:opacity-40 ${
                readerMode === value
                  ? "bg-[var(--card)] font-semibold text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              <Icon size={14} />
              <span className="ml-1 hidden lg:inline">{label}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          data-reader-control
          onClick={() => setClickLookupEnabled((value) => !value)}
          aria-pressed={clickLookupEnabled}
          title={t("Tap-to-lookup mode")}
          className={`flex h-8 shrink-0 items-center gap-1 rounded-lg border px-2 text-xs transition ${
            clickLookupEnabled
              ? "border-[var(--primary)]/50 bg-[var(--primary)]/10 text-[var(--primary)]"
              : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          }`}
        >
          <MousePointerClick size={14} />
          <span className="hidden md:inline">{t("Tap words")}</span>
        </button>
        <button
          type="button"
          data-reader-control
          onClick={() => setShowAppearanceModal(true)}
          title={t("Appearance & Typography")}
          aria-label={t("Appearance & Typography")}
          className="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-2 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <Type size={14} />
          <span className="hidden sm:inline">{t("Appearance")}</span>
        </button>
        <button
          onClick={() => loadChapter(chapterIndex - 1)}
          disabled={chapterIndex === 0}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronLeft size={18} />
        </button>
        <select
          value={chapterIndex}
          onChange={(e) => loadChapter(Number(e.target.value))}
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm"
        >
          {chapters.map((ch, i) => (
            <option key={ch.id} value={i}>
              {chapterTaskSummaries.find((item) => item.chapter_id === ch.id)?.completed ? "✓ " : ""}
              {ch.en_title || ch.id}
            </option>
          ))}
        </select>
        <button
          onClick={() => loadChapter(chapterIndex + 1)}
          disabled={chapterIndex >= chapters.length - 1}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronRight size={18} />
        </button>
        <button
          type="button"
          onClick={() => setShowShortcutsModal(true)}
          title={t("Keyboard Shortcuts")}
          aria-label={t("Keyboard Shortcuts")}
          className="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-2 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <Keyboard size={14} />
          <span className="hidden sm:inline">{t("J/K")}</span>
        </button>
      </div>

      {/* Content */}
      <div
        ref={contentRef}
        className="relative min-h-0 flex-1 pb-16"
        onMouseLeave={() => setHoveredGroup(null)}
      >
        {sectionLoading ? (
          <div className="flex h-full justify-center py-12">
            <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : section ? (
          readerMode === "dual" ? (
            <div className="grid h-full grid-cols-2 divide-x divide-[var(--border)] overflow-hidden">
              <div
                ref={englishPaneRef}
                aria-label={t("English pane")}
                className="relative h-full overflow-y-auto px-6 py-6"
              >
                <div className="mx-auto max-w-2xl space-y-4">{renderGroups("english")}</div>
              </div>
              <div
                ref={chinesePaneRef}
                aria-label={t("Chinese pane")}
                className="relative h-full overflow-y-auto bg-[var(--muted)]/20 px-6 py-6"
              >
                <div className="mx-auto max-w-2xl space-y-4">{renderGroups("chinese")}</div>
              </div>
            </div>
          ) : (
            <div ref={inlinePaneRef} className="h-full overflow-y-auto px-4 py-6">
              <div className="mx-auto max-w-2xl space-y-2">{renderGroups("combined")}</div>
            </div>
          )
        ) : (
          <div ref={inlinePaneRef} className="h-full overflow-y-auto px-4 py-6">
            <p className="py-8 text-center text-[var(--muted-foreground)]">
              {t("Failed to load this chapter.")}
            </p>
          </div>
        )}

        {dictPopover?.presentation === "mini" && (
          <MiniDictionaryTooltip
            word={dictPopover.word}
            anchor={dictPopover.anchor}
            loading={dictLoading}
            result={dictResult}
            error={dictError}
            onOpenFull={handleOpenFullDictionary}
            onPronounce={handlePronounce}
            onClose={closeDictionary}
          />
        )}
        {dictPopover?.presentation === "full" && (
          <DictionaryPanel
            word={dictPopover.word}
            anchor={dictPopover.anchor}
            loading={dictLoading}
            result={dictResult}
            error={dictError}
            initialMode={dictPopover.initialMode}
            onLookup={handleDictLookupClick}
            onTranslate={handleTranslateSelection}
            onClose={closeDictionary}
            saveBusy={savingWord}
            onSaveToVocabulary={() => void handleSaveVocabulary()}
            onPronounce={
              dictPopover.initialMode === "dictionary" ? handlePronounce : undefined
            }
          />
        )}
      </div>

      {/* Floating action bar for touch readers */}
      <div
        className="fixed left-1/2 z-40 -translate-x-1/2 select-none"
        style={{
          bottom: "max(12px, env(safe-area-inset-bottom, 12px))",
          touchAction: "manipulation",
        }}
        data-reader-control
      >
        <div className="flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--background)]/92 px-3 py-1.5 shadow-2xl backdrop-blur-lg">
          <button
            type="button"
            onClick={() => moveGroup(-1)}
            disabled={activeGroup <= 0}
            title={`${t("Previous paragraph")} (K / ↑)`}
            aria-label={t("Previous paragraph")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <ChevronUp size={18} />
          </button>
          <button
            type="button"
            onClick={() => moveGroup(1)}
            disabled={!section?.groups?.length || activeGroup >= section.groups.length - 1}
            title={`${t("Next paragraph")} (J / ↓)`}
            aria-label={t("Next paragraph")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <ChevronDown size={18} />
          </button>
          <div className="mx-0.5 h-4 w-[1px] bg-[var(--border)]" />
          <button
            type="button"
            onClick={() => toggleTranslation()}
            title={`${t("Toggle paragraph translation")} (T)`}
            aria-label={t("Toggle paragraph translation")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              groupIsOpen(activeGroup)
                ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Languages size={17} />
          </button>
          <button
            type="button"
            onClick={lookupFromKeyboard}
            title={`${t("Dictionary lookup")} (D)`}
            aria-label={t("Dictionary lookup")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <BookOpen size={17} />
          </button>
          <button
            type="button"
            onClick={() => void handleAddBookmark()}
            title={`${t("Bookmark this position")} (B)`}
            aria-label={t("Bookmark this position")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              bookmarkedGroups.has(activeGroup)
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Bookmark
              size={17}
              className={bookmarkedGroups.has(activeGroup) ? "fill-[var(--primary)]" : ""}
            />
          </button>
          <button
            type="button"
            onClick={() => handlePronounce("en-US")}
            title={`${t("Play US pronunciation (P)")} (P)`}
            aria-label={t("Play US pronunciation (P)")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              audioState.isPlaying
                ? "animate-pulse bg-[var(--primary)]/20 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {audioState.isPlaying ? <AudioLines size={17} /> : <Volume2 size={17} />}
          </button>
          <button
            type="button"
            onClick={() => setShowAppearanceModal(true)}
            title={t("Appearance & Typography")}
            aria-label={t("Appearance & Typography")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              showAppearanceModal
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Type size={16} />
          </button>
          <div className="mx-0.5 hidden h-4 w-[1px] bg-[var(--border)] sm:block" />
          <button
            type="button"
            onClick={() => setShowShortcutsModal(true)}
            title={t("Keyboard Shortcuts")}
            aria-label={t("Keyboard Shortcuts")}
            className={`hidden h-9 w-9 items-center justify-center rounded-full transition sm:flex ${
              showShortcutsModal
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Keyboard size={16} />
          </button>
        </div>
      </div>

      {/* Flag dialog */}
      {flagTarget !== null && (
        <FlagDialog
          groupIndex={flagTarget}
          onClose={() => setFlagTarget(null)}
          onSubmit={(issueType, note) => handleFlag(flagTarget, issueType, note)}
        />
      )}

      {/* Review panel */}
      {showReview && (
        <ReviewPanel
          annotations={annotations}
          onClose={() => setShowReview(false)}
          onResolve={handleResolveAnnotation}
          pairingId={pairingId}
        />
      )}
      {showBookmarks && (
        <BookmarkPanel
          bookmarks={bookmarks}
          onClose={() => setShowBookmarks(false)}
          onJump={handleJumpBookmark}
          onRename={handleRenameBookmark}
          onDelete={handleDeleteBookmark}
        />
      )}
      {showExportDialog && (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-black/40 p-4"
          onClick={() => !exporting && setShowExportDialog(false)}
        >
          <div
            className="flex max-h-[85vh] w-full max-w-[520px] flex-col overflow-hidden rounded-xl bg-[var(--background)] shadow-2xl"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={t("Export EPUB")}
          >
            <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Download size={16} />
                {t("Export EPUB")}
              </h3>
              <button
                type="button"
                onClick={() => !exporting && setShowExportDialog(false)}
                disabled={exporting}
                className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <div className="space-y-2">
                <span className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Layout")}
                </span>
                <div
                  className="grid grid-cols-3 gap-1 rounded-lg bg-[var(--muted)] p-1"
                  role="group"
                  aria-label={t("Layout")}
                >
                  {([
                    { value: "folded", label: t("Folded") },
                    { value: "alternating", label: t("Alternating") },
                    { value: "two_column", label: t("Two columns") },
                  ] as const).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setExportStyle(option.value)}
                      disabled={exporting}
                      aria-pressed={exportStyle === option.value}
                      className={`h-9 rounded-md px-2 text-xs transition disabled:opacity-50 ${
                        exportStyle === option.value
                          ? "bg-[var(--background)] font-semibold text-[var(--foreground)] shadow-sm"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="bilingual-export-font"
                  className="text-xs font-medium text-[var(--muted-foreground)]"
                >
                  {t("Font family")}
                </label>
                <input
                  id="bilingual-export-font"
                  value={exportFontFamily}
                  onChange={(event) => setExportFontFamily(event.target.value)}
                  maxLength={300}
                  disabled={exporting}
                  className="h-10 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                />
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="bilingual-export-css"
                  className="text-xs font-medium text-[var(--muted-foreground)]"
                >
                  {t("Custom CSS")}
                </label>
                <textarea
                  id="bilingual-export-css"
                  value={exportCss}
                  onChange={(event) => setExportCss(event.target.value)}
                  maxLength={100000}
                  disabled={exporting}
                  spellCheck={false}
                  rows={6}
                  className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-xs leading-5"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
              <button
                type="button"
                onClick={() => setShowExportDialog(false)}
                disabled={exporting}
                className="rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
              >
                {t("Cancel")}
              </button>
              <button
                type="button"
                onClick={() => void handleExport()}
                disabled={exporting}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
              >
                {exporting ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Download size={15} />
                )}
                {exporting ? t("Exporting...") : t("Download EPUB")}
              </button>
            </div>
          </div>
        </div>
      )}
      {showAppearanceModal && (
        <div
          className="fixed inset-0 z-[130] flex items-end justify-center bg-black/40 p-4 sm:items-center"
          onClick={() => setShowAppearanceModal(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Type size={16} className="text-[var(--primary)]" />
                {t("Appearance & Typography")}
              </h3>
              <button
                type="button"
                onClick={() => setShowAppearanceModal(false)}
                aria-label={t("Close")}
                className="rounded p-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-4 text-sm">
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Reading Theme")}
                </label>
                <div className="mt-2 grid grid-cols-4 gap-2">
                  {[
                    {
                      key: "system",
                      label: t("System"),
                      bg: "bg-gradient-to-tr from-zinc-800 to-zinc-200",
                    },
                    {
                      key: "sepia",
                      label: t("Sepia (Warm)"),
                      bg: "border border-[#dfd3be] bg-[#f8f1e3]",
                    },
                    {
                      key: "dark",
                      label: t("Zinc Dark"),
                      bg: "border border-[#3f3f46] bg-[#18181b]",
                    },
                    {
                      key: "oled",
                      label: t("OLED Black"),
                      bg: "border border-zinc-800 bg-black",
                    },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setTheme(item.key as BilingualTheme)}
                      aria-pressed={theme === item.key}
                      className={`flex flex-col items-center gap-1.5 rounded-lg border p-2 text-xs transition ${
                        theme === item.key
                          ? "border-[var(--primary)] font-medium ring-2 ring-[var(--primary)]/30"
                          : "border-[var(--border)] hover:bg-[var(--muted)]"
                      }`}
                    >
                      <div className={`h-6 w-full rounded-md shadow-sm ${item.bg}`} />
                      <span className="w-full truncate text-center text-[11px]">
                        {item.label}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Font Size")}
                </label>
                <div className="mt-2 flex items-center justify-between gap-1 rounded-lg bg-[var(--muted)]/50 p-1">
                  {(["sm", "base", "lg", "xl", "2xl"] as const).map((size, index) => (
                    <button
                      key={size}
                      type="button"
                      onClick={() => setFontSize(size)}
                      aria-pressed={fontSize === size}
                      className={`flex-1 rounded-md py-1.5 text-xs transition ${
                        fontSize === size
                          ? "bg-[var(--background)] font-semibold text-[var(--foreground)] shadow-sm"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {index === 0 ? "A-" : index === 4 ? "A++" : `A${"+".repeat(index - 1)}`}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Font Family")}
                </label>
                <div className="mt-2 flex gap-2">
                  {[
                    { key: "sans", label: t("Modern Sans"), fontClass: "font-sans" },
                    { key: "serif", label: t("Literary Serif"), fontClass: "font-serif" },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setFontFamily(item.key as BilingualFontFamily)}
                      aria-pressed={fontFamily === item.key}
                      className={`flex-1 rounded-lg border py-2 text-xs transition ${item.fontClass} ${
                        fontFamily === item.key
                          ? "border-[var(--primary)] bg-[var(--primary)]/10 font-medium text-[var(--primary)]"
                          : "border-[var(--border)] hover:bg-[var(--muted)]"
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      {showShortcutsModal && (
        <div
          className="fixed inset-0 z-[130] flex items-center justify-center bg-black/40 p-4"
          onClick={() => setShowShortcutsModal(false)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--background)] p-6 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between border-b border-[var(--border)] pb-3">
              <h3 className="flex items-center gap-2 text-base font-semibold">
                <Keyboard size={18} className="text-[var(--primary)]" />
                {t("Keyboard Shortcuts")}
              </h3>
              <button
                type="button"
                onClick={() => setShowShortcutsModal(false)}
                aria-label={t("Close shortcuts")}
                className="rounded p-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <p className="text-xs text-[var(--muted-foreground)]">
                {t("Continuous Reading Flow")}
              </p>
              <div className="grid gap-2">
                {[
                  { key: "J / ↓", desc: t("Next paragraph") },
                  { key: "K / ↑", desc: t("Previous paragraph") },
                  { key: "T", desc: t("Toggle paragraph translation") },
                  { key: "D", desc: t("Dictionary lookup") },
                  { key: "B", desc: t("Bookmark this position") },
                  { key: "P", desc: t("Play US pronunciation") },
                  { key: "Shift + P", desc: t("Play UK pronunciation") },
                  { key: "? / H", desc: t("Keyboard Shortcuts") },
                  { key: "Esc", desc: t("Close") },
                ].map((item) => (
                  <div
                    key={item.key}
                    className="flex items-center justify-between rounded-lg bg-[var(--muted)]/40 px-3 py-2 text-xs"
                  >
                    <span className="text-[var(--foreground)]">{item.desc}</span>
                    <kbd className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 font-mono font-semibold text-[var(--foreground)]">
                      {item.key}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      {showTaskBoard && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4">
          <div className="flex h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-[var(--background)] shadow-2xl">
            <TranslationTaskBoardPanel
              sourceType="bilingual"
              sourceId={pairingId}
              chapterId={currentChapter?.id}
              onBoardLoaded={handleTaskBoardChange}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function BookmarkPanel({
  bookmarks,
  onClose,
  onJump,
  onRename,
  onDelete,
}: {
  bookmarks: BilingualBookmark[];
  onClose: () => void;
  onJump: (bookmark: BilingualBookmark) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const commitRename = (bookmarkId: string) => {
    if (editingId !== bookmarkId) return;
    const title = draftTitle.trim();
    setEditingId(null);
    if (title) onRename(bookmarkId, title);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-full max-w-[560px] flex-col rounded-xl bg-[var(--background)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Bookmark size={16} />
            {t("Bookmarks")} ({bookmarks.length})
          </h3>
          <button
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {bookmarks.length === 0 ? (
            <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">
              {t("No bookmarks yet.")}
            </p>
          ) : (
            <div className="space-y-3">
              {bookmarks.map((bookmark) => (
                <div key={bookmark.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
                  {editingId === bookmark.id ? (
                    <input
                      autoFocus
                      value={draftTitle}
                      onChange={(event) => setDraftTitle(event.target.value)}
                      onBlur={() => commitRename(bookmark.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") commitRename(bookmark.id);
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      className="mb-2 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm"
                    />
                  ) : (
                    <div className="flex items-start justify-between gap-2">
                      <button
                        onClick={() => onJump(bookmark)}
                        className="min-w-0 flex-1 text-left"
                        title={t("Jump to bookmark")}
                      >
                        <span className="block truncate text-sm font-medium">{bookmark.title}</span>
                        <span className="block truncate text-xs text-[var(--muted-foreground)]">
                          {bookmark.chapter_title} · #{bookmark.group_index + 1} · {Math.round(bookmark.scroll_percent)}%
                        </span>
                      </button>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          onClick={() => {
                            setEditingId(bookmark.id);
                            setDraftTitle(bookmark.title);
                          }}
                          aria-label={t("Rename bookmark")}
                          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => onDelete(bookmark.id)}
                          aria-label={t("Delete bookmark")}
                          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-red-600"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  )}
                  {bookmark.preview && (
                    <p className="mt-2 line-clamp-2 text-xs text-[var(--muted-foreground)]">{bookmark.preview}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function BilingualGroup({
  group,
  index,
  mode,
  pane,
  open,
  active,
  isBookmarked,
  fontSize,
  fontFamily,
  peekVisible,
  isFlagged,
  onSelect,
  onToggle,
  onFlag,
  onPointerEnter,
  onPointerLeave,
  onPeekToggle,
}: {
  group: import("@/lib/immersive-reading-api").BilingualAlignGroup;
  index: number;
  mode: BilingualReaderMode;
  pane: "combined" | "english" | "chinese";
  open: boolean;
  active: boolean;
  isBookmarked: boolean;
  fontSize: BilingualFontSize;
  fontFamily: BilingualFontFamily;
  peekVisible: boolean;
  isFlagged: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onFlag: () => void;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onPeekToggle: () => void;
}) {
  const { t } = useTranslation();
  const activeClass = active
    ? "outline-[var(--primary)]/50"
    : "outline-transparent hover:outline-[var(--muted)]";
  const fontClass = fontFamily === "serif" ? "font-serif" : "font-sans";
  const sizeStyles = FONT_SIZE_STYLES[fontSize];
  const chineseFont = {
    fontFamily:
      fontFamily === "serif"
        ? '"Songti SC","Noto Serif CJK SC","PingFang TC","Heiti TC",serif'
        : '"PingFang SC","Microsoft YaHei","Heiti SC",sans-serif',
  };

  if (pane === "chinese") {
    return (
      <div
        className={`group/para relative cursor-pointer rounded-lg px-3.5 py-2.5 outline-2 outline-offset-4 transition ${activeClass}`}
        data-group-index={index}
        data-active={active || undefined}
        onClick={onSelect}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
      >
        {isBookmarked && (
          <span
            className="absolute right-2 top-2 text-[var(--primary)]"
            title={t("Bookmarked")}
          >
            <Bookmark size={13} className="fill-current" />
          </span>
        )}
        {group.zh.length > 0 ? (
          group.zh.map((para, pi) => (
            <p
              key={pi}
              className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`}
              style={chineseFont}
            >
              {para}
            </p>
          ))
        ) : (
          <p className="text-sm text-[var(--muted-foreground)]">
            {t("No Chinese translation")}
          </p>
        )}
      </div>
    );
  }

  if (pane === "english") {
    return (
      <div
        className={`group/para relative cursor-pointer rounded-lg px-3.5 py-2.5 outline-2 outline-offset-4 transition ${activeClass}`}
        data-group-index={index}
        data-active={active || undefined}
        onClick={onSelect}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
      >
        {isBookmarked && (
          <span
            className="absolute right-6 top-2 text-[var(--primary)]"
            title={t("Bookmarked")}
          >
            <Bookmark size={13} className="fill-current" />
          </span>
        )}
        {group.en.map((para, pi) => (
          <p
            key={pi}
            className={`select-text ${fontClass} ${sizeStyles.en} text-[var(--foreground)]`}
          >
            {para}
          </p>
        ))}
        {group.low_confidence && group.shape !== "1:1" && (
          <span className="text-xs text-[var(--muted-foreground)]">({group.shape})</span>
        )}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onFlag();
          }}
          className="absolute right-1 top-1 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] focus-visible:opacity-100 group-hover/para:opacity-100"
          title={t("Flag issue")}
          aria-label={t("Flag issue")}
        >
          <Flag size={14} className={isFlagged ? "fill-amber-400 text-amber-500" : ""} />
        </button>
      </div>
    );
  }

  return (
    <div
      className={`group/para relative cursor-pointer space-y-1 rounded-lg px-3 py-2 outline-2 outline-offset-4 transition ${activeClass}`}
      data-group-index={index}
      data-active={active || undefined}
      onClick={onSelect}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      {isBookmarked && (
        <span
          className="absolute right-6 top-2 text-[var(--primary)]"
          title={t("Bookmarked")}
        >
          <Bookmark size={13} className="fill-current" />
        </span>
      )}
      {group.en.map((para, pi) => (
        <p
          key={pi}
          className={`select-text ${fontClass} ${sizeStyles.en} text-[var(--foreground)]`}
        >
          {para}
        </p>
      ))}

      {mode === "hover" ? (
        <>
          <button
            type="button"
            data-reader-control
            onClick={(event) => {
              event.stopPropagation();
              onPeekToggle();
            }}
            className="absolute right-0 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-100 transition hover:bg-[var(--muted)] focus-visible:opacity-100 sm:opacity-0 sm:group-hover/para:opacity-100"
            title={t("Show translation")}
            aria-label={t("Show translation")}
            aria-expanded={peekVisible}
          >
            <Eye size={14} />
          </button>
          <div
            className={`absolute right-0 top-7 z-20 w-[min(24rem,calc(100%-0.5rem))] rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 shadow-xl transition-opacity duration-150 ${
              peekVisible
                ? "pointer-events-auto opacity-100"
                : "pointer-events-none opacity-0 group-hover/para:opacity-100"
            }`}
          >
            {group.zh.length > 0 ? (
              group.zh.map((para, pi) => (
                <p
                  key={pi}
                  className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`}
                  style={chineseFont}
                >
                  {para}
                </p>
              ))
            ) : (
              <p className="text-sm text-[var(--muted-foreground)]">
                {t("No Chinese translation")}
              </p>
            )}
          </div>
        </>
      ) : group.zh.length > 0 ? (
        <details
          open={open}
          onClick={(event) => event.stopPropagation()}
          onToggle={(event) => {
            if ((event.target as HTMLDetailsElement).open !== open) onToggle();
          }}
          className="bilingual-zh-details my-1.5 rounded-lg border-l-[3px] border-l-[var(--primary)] bg-[var(--muted)]/40 px-3.5 py-2.5"
        >
          <summary
            data-reader-control
            className="cursor-pointer select-none text-xs font-semibold text-[var(--primary)]"
          >
            {open ? t("Hide Chinese") : t("Show Chinese")}
          </summary>
          <div className="mt-2 space-y-1.5 pt-1">
            {group.zh.map((para, pi) => (
              <p
                key={pi}
                className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`}
                style={chineseFont}
              >
                {para}
              </p>
            ))}
          </div>
        </details>
      ) : null}

      {mode !== "hover" && group.low_confidence && group.shape !== "1:1" && (
        <span className="text-xs text-[var(--muted-foreground)]">({group.shape})</span>
      )}
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onFlag();
        }}
        className="absolute right-0 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] focus-visible:opacity-100 group-hover/para:opacity-100"
        title={t("Flag issue")}
        aria-label={t("Flag issue")}
      >
        <Flag size={14} className={isFlagged ? "fill-amber-400 text-amber-500" : ""} />
      </button>
    </div>
  );
}

const ISSUE_TYPES: { value: IssueType; labelKey: string }[] = [
  { value: "misalignment", labelKey: "Misaligned paragraphs" },
  { value: "wrong_chapter", labelKey: "Wrong chapter mapping" },
  { value: "missing_translation", labelKey: "Missing translation" },
  { value: "translation_error", labelKey: "Translation quality issue" },
  { value: "other", labelKey: "Other" },
];

function FlagDialog({
  groupIndex,
  onClose,
  onSubmit,
}: {
  groupIndex: number;
  onClose: () => void;
  onSubmit: (issueType: IssueType, note: string) => void;
}) {
  const { t } = useTranslation();
  const [issueType, setIssueType] = useState<IssueType>("misalignment");
  const [note, setNote] = useState("");

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[420px] rounded-xl bg-[var(--background)] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle size={16} className="text-amber-500" />
            {t("Flag alignment issue")} (#{groupIndex + 1})
          </h3>
          <button onClick={onClose} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Issue type")}</label>
            <select
              value={issueType}
              onChange={(e) => setIssueType(e.target.value as IssueType)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
            >
              {ISSUE_TYPES.map((it) => (
                <option key={it.value} value={it.value}>
                  {t(it.labelKey)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Note (optional)")}</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("Describe what's wrong...")}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {t("Cancel")}
            </button>
            <button
              onClick={() => onSubmit(issueType, note)}
              className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-600"
            >
              {t("Flag")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewPanel({
  annotations,
  onClose,
  onResolve,
  pairingId,
}: {
  annotations: BilingualAnnotation[];
  onClose: () => void;
  onResolve: (id: string) => void;
  pairingId: string;
}) {
  const { t } = useTranslation();
  const [report, setReport] = useState("");
  const [copied, setCopied] = useState(false);

  const loadReport = useCallback(async () => {
    try {
      const data = await annotationApi.reviewReport(pairingId);
      setReport(data.report);
    } catch {
      // ignore
    }
  }, [pairingId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReport(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReport]);

  const handleCopy = () => {
    navigator.clipboard.writeText(report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[640px] flex-col rounded-xl bg-[var(--background)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ClipboardList size={16} />
            {t("Review Issues")} ({annotations.length})
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {copied ? t("Copied!") : t("Copy report for Codex")}
            </button>
            <button onClick={onClose} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {annotations.length === 0 ? (
            <p className="text-center text-sm text-[var(--muted-foreground)]">{t("No open issues.")}</p>
          ) : (
            <div className="space-y-3">
              {annotations.map((ann) => (
                <div
                  key={ann.id}
                  className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3"
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-xs font-medium text-amber-600">
                      <Flag size={12} className="fill-amber-400" />
                      {t(ISSUE_TYPES.find((it) => it.value === ann.issue_type)?.labelKey || ann.issue_type)}
                    </span>
                    <button
                      onClick={() => onResolve(ann.id)}
                      className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    >
                      {t("Resolve")}
                    </button>
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {ann.chapter_title} · #{ann.group_index + 1} · {ann.shape}
                  </p>
                  {ann.note && (
                    <p className="mt-1 text-sm italic text-[var(--foreground)]">&ldquo;{ann.note}&rdquo;</p>
                  )}
                  <div className="mt-2 space-y-1">
                    <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {t("EN")}: {ann.en_text}
                    </p>
                    <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {t("ZH")}: {ann.zh_text}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {report && (
          <div className="border-t border-[var(--border)] px-5 py-2">
            <p className="text-xs text-[var(--muted-foreground)]">
              {t("Copy the report above and paste it to Codex to generate alignment fixes.")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
