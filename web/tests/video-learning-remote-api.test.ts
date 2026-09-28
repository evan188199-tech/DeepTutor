import assert from "node:assert/strict";
import test from "node:test";

import {
  createRendererLaunch,
  formatRemotePosition,
  listRemoteSessions,
  sendRemoteSessionCommand,
} from "../lib/video-learning-remote-api";

function withFetch(stub: typeof fetch): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = stub;
  return () => {
    globalThis.fetch = original;
  };
}

test("renderer launches use the canonical remote route and material binding", async () => {
  const calls: Array<{ url: URL; init: RequestInit | undefined }> = [];
  const restore = withFetch(async (input, init) => {
    calls.push({ url: new URL(String(input), "https://app.example"), init });
    return Response.json({
      bootstrap_id: "bootstrap-1",
      ticket: "ticket",
      expires_at: "2026-09-02T00:00:00Z",
      launch_url: "https://renderer.example/watch#dt_bootstrap=ticket",
      renderer_origin: "https://renderer.example",
      material_id: "material-1",
    });
  });
  try {
    const launch = await createRendererLaunch({
      video_id: "dQw4w9WgXcQ",
      material_id: "material-1",
      position_seconds: 12,
    });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.pathname, "/api/video-learning/renderers");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      video_id: "dQw4w9WgXcQ",
      material_id: "material-1",
      position_seconds: 12,
    });
    assert.equal(launch.launch_url, "https://renderer.example/watch#dt_bootstrap=ticket");
  } finally {
    restore();
  }
});

test("remote session commands preserve owner session paths", async () => {
  const calls: Array<{ url: URL; init: RequestInit | undefined }> = [];
  const restore = withFetch(async (input, init) => {
    calls.push({ url: new URL(String(input), "https://app.example"), init });
    return Response.json({
      command_id: "command-1",
      session_id: "session/1",
      owner_id: "local-admin",
      device_id: "device-1",
      command_type: "seek",
      payload: { position_ms: 22_000 },
      status: "pending",
      created_at: "",
      acked_at: null,
      error: null,
    });
  });
  try {
    const command = await sendRemoteSessionCommand("session/1", {
      type: "seek",
      delta_ms: -20_000,
    });
    assert.equal(calls[0].url.pathname, "/api/video-learning/sessions/session%2F1/commands");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      type: "seek",
      delta_ms: -20_000,
    });
    assert.equal(command.status, "pending");
    assert.deepEqual(command.payload, { position_ms: 22_000 });
  } finally {
    restore();
  }
});

test("remote session lists and positions use stable shapes", async () => {
  const restore = withFetch(async () =>
    Response.json({
      sessions: [
        {
          session_id: "session-1",
          owner_id: "local-admin",
          device_id: "device-1",
          instance_origin: "https://renderer.example",
          video_id: "dQw4w9WgXcQ",
          material_id: "material-1",
          title: "Demo",
          position_ms: 3_723_000,
          duration_ms: 0,
          playback_state: "playing",
          playback_rate: 1,
          updated_at: "",
          last_heartbeat_at: "",
          controller_token_hash: "",
        },
      ],
    }),
  );
  try {
    const sessions = await listRemoteSessions();
    assert.equal(sessions.length, 1);
    assert.equal(sessions[0].session_id, "session-1");
    assert.equal(formatRemotePosition(sessions[0].position_ms), "1:02:03");
  } finally {
    restore();
  }
});
