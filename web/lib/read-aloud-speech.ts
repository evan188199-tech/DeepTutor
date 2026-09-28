export interface SpeechVoiceCandidate {
  lang: string;
  name: string;
  voiceURI?: string;
  localService?: boolean;
}

function languageTag(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, "-");
}

function primaryLanguage(value: string): string {
  const match = languageTag(value).match(/^([a-z]{2,3})(?:$|-)/);
  return match?.[1] ?? "";
}

function countMatches(value: string, pattern: RegExp): number {
  return (value.match(pattern) ?? []).length;
}

export function inferSpeechLocale(text: string, fallback: string): string {
  const value = text || "";
  const chinese = countMatches(value, /[\u3400-\u4DBF\u4E00-\u9FFF]/g);
  const japanese = countMatches(value, /[\u3040-\u30FF]/g);
  const korean = countMatches(value, /[\uAC00-\uD3AF\u1100-\u11FF]/g);
  const cyrillic = countMatches(value, /[\u0400-\u04FF]/g);
  const arabic = countMatches(value, /[\u0600-\u06FF]/g);
  const hebrew = countMatches(value, /[\u0590-\u05FF]/g);
  const scripts = [
    ["zh-CN", chinese],
    ["ja-JP", japanese],
    ["ko-KR", korean],
    ["ru-RU", cyrillic],
    ["ar-SA", arabic],
    ["he-IL", hebrew],
  ] as const;

  const detected = scripts.filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);
  if (detected.length) return detected[0][0];

  // Latin-script languages are too close to distinguish reliably. Default to
  // concrete English rather than leaking the UI locale into material speech:
  // a Chinese interface must not make an English passage use a Chinese voice.
  void fallback;
  return "en-US";
}

function nameQuality(name: string): number {
  const value = name.toLowerCase();
  if (/(premium|enhanced|natural|neural)/.test(value)) return 30;
  if (/google/.test(value)) return 20;
  if (/microsoft/.test(value)) return 10;
  if (/(compact|eloquence|espeak)/.test(value)) return -25;
  return 0;
}

export function selectSpeechVoice(
  voices: SpeechVoiceCandidate[],
  locale: string,
): SpeechVoiceCandidate | undefined {
  const target = languageTag(locale);
  const targetPrimary = primaryLanguage(target);
  if (!targetPrimary) return undefined;

  return [...voices]
    .map((voice, index) => {
      const lang = languageTag(voice.lang);
      const languageScore = lang === target ? 100 : primaryLanguage(lang) === targetPrimary ? 55 : 0;
      const localBonus = voice.localService === false ? 3 : 0;
      return { voice, index, score: languageScore + nameQuality(voice.name) + localBonus };
    })
    .filter((row) => row.score >= 55)
    .sort((a, b) => b.score - a.score || a.index - b.index)[0]?.voice;
}
