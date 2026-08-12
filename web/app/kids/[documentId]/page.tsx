"use client";

import { EpubView } from "react-reader";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  kidsApi,
  type KidsSafeQuestion,
  type KidsQuizGrade,
} from "@/lib/kids-api";

type Rendition = any;
type NavItem = any;

const EPUB_URL = (documentId: string) =>
  `/api/v1/kids/books/${encodeURIComponent(documentId)}/epub`;

const FONT_MIN = 80;
const FONT_MAX = 220;
const FONT_STEP = 20;

export default function KidsReaderPage() {
  const router = useRouter();
  const params = useParams();
  const documentId = params.documentId as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bookTitle, setBookTitle] = useState("");
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [showQuiz, setShowQuiz] = useState(false);
  const [questions, setQuestions] = useState<KidsSafeQuestion[]>([]);
  const [quizLoading, setQuizLoading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [grade, setGrade] = useState<KidsQuizGrade | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  // Text-selection state
  const [selectedText, setSelectedText] = useState("");
  const [showSelectionBar, setShowSelectionBar] = useState(false);

  // Translate popup
  const [translateText, setTranslateText] = useState<string | null>(null);
  const [translateResult, setTranslateResult] = useState("");
  const [translating, setTranslating] = useState(false);

  const [stars, setStars] = useState(0);

  // Extra controls
  const [fontSize, setFontSize] = useState(120);
  const [nightMode, setNightMode] = useState(false);
  const [showTocPanel, setShowTocPanel] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  // Exit protection
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");
  const [profileHasPin, setProfileHasPin] = useState(false);
  const [profileId, setProfileId] = useState("");

  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const currentHrefRef = useRef<string>("");
  const selectedCfiRef = useRef<string>("");
  const fontSizeRef = useRef(120);

  useEffect(() => { fontSizeRef.current = fontSize; }, [fontSize]);

  // Load book data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await kidsApi.getBook(documentId);
        if (cancelled) return;
        const doc = data.document as Record<string, any>;
        setBookTitle(doc.title || "Book");
        setStars(data.progress?.total_stars || 0);
        if (data.progress?.epub_cfi) setLocation(data.progress.epub_cfi);
      } catch {
        if (!cancelled) {
          setBookTitle("Book");
          setError("Could not load this book. Please go back and try again.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [documentId]);

  // Check if the current profile has a PIN
  useEffect(() => {
    const pid = localStorage.getItem("dt_kids_profile_id") || "";
    setProfileId(pid);
    if (!pid) return;
    kidsApi.bootstrap().then(({ profiles }) => {
      const p = profiles.find((x) => x.id === pid);
      if (p) setProfileHasPin(!!p.has_pin);
    }).catch(() => {});
  }, []);

  const handleExitClick = () => {
    if (profileHasPin) {
      setShowExitPin(true);
      setExitPin("");
      setExitPinError("");
    } else {
      router.push("/kids");
    }
  };

  const handleExitPinSubmit = async () => {
    try {
      await kidsApi.exitVerify(profileId, exitPin);
      router.push("/kids");
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  const saveProgress = useCallback(
    (loc: string, href: string) => {
      kidsApi.updateProgress(documentId, {
        section_id: href,
        section_index: 0,
        scroll_percent: 0,
        epub_cfi: loc,
        section_href: href,
        time_delta: 0,
      }).catch(() => {});
    },
    [documentId],
  );

  const stopSpeaking = useCallback(() => {
    if (utteranceRef.current) {
      window.speechSynthesis.cancel();
      utteranceRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const speakSelection = useCallback(async () => {
    stopSpeaking();
    let text = selectedText;
    // Try to get fresh text from rendition if we have a CFI range
    if (renditionRef.current && selectedCfiRef.current) {
      try {
        const range = renditionRef.current.getRange(selectedCfiRef.current);
        if (range) {
          const rangeText = range.toString();
          if (rangeText.trim()) text = rangeText;
        }
      } catch { /* fall back to stored text */ }
    }
    if (!text || !text.trim()) {
      setShowHelp(true);
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.85;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    utteranceRef.current = u;
    window.speechSynthesis.speak(u);
    setSpeaking(true);
    setShowSelectionBar(false);
  }, [stopSpeaking, selectedText]);

  const handleTranslate = useCallback(async (text: string) => {
    setTranslateText(text);
    setTranslating(true);
    setTranslateResult("");
    try {
      const { translation } = await kidsApi.translate(text);
      setTranslateResult(translation);
    } catch {
      setTranslateResult("Translation unavailable");
    } finally {
      setTranslating(false);
    }
  }, []);

  // ── Page navigation ──────────────────────────────────
  const goNextPage = useCallback(() => { renditionRef.current?.next(); }, []);
  const goPrevPage = useCallback(() => { renditionRef.current?.prev(); }, []);

  // ── Font size ────────────────────────────────────────
  const increaseFont = useCallback(() => {
    setFontSize((s) => {
      const next = Math.min(s + FONT_STEP, FONT_MAX);
      renditionRef.current?.themes?.fontSize(`${next}%`);
      return next;
    });
  }, []);
  const decreaseFont = useCallback(() => {
    setFontSize((s) => {
      const next = Math.max(s - FONT_STEP, FONT_MIN);
      renditionRef.current?.themes?.fontSize(`${next}%`);
      return next;
    });
  }, []);

  // ── Night mode ───────────────────────────────────────
  const toggleNightMode = useCallback(() => {
    setNightMode((prev) => {
      const next = !prev;
      if (next) {
        renditionRef.current?.themes?.override("color", "#e0e0e0");
        renditionRef.current?.themes?.override("background", "#1a1a2e");
      } else {
        renditionRef.current?.themes?.override("color", "#2d2d2d");
        renditionRef.current?.themes?.override("background", "#ffffff");
      }
      return next;
    });
  }, []);

  // ── TOC navigation ───────────────────────────────────
  const goToTocItem = useCallback((href: string) => {
    renditionRef.current?.display(href);
    setShowTocPanel(false);
  }, []);

  // ── Quiz ─────────────────────────────────────────────
  const loadQuiz = useCallback(async () => {
    setShowQuiz(true);
    setGrade(null);
    setAnswers({});
    setQuizLoading(true);
    try {
      const sectionId = currentHrefRef.current || toc[0]?.href || "section-0";
      const { questions: qs } = await kidsApi.getQuiz(documentId, sectionId);
      setQuestions(qs);
    } catch {
      setQuestions([]);
    } finally {
      setQuizLoading(false);
    }
  }, [documentId, toc]);

  const submitQuiz = async () => {
    setSubmitting(true);
    try {
      const answerArr = questions.map((_, i) => answers[i] ?? -1);
      const result = await kidsApi.submitQuiz(
        documentId,
        currentHrefRef.current || toc[0]?.href || "section-0",
        answerArr,
      );
      setGrade(result);
      setStars((s) => s + result.stars);
    } catch {
      setGrade({
        score: 0, total: 0, stars: 0, per_question: [],
        encouragements: ["Quiz error. Try again!"],
      });
    } finally {
      setSubmitting(false);
    }
  };

  // ── Clear selection when clicking outside ────────────
  const clearSelection = () => {
    setShowSelectionBar(false);
    setSelectedText("");
    selectedCfiRef.current = "";
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e0f2ff" }}>
        <div style={{ fontSize: 24, color: "#667eea" }}>Opening your book...</div>
      </div>
    );
  }

  const pageBg = nightMode ? "#1a1a2e" : "#fef9f0";
  const headerBg = nightMode ? "#16213e" : "white";
  const headerColor = nightMode ? "#e0e0e0" : "#4a3f6b";
  const btnBg = nightMode ? "#0f3460" : "#edf2f7";
  const btnColor = nightMode ? "#e0e0e0" : "#4a5568";

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: pageBg }}>
      {/* Exit PIN modal */}
      {showExitPin && (
        <div style={popupOverlay}>
          <div style={{ ...popupBox, maxWidth: 360 }}>
            <p style={{ fontSize: 18, color: "#7c6f9b", textAlign: "center" }}>Enter PIN to exit</p>
            <input
              type="password"
              value={exitPin}
              onChange={(e) => setExitPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && exitPin.length >= 4 && handleExitPinSubmit()}
              maxLength={8}
              style={{
                fontSize: 32, textAlign: "center", letterSpacing: 12,
                border: "3px solid #667eea", borderRadius: 12, padding: "12px 16px",
                width: "100%", outline: "none", margin: "12px 0",
              }}
              placeholder="----"
              autoFocus
            />
            {exitPinError && <p style={{ fontSize: 16, color: "#e53e3e", textAlign: "center" }}>{exitPinError}</p>}
            <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 16 }}>
              <button style={cancelBtn} onClick={() => { setShowExitPin(false); setExitPin(""); setExitPinError(""); }}>
                Cancel
              </button>
              <button style={{ ...confirmBtn, opacity: exitPin.length < 4 ? 0.5 : 1 }} onClick={handleExitPinSubmit} disabled={exitPin.length < 4}>
                Exit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "8px 12px", background: headerBg,
        boxShadow: "0 2px 6px rgba(0,0,0,0.06)", zIndex: 10, flexShrink: 0,
      }}>
        <button onClick={handleExitClick} style={{ ...toolbarBtn, color: headerColor }}>
          {"< Books"}
        </button>
        <div style={{
          flex: 1, textAlign: "center", fontWeight: 700, fontSize: 16,
          color: headerColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {bookTitle}
        </div>
        <div style={{ fontSize: 18, color: headerColor }}>
          {stars > 0 ? `${"\u2605".repeat(Math.min(stars, 5))}` : "\u2606"}
        </div>
        <button onClick={() => setShowTocPanel(true)} style={{ ...toolbarBtn, color: headerColor, fontSize: 20 }} title="Chapters">
          {"\u2630"}
        </button>
      </div>

      {/* TOC panel */}
      {showTocPanel && (
        <div style={popupOverlay} onClick={() => setShowTocPanel(false)}>
          <div style={{ ...popupBox, maxWidth: 400 }} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: "#4a3f6b", marginBottom: 16 }}>Chapters</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {toc.map((item: NavItem, i: number) => (
                <button
                  key={i}
                  onClick={() => goToTocItem(item.href)}
                  style={{
                    padding: "12px 16px", borderRadius: 10, border: "none",
                    background: currentHrefRef.current === item.href ? "#e9d8fd" : "#f7fafc",
                    fontSize: 16, cursor: "pointer", textAlign: "left", color: "#2d3748",
                  }}
                >
                  {item.label}
                </button>
              ))}
              {toc.length === 0 && <p style={{ color: "#999", textAlign: "center" }}>No chapters found.</p>}
            </div>
            <button style={{ ...bigBtn, marginTop: 16, width: "100%", background: "#e2e8f0" }} onClick={() => setShowTocPanel(false)}>
              Close
            </button>
          </div>
        </div>
      )}

      {/* Help popup */}
      {showHelp && (
        <div style={popupOverlay} onClick={() => setShowHelp(false)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: "#4a3f6b", marginBottom: 12 }}>How to Read</h2>
            <div style={{ fontSize: 16, color: "#4a5568", lineHeight: 2 }}>
              <p><b>Turn pages:</b> Tap the big &lt; or &gt; arrows, or swipe left/right on the book.</p>
              <p><b>Read Aloud:</b> Tap and hold on text to select it. A small menu pops up. Tap "Read Aloud".</p>
              <p><b>Translate:</b> Select text, then tap "Translate" to see Chinese.</p>
              <p><b>Quiz:</b> Tap "Quiz" for fun questions about this page.</p>
              <p><b>Chapters:</b> Tap the menu icon in the top-right corner.</p>
              <p><b>Font Size:</b> Use "A+" for bigger, "A-" for smaller text.</p>
              <p><b>Night Mode:</b> Tap the moon/sun button to switch colors.</p>
            </div>
            <button style={{ ...bigBtn, marginTop: 16, width: "100%", background: "#667eea", color: "white" }} onClick={() => setShowHelp(false)}>
              Got it!
            </button>
          </div>
        </div>
      )}

      {/* Floating selection toolbar */}
      {showSelectionBar && selectedText && (
        <div style={{
          position: "fixed", bottom: 88, left: "50%", transform: "translateX(-50%)",
          display: "flex", gap: 8, alignItems: "center",
          background: "white", borderRadius: 16, padding: "8px 12px",
          boxShadow: "0 4px 16px rgba(0,0,0,0.2)", zIndex: 200, maxWidth: "90vw",
        }}>
          <span style={{
            fontSize: 13, color: "#999", maxWidth: 120,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {selectedText.slice(0, 30)}
          </span>
          <button style={{ ...selBtn, background: "#e9d8fd" }} onClick={speakSelection}>
            {speaking ? "Stop" : "Read Aloud"}
          </button>
          <button style={{ ...selBtn, background: "#bee3f8" }} onClick={() => handleTranslate(selectedText)}>
            Translate
          </button>
          <button style={{ ...selBtn, background: "#e2e8f0" }} onClick={clearSelection}>x</button>
        </div>
      )}

      {/* Reader area */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {error ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 16 }}>
            <p style={{ fontSize: 20, color: "#e53e3e", textAlign: "center", padding: "0 20px" }}>{error}</p>
            <button style={{ ...bigBtn, background: "#667eea", color: "white" }} onClick={() => router.push("/kids")}>
              Back to Library
            </button>
          </div>
        ) : (
          <>
            {/* Tap zones for page turning (left/right 15% of width) */}
            <button
              aria-label="Previous page"
              onClick={goPrevPage}
              style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "15%", background: "transparent", border: "none", cursor: "pointer", zIndex: 5, opacity: 0 }}
            />
            <button
              aria-label="Next page"
              onClick={goNextPage}
              style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: "15%", background: "transparent", border: "none", cursor: "pointer", zIndex: 5, opacity: 0 }}
            />

            <EpubView
              url={EPUB_URL(documentId)}
              location={location ?? null}
              locationChanged={(loc: string) => {
                setLocation(loc);
                saveProgress(loc, currentHrefRef.current);
              }}
              tocChanged={(t: NavItem[]) => setToc(t)}
              epubInitOptions={{ openAs: "epub" }}
              epubOptions={{
                allowScriptedContent: false,
                flow: "paginated",
                spread: "none",
                manager: "default",
              }}
              getRendition={(rendition: Rendition) => {
                renditionRef.current = rendition;
                rendition.themes.fontSize(`${fontSizeRef.current}%`);

                // Capture text selection
                rendition.on("selected", (cfiRange: string, contents: any) => {
                  try {
                    const text = contents.window.getSelection().toString();
                    if (text && text.trim().length > 1) {
                      selectedCfiRef.current = cfiRange;
                      setSelectedText(text.trim());
                      setShowSelectionBar(true);
                      currentHrefRef.current = rendition.currentLocation()?.start?.href || "";
                    }
                  } catch { /* ignore */ }
                });

                rendition.on("relocated", (loc: any) => {
                  currentHrefRef.current = loc?.start?.href || "";
                });
              }}
            />
          </>
        )}
      </div>

      {/* Bottom toolbar */}
      <div style={{
        display: "flex", gap: 4, padding: "8px 8px",
        background: headerBg, boxShadow: "0 -2px 6px rgba(0,0,0,0.06)",
        justifyContent: "center", alignItems: "center", flexWrap: "wrap", flexShrink: 0,
      }}>
        {/* Prev page */}
        <button style={{ ...navBtn, background: btnBg, color: btnColor }} onClick={goPrevPage} title="Previous page">
          {"\u2039"}
        </button>
        {/* Read Aloud */}
        <button
          style={{ ...actionBtn, background: speaking ? "#fed7d7" : "#e9d8fd" }}
          onClick={speaking ? stopSpeaking : speakSelection}
          title="Select text first, then tap to hear it"
        >
          {speaking ? "Stop" : "Read Aloud"}
        </button>
        {/* Translate */}
        <button
          style={{ ...actionBtn, background: "#bee3f8" }}
          onClick={() => {
            if (selectedText) handleTranslate(selectedText);
            else setShowHelp(true);
          }}
          title="Select text first, then tap to translate"
        >
          Translate
        </button>
        {/* Quiz */}
        <button style={{ ...actionBtn, background: "#fed7aa" }} onClick={loadQuiz} title="Take a fun quiz">
          Quiz
        </button>
        {/* Font size */}
        <button style={{ ...iconBtn, background: btnBg, color: btnColor }} onClick={increaseFont} title="Bigger text">A+</button>
        <button style={{ ...iconBtn, background: btnBg, color: btnColor, fontSize: 14 }} onClick={decreaseFont} title="Smaller text">A-</button>
        {/* Night mode */}
        <button style={{ ...iconBtn, background: btnBg, color: btnColor }} onClick={toggleNightMode} title="Day / Night">
          {nightMode ? "\u2600" : "\u263D"}
        </button>
        {/* Help */}
        <button style={{ ...iconBtn, background: btnBg, color: btnColor }} onClick={() => setShowHelp(true)} title="How to use">?</button>
        {/* Next page */}
        <button style={{ ...navBtn, background: btnBg, color: btnColor }} onClick={goNextPage} title="Next page">
          {"\u203A"}
        </button>
      </div>

      {/* Translate popup */}
      {translateText && (
        <div style={popupOverlay} onClick={() => { setTranslateText(null); clearSelection(); }}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontSize: 18, color: "#4a5568", marginBottom: 12 }}>{translateText}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#2d3748" }}>
              {translating ? "Translating..." : translateResult}
            </div>
            <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={() => { setTranslateText(null); clearSelection(); }}>
              Close
            </button>
          </div>
        </div>
      )}

      {/* Quiz popup */}
      {showQuiz && (
        <div style={popupOverlay} onClick={() => setShowQuiz(false)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            {grade ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 48 }}>
                  {grade.stars >= 3 ? "\u{1F389}" : grade.stars >= 2 ? "\u{1F44D}" : grade.stars >= 1 ? "\u{1F44F}" : "\u{1F4AA}"}
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, color: "#4a3f6b", marginTop: 8 }}>
                  {grade.score} / {grade.total} correct!
                </div>
                <div style={{ fontSize: 32, marginTop: 8 }}>
                  {"\u2605".repeat(grade.stars)}{"\u2606".repeat(Math.max(0, 3 - grade.stars))}
                </div>
                {grade.encouragements[0] && (
                  <div style={{ fontSize: 18, color: "#667eea", marginTop: 8 }}>{grade.encouragements[0]}</div>
                )}
                {grade.per_question.map((q, i) => (
                  <div key={i} style={{
                    marginTop: 12, padding: 12, borderRadius: 12,
                    background: q.correct ? "#f0fff4" : "#fff5f5", textAlign: "left",
                  }}>
                    <span style={{ fontSize: 20 }}>{q.correct ? "\u2714" : "\u2718"}</span>
                    <span style={{ fontSize: 14, color: "#4a5568", marginLeft: 8 }}>{q.explanation}</span>
                  </div>
                ))}
                <button style={{ ...bigBtn, marginTop: 16, background: "#667eea", color: "white" }} onClick={() => setShowQuiz(false)}>
                  Done!
                </button>
              </div>
            ) : quizLoading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48 }}>?</div>
                <p style={{ fontSize: 18, color: "#667eea" }}>Making your quiz...</p>
              </div>
            ) : questions.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <p style={{ fontSize: 18, color: "#e53e3e" }}>No quiz for this page yet. Try another chapter!</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={() => setShowQuiz(false)}>
                  Close
                </button>
              </div>
            ) : (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, color: "#4a3f6b", marginBottom: 16 }}>Fun Quiz!</h2>
                {questions.map((q, qi) => (
                  <div key={qi} style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 18, fontWeight: 600, color: "#2d3748", marginBottom: 8 }}>
                      {q.question}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {q.choices.map((c, ci) => (
                        <button
                          key={ci}
                          onClick={() => setAnswers({ ...answers, [qi]: ci })}
                          style={{
                            padding: "12px 16px", borderRadius: 12,
                            border: answers[qi] === ci ? "3px solid #667eea" : "3px solid #e2e8f0",
                            background: answers[qi] === ci ? "#e9d8fd" : "white",
                            fontSize: 16, cursor: "pointer", textAlign: "left",
                          }}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={submitQuiz}
                  disabled={submitting}
                >
                  {submitting ? "Checking..." : "Check Answers!"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────

const toolbarBtn: React.CSSProperties = {
  background: "#f7fafc", border: "none", borderRadius: 10,
  padding: "8px 12px", fontSize: 15, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
};

const bigBtn: React.CSSProperties = {
  border: "none", borderRadius: 16, padding: "14px 28px",
  fontSize: 18, fontWeight: 700, cursor: "pointer", color: "#2d3748",
};

const actionBtn: React.CSSProperties = {
  border: "none", borderRadius: 14, padding: "10px 14px",
  fontSize: 14, fontWeight: 700, cursor: "pointer", color: "#2d3748", whiteSpace: "nowrap",
};

const iconBtn: React.CSSProperties = {
  border: "none", borderRadius: 12, padding: "10px 10px",
  fontSize: 16, fontWeight: 700, cursor: "pointer", minWidth: 44,
};

const navBtn: React.CSSProperties = {
  border: "none", borderRadius: 12, padding: "10px 14px",
  fontSize: 24, fontWeight: 800, cursor: "pointer", minWidth: 48,
};

const selBtn: React.CSSProperties = {
  border: "none", borderRadius: 10, padding: "8px 12px",
  fontSize: 14, fontWeight: 700, cursor: "pointer", color: "#2d3748", whiteSpace: "nowrap",
};

const cancelBtn: React.CSSProperties = {
  padding: "12px 24px", borderRadius: 12, border: "none",
  fontSize: 16, fontWeight: 700, cursor: "pointer", background: "#e2e8f0", color: "#4a5568",
};

const confirmBtn: React.CSSProperties = {
  padding: "12px 24px", borderRadius: 12, border: "none",
  fontSize: 16, fontWeight: 700, cursor: "pointer", background: "#667eea", color: "white",
};

const popupOverlay: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(0,0,0,0.4)", display: "flex",
  alignItems: "center", justifyContent: "center", zIndex: 100,
};

const popupBox: React.CSSProperties = {
  background: "white", borderRadius: 24, padding: 28,
  maxWidth: 500, width: "90%", maxHeight: "80vh", overflowY: "auto",
  boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
};
