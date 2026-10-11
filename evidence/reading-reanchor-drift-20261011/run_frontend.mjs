// Offline drift fixture for the frontend selector re-anchor path.
//
// Imports the real web/lib/reading-w3c-annotations.ts (Node >= 22.18 strips
// the type-only import, so no bundler or node_modules is needed) and runs it
// against the same drift scenarios as the backend harness.
//
//     node run_frontend.mjs --out frontend_results.json

import { writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { resolveTextSelectors } from "/Users/Shared/dt-agen1802-reanchor-wt/web/lib/reading-w3c-annotations.ts";

const scenarios = [];

function record(name, text, annotation, note = "") {
  const selectors = resolveTextSelectors(text, annotation);
  const quote = selectors?.find((s) => s.type === "TextQuoteSelector");
  const position = selectors?.find((s) => s.type === "TextPositionSelector");
  let partialWord = null;
  let positionMatches = null;
  if (position && quote) {
    positionMatches = true;
    const before = text[position.start - 1];
    const after = text[position.end];
    partialWord = Boolean(
      (before && /\S/.test(before)) || (after && /\S/.test(after)),
    );
  }
  scenarios.push({
    scenario: name,
    note,
    anchored: selectors !== null,
    quote: quote?.exact ?? null,
    position: position ? { start: position.start, end: position.end } : null,
    position_matches_quote: positionMatches,
    partial_word_anchor: partialWord,
  });
}

const sel = (exact, prefix = "", suffix = "") => ({
  type: "TextQuoteSelector",
  exact,
  prefix,
  suffix,
});
const pos = (start, end) => ({ type: "TextPositionSelector", start, end });

// F1 stale position + unique quote -> re-anchor
record(
  "stale_position_unique_quote",
  "A new introduction. portable quote end",
  { quote: "portable quote", selectors: [sel("portable quote", "Start "), pos(0, 14)] },
);

// F2 duplicated quote, no context -> ambiguous
record(
  "duplicate_no_context",
  "portable quote then portable quote",
  { quote: "portable quote", selectors: [sel("portable quote")] },
);

// F3 duplicated quote, stored context still distinguishes -> anchored
record(
  "duplicate_context_distinguishes",
  "first: portable quote / second: portable quote",
  {
    quote: "portable quote",
    selectors: [sel("portable quote", "second: ", " ")],
  },
);

// F4 stale context + duplicated quote (mirrors backend compounding) -> null
record(
  "stale_context_duplicate",
  "new intro portable quote / repeat portable quote",
  {
    quote: "portable quote",
    selectors: [sel("portable quote", "old intro ", " ")],
  },
  "stored prefix no longer touches either copy",
);

// F5 stale position still covers normalise-equal text -> position accepted
record(
  "stale_position_whitespace_variant_accepted",
  "Start portable\n\nquote end",
  { quote: "portable quote", selectors: [sel("portable quote", "Start "), pos(6, 21)] },
  "position slice normalise-equals the quote, so it wins by design",
);

// F6 word-extension drift -> partial-word anchor
record(
  "word_extended_partial_word",
  "The quick brown foxes jump over the lazy dog.",
  { quote: "quick brown fox", selectors: [sel("quick brown fox", "The "), pos(4, 19)] },
);

// F7 case change -> null
record(
  "case_change",
  "The Quick Brown Fox jumps over the lazy dog.",
  { quote: "quick brown fox", selectors: [sel("quick brown fox", "The "), pos(4, 19)] },
);

// F8 regex metacharacters in quote -> anchored correctly
record(
  "regex_metacharacters",
  "Result: 1.5 (±0.2) [update] recorded.",
  { quote: "1.5 (±0.2) [update]", selectors: [sel("1.5 (±0.2) [update]", "Result: ", " recorded")] },
);

// F9 legacy quote-only rows (no selectors)
record(
  "legacy_quote_only_unique",
  "Intro added. quick brown fox continues.",
  { quote: "quick brown fox", selectors: [] },
  "frontend anchors legacy rows the backend revision migration marks unresolved",
);
record(
  "legacy_quote_only_duplicate",
  "quick brown fox then quick brown fox",
  { quote: "quick brown fox", selectors: [] },
);

// F10 quote moved, stale position + stale context -> re-anchored by raw quote
record(
  "moved_quote_stale_context_unique",
  "Totally new surroundings around the quick brown fox passage now.",
  {
    quote: "quick brown fox",
    selectors: [sel("quick brown fox", "The ", " jumps"), pos(4, 19)],
  },
);

const args = parseArgs({
  args: process.argv.slice(2),
  options: { out: { type: "string", default: "frontend_results.json" } },
});
const out = args.values.out;
writeFileSync(out, JSON.stringify(scenarios, null, 2));
for (const row of scenarios) {
  console.log(
    `${row.scenario.padEnd(45)} anchored=${String(row.anchored).padEnd(5)} partial_word=${row.partial_word_anchor}`,
  );
}
console.log(`wrote ${out}: ${scenarios.length} scenarios`);
