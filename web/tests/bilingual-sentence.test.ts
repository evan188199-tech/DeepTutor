import test from "node:test";
import assert from "node:assert/strict";

import {
  matchBilingualSentence,
  splitChineseSentences,
  splitEnglishSentences,
} from "../lib/bilingual-sentence";

test("sentence splitters preserve terminal punctuation", () => {
  assert.deepEqual(splitEnglishSentences("One sentence. Another one!"), [
    "One sentence.",
    "Another one!",
  ]);
  assert.deepEqual(splitChineseSentences("第一句。第二句！"), ["第一句。", "第二句！"]);
});

test("an English sentence maps to contiguous aligned Chinese sentences", () => {
  const group = {
    en: ["The first event happened. A later event changed everything. The ending arrived."],
    zh: ["第一件事發生了。後來的事件改變了一切。結局到來了。"],
  };

  const first = matchBilingualSentence(group, "en", 0, "The first event happened.");
  const last = matchBilingualSentence(group, "en", 0, "The ending arrived.");

  assert.equal(first, "第一件事發生了。");
  assert.equal(last, "結局到來了。");
});

test("a Chinese sentence maps back to contiguous English sentences", () => {
  const group = {
    en: ["First sentence. Second sentence. Third sentence."],
    zh: ["第一句。第二句。第三句。"],
  };

  assert.equal(matchBilingualSentence(group, "zh", 0, "第二句。"), "Second sentence.");
});

test("selecting a whole paragraph returns the whole aligned group", () => {
  const group = {
    en: ["Full English paragraph."],
    zh: ["完整中文段落。"],
  };

  assert.equal(
    matchBilingualSentence(group, "en", 0, "Full English paragraph."),
    "完整中文段落。",
  );
});
