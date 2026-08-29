import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { timedMediaSubtitleUrl } from "../lib/video-learning-api";

test("timed media subtitle URLs stay on the same API origin", () => {
  assert.equal(
    timedMediaSubtitleUrl("material/with:special?id"),
    "/api/v1/video-learning/materials/material%2Fwith%3Aspecial%3Fid/subtitles.vtt"
  );
});

test("the player exposes stored transcript cues as default captions", () => {
  const source = readFileSync(path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"), "utf8");
  assert.match(source, /kind="captions"/);
  assert.match(source, /subtitleBlobUrl/);
  assert.match(source, /new Blob\(\[subtitleText\]/);
  assert.match(source, /default\b/);
  assert.match(source, /textTracks/);
  assert.match(source, /mode = "showing"/);
  assert.match(source, /requestPictureInPicture/);
  assert.match(source, /webkitpresentationmodechanged/);
  assert.match(source, /2_000, 5_000, 10_000, 30_000, 60_000/);
  assert.match(source, /Connect YouTube/);
  assert.match(source, /data-active/);
  assert.match(source, /aria-current/);
  assert.match(source, /scrollTo/);
});

test("watching sessions persist and restore their material after a page refresh", () => {
  const context = readFileSync(path.join(process.cwd(), "context/WatchingContext.tsx"), "utf8");
  const state = readFileSync(path.join(process.cwd(), "lib/watching-turn-state.ts"), "utf8");
  const page = readFileSync(path.join(process.cwd(), "app/(workspace)/home/[[...sessionId]]/page.tsx"), "utf8");
  assert.match(state, /sessionStorage/);
  assert.match(state, /watchingSessionStorageKey/);
  assert.match(context, /readPersistedWatchingState/);
  assert.match(context, /getVideoLearningMaterial\(persisted\.materialId\)/);
  assert.match(context, /persistWatchingState/);
  assert.match(context, /clearPersistedWatchingState/);
  assert.match(page, /restoredFromSession/);
  assert.match(page, /setCapability\("immersive_watching"\)/);
});

test("YouTube connection uses the host Mac Chrome session without an isolated-login poll", () => {
  const source = readFileSync(path.join(process.cwd(), "components/watching/InvidiousHome.tsx"), "utf8");
  const reader = readFileSync(path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"), "utf8");
  assert.match(source, /youtubeConnecting/);
  assert.match(source, /operation\.mode === "host_chrome" \|\| !operation\.operation_id/);
  assert.match(source, /existing Chrome session/);
  assert.match(reader, /operation\.mode === "host_chrome" \|\| !operationId/);
  assert.match(reader, /requestSubtitlePrefetch\(material\.material_id\)/);
  assert.match(reader, /Chrome session/);
  assert.match(source, /Mac running DeepTutor/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /getYouTubeConnectOperation/);
});
