import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  invidiousFallbackUrl,
  shouldOpenInvidiousInCurrentTab,
} from "../lib/invidious-open";

test("invidiousFallbackUrl keeps a current public feed URL", () => {
  assert.equal(invidiousFallbackUrl("https://inv.example/"), "https://inv.example/feed/popular");
  assert.equal(invidiousFallbackUrl("https://inv.example"), "https://inv.example/feed/popular");
  assert.equal(invidiousFallbackUrl("  "), "");
  assert.equal(invidiousFallbackUrl(undefined), "");
  assert.equal(
    invidiousFallbackUrl("https://inv.example", "dQw4w9WgXcQ", 42.8),
    "https://inv.example/watch?v=dQw4w9WgXcQ&t=42",
  );
  assert.equal(
    invidiousFallbackUrl("https://inv.example", "dQw4w9WgXcQ", 1),
    "https://inv.example/watch?v=dQw4w9WgXcQ",
  );
});

test("hub Open Invidious always uses the current tab", () => {
  assert.equal(shouldOpenInvidiousInCurrentTab(true, true), true);
  assert.equal(shouldOpenInvidiousInCurrentTab(true, false), true);
});

test("watch Open Invidious falls back to the current tab when the popup is blocked", () => {
  assert.equal(shouldOpenInvidiousInCurrentTab(false, true), false);
  assert.equal(shouldOpenInvidiousInCurrentTab(false, false), true);
});

test("Invidious hub surfaces Open Invidious status and current-tab navigation", () => {
  const reader = readFileSync(
    path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"),
    "utf8",
  );
  const home = readFileSync(
    path.join(process.cwd(), "components/watching/InvidiousHome.tsx"),
    "utf8",
  );
  assert.match(reader, /openInvidiousRenderer\(material\?\.source\?\.video_id, currentTime, true\)/);
  assert.match(reader, /openingInvidious=\{openingInvidious\}/);
  assert.match(reader, /fallbackOpenUrl=\{invidiousFallbackUrl\(\s*invidiousPublicUrl/);
  assert.match(reader, /window\.open\("about:blank", "_blank"\)/);
  assert.match(reader, /target\.location\.href = launch\.launch_url/);
  assert.match(reader, /target\.location\.href = fallbackUrl/);
  assert.doesNotMatch(reader, /window\.open\(fallbackUrl \|\| "about:blank", "_blank"\)/);
  assert.match(home, /openingInvidious/);
  assert.match(home, /Continue to Invidious/);
  assert.match(home, /disabled=\{openingInvidious\}/);
});

test("hub keeps the selected card visible until its playable material resolves", () => {
  const context = readFileSync(path.join(process.cwd(), "context/WatchingContext.tsx"), "utf8");
  const reader = readFileSync(path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"), "utf8");
  const home = readFileSync(path.join(process.cwd(), "components/watching/InvidiousHome.tsx"), "utf8");
  assert.match(context, /Promise<boolean>/);
  assert.match(context, /replaceWatchingUrl\(next\.material_id, start\)/);
  assert.match(reader, /const opened = await openUrl\(videoUrl\);/);
  assert.match(reader, /if \(opened\) setShowInvidiousHome\(false\);/);
  assert.match(reader, /getVideoLearningMaterial\(materialId\)/);
  assert.match(home, /onPointerEnter=\{onPrefetch\}/);
  assert.match(home, /api\/v1\/videos/);
});
