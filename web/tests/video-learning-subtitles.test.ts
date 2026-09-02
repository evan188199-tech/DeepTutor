import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  connectYouTubeSession,
  disconnectYouTubeSession,
  getYouTubeSessionStatus,
  requestSubtitlePrefetch,
} from "../lib/video-learning-api";

function withFetch(stub: typeof fetch): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = stub;
  return () => {
    globalThis.fetch = original;
  };
}

test("YouTube caption session and prefetch calls use canonical routes", async () => {
  const calls: Array<{ method: string; url: URL; body: string | null }> = [];
  const restore = withFetch(async (input, init) => {
    calls.push({
      method: init?.method || "GET",
      url: new URL(String(input), "https://app.example"),
      body: typeof init?.body === "string" ? init.body : null,
    });
    if (calls.length === 1) {
      return Response.json({
        connection: "disconnected",
        helper_available: true,
        last_validated_at: null,
        last_error_code: null,
        next_prefetch_at: null,
      });
    }
    if (calls.length === 2) {
      return Response.json({
        connection: "connected",
        helper_available: true,
        last_error_code: null,
        mode: "host_chrome",
      });
    }
    if (calls.length === 3) {
      return Response.json({
        fetch: {
          status: "queued",
          updated_at: "2026-09-02T00:00:00Z",
          error_code: null,
          attempts: 0,
          next_retry_at: null,
        },
      });
    }
    return Response.json({ ok: true });
  });

  try {
    await getYouTubeSessionStatus();
    await connectYouTubeSession("material/1");
    const fetchState = await requestSubtitlePrefetch("material/1");
    await disconnectYouTubeSession();

    assert.deepEqual(
      calls.map((call) => [call.method, call.url.pathname]),
      [
        ["GET", "/api/video-learning/youtube-session/status"],
        ["POST", "/api/video-learning/youtube-session/connect"],
        ["POST", "/api/video-learning/materials/material%2F1/subtitle-prefetch"],
        ["DELETE", "/api/video-learning/youtube-session"],
      ],
    );
    assert.equal(JSON.parse(String(calls[1].body)).material_id, "material/1");
    assert.equal(fetchState.status, "queued");
  } finally {
    restore();
  }
});

test("the watching panel polls active caption fetches and keeps consent controls", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/watching/WatchingPane.tsx"),
    "utf8",
  );
  assert.match(source, /connectYouTubeSession/);
  assert.match(source, /requestSubtitlePrefetch/);
  assert.match(source, /disconnectYouTubeSession/);
  assert.match(source, /setInterval\(\(\) => \{\s*void refresh\(\);/);
  assert.match(source, /transcript\.fetch\?\.status/);
});
