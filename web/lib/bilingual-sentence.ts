export type BilingualSide = "en" | "zh";

export interface BilingualSentenceGroup {
  en: string[];
  zh: string[];
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .replace(/[\p{P}\p{S}\s]+/gu, "")
    .normalize("NFKD");
}

const ABBREVIATIONS = new Set([
  "mr",
  "mrs",
  "ms",
  "dr",
  "prof",
  "sr",
  "jr",
  "st",
  "co",
  "inc",
  "ltd",
  "corp",
  "vs",
  "v",
  "e.g",
  "i.e",
  "etc",
  "cf",
  "vol",
  "vols",
  "no",
  "nos",
  "sec",
  "fig",
  "figs",
  "p",
  "pp",
  "ch",
  "ed",
  "eds",
  "trans",
  "app",
  "dept",
  "univ",
  "approx",
  "ibid",
  "u.s",
  "u.k",
  "u.n",
  "d.c",
  "a.m",
  "p.m",
]);

export function splitEnglishSentences(text: string): string[] {
  const tokens: string[] = [];
  let start = 0;
  const terminal = /([.!?]['"”’)\]]*)\s+/gu;
  for (const match of text.matchAll(terminal)) {
    tokens.push(text.slice(start, match.index) + match[1]);
    start = (match.index ?? 0) + match[0].length;
  }
  if (start < text.length) tokens.push(text.slice(start));

  const sentences: string[] = [];
  let buffered = "";
  for (const token of tokens) {
    buffered = buffered ? `${buffered} ${token}` : token;
    const last = buffered.match(/[A-Za-z0-9.]+[.!?]['"”’)\]]*$/u);
    const word = last?.[0]?.toLowerCase().replace(/\.+$/u, "") ?? "";
    if (ABBREVIATIONS.has(word) || /^[a-z]\.[a-z]$/u.test(word) || /\d\.\d$/u.test(buffered)) {
      continue;
    }
    if (/^\d+$/u.test(buffered) && sentences.length) {
      sentences[sentences.length - 1] += ` ${buffered}`;
    } else {
      sentences.push(buffered);
    }
    buffered = "";
  }
  if (buffered) sentences.push(buffered);
  return sentences;
}

export function splitChineseSentences(text: string): string[] {
  return text
    .split(/(?<=[。！？；…]['"”’」』）)]*)/u)
    .map((part) => part.trim())
    .filter(Boolean);
}

function sentences(side: BilingualSide, text: string): string[] {
  return side === "en" ? splitEnglishSentences(text) : splitChineseSentences(text);
}

function score(selected: string, sentence: string): number {
  const selectedWords = selected.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  if (!selectedWords.length) return 0;
  const sentenceWords = new Set(sentence.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []);
  const hits = selectedWords.filter((word) => sentenceWords.has(word)).length;
  return hits / selectedWords.length;
}

function selectedSentenceIndex(parts: string[], selected: string): number {
  let best = 0;
  let bestScore = -1;
  parts.forEach((sentence, index) => {
    const current = score(selected, sentence);
    if (current > bestScore) {
      best = index;
      bestScore = current;
    }
  });
  return best;
}

function proportionalSlice(
  sourceParts: string[],
  targetParts: string[],
  sourceIndex: number,
): string {
  if (!targetParts.length) return "";
  const lengths = sourceParts.map((part) => Math.max(normalize(part).length, 1));
  const total = lengths.reduce((sum, length) => sum + length, 0);
  const before = lengths.slice(0, sourceIndex).reduce((sum, length) => sum + length, 0);
  const start = before / total;
  const end = (before + lengths[sourceIndex]) / total;
  const targetLengths = targetParts.map((part) => Math.max(normalize(part).length, 1));
  const targetTotal = targetLengths.reduce((sum, length) => sum + length, 0);

  let cursor = 0;
  const chunks: string[] = [];
  targetParts.forEach((part, index) => {
    const partCenter = (cursor + targetLengths[index] / 2) / targetTotal;
    cursor += targetLengths[index];
    if (partCenter >= start && partCenter <= end) chunks.push(part);
  });
  if (!chunks.length) {
    const center = (start + end) / 2;
    let nearest = 0;
    let nearestDistance = Infinity;
    let position = 0;
    targetParts.forEach((_, index) => {
      const partCenter = (position + targetLengths[index] / 2) / targetTotal;
      position += targetLengths[index];
      const distance = Math.abs(partCenter - center);
      if (distance < nearestDistance) {
        nearest = index;
        nearestDistance = distance;
      }
    });
    chunks.push(targetParts[nearest]);
  }
  return chunks.join(sideJoiner(targetParts));
}

function sideJoiner(parts: string[]): string {
  return /[\u3400-\u9fff]/u.test(parts[0] ?? "") ? "" : " ";
}

export function matchBilingualSentence(
  group: BilingualSentenceGroup,
  side: BilingualSide,
  paragraphIndex: number,
  selectedText: string,
): string | null {
  const sourceParagraphs = group[side];
  const oppositeParagraphs = group[side === "en" ? "zh" : "en"];
  const sourceParagraph = sourceParagraphs[paragraphIndex];
  if (!sourceParagraph || !oppositeParagraphs.length) return null;

  if (normalize(selectedText) === normalize(sourceParagraph)) {
    return oppositeParagraphs.join(sideJoiner(oppositeParagraphs));
  }

  const sourceParts = sentences(side, sourceParagraph);
  if (!sourceParts.length) return oppositeParagraphs.join(sideJoiner(oppositeParagraphs));
  const oppositeParts = oppositeParagraphs.flatMap((paragraph) =>
    sentences(side === "en" ? "zh" : "en", paragraph),
  );
  const index = selectedSentenceIndex(sourceParts, selectedText);
  return proportionalSlice(sourceParts, oppositeParts.length ? oppositeParts : oppositeParagraphs, index);
}
