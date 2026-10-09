import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";

const api = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

vi.mock("@/lib/api", () => api);

type Track = { stop: ReturnType<typeof vi.fn> };

/**
 * Minimal MediaRecorder double: records through the same lifecycle the hook
 * relies on (start → dataavailable → stop/onstop) without touching any real
 * capture hardware.
 */
class MockMediaRecorder {
  static instances: MockMediaRecorder[] = [];
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm;codecs=opus";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  pendingChunk: Blob | null = null;
  start = vi.fn(() => {
    this.state = "recording";
  });
  stop = vi.fn(() => {
    if (this.state === "inactive") return;
    this.state = "inactive";
    this.ondataavailable?.({ data: this.pendingChunk ?? new Blob([]) });
    this.onstop?.();
  });
  constructor(public stream: { getTracks: () => Track[] }) {
    MockMediaRecorder.instances.push(this);
  }
}

function makeStream() {
  const track: Track = { stop: vi.fn() };
  return { track, stream: { getTracks: () => [track] } };
}

function setMediaDevices(
  value: { getUserMedia: ReturnType<typeof vi.fn> } | undefined,
) {
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value,
  });
}

function okJson(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload };
}

/** Grants a fake mic and installs the recorder double. */
function grantMic() {
  const { stream, track } = makeStream();
  const getUserMedia = vi.fn(async () => stream);
  setMediaDevices({ getUserMedia });
  vi.stubGlobal(
    "MediaRecorder",
    MockMediaRecorder as unknown as typeof MediaRecorder,
  );
  return { getUserMedia, stream, track };
}

beforeEach(() => {
  api.apiFetch.mockReset();
  MockMediaRecorder.instances = [];
});

afterEach(() => {
  delete (window.navigator as { mediaDevices?: unknown }).mediaDevices;
  vi.unstubAllGlobals();
});

it("flags unsupported browsers before requesting permission", async () => {
  setMediaDevices(undefined);
  const onTranscript = vi.fn();
  const { result } = renderHook(() => useVoiceRecorder(onTranscript));
  await act(async () => {
    await result.current.start();
  });
  expect(result.current.state).toBe("idle");
  expect(result.current.error).toBe(
    "Recording is not supported in this browser.",
  );
  expect(api.apiFetch).not.toHaveBeenCalled();
  expect(onTranscript).not.toHaveBeenCalled();
});

it("still flags unsupported when only MediaRecorder is missing", async () => {
  const getUserMedia = vi.fn(async () => makeStream().stream);
  setMediaDevices({ getUserMedia });
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  expect(result.current.error).toBe(
    "Recording is not supported in this browser.",
  );
  expect(getUserMedia).not.toHaveBeenCalled();
});

it("reports denied microphone permission and stays idle", async () => {
  const getUserMedia = vi.fn(async () => {
    throw new Error("NotAllowedError");
  });
  setMediaDevices({ getUserMedia });
  vi.stubGlobal(
    "MediaRecorder",
    MockMediaRecorder as unknown as typeof MediaRecorder,
  );
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  expect(result.current.error).toBe("Microphone permission denied.");
  expect(result.current.state).toBe("idle");
  expect(MockMediaRecorder.instances).toHaveLength(0);
});

it("starts recording once permission is granted", async () => {
  const { getUserMedia, stream } = grantMic();
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  expect(result.current.error).toBeNull();
  expect(result.current.state).toBe("recording");
  expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
  const recorder = MockMediaRecorder.instances[0];
  expect(recorder.stream).toBe(stream);
  expect(recorder.start).toHaveBeenCalledOnce();
});

it("ignores start while a recording is already active", async () => {
  const { getUserMedia } = grantMic();
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  await act(async () => {
    await result.current.start();
  });
  expect(getUserMedia).toHaveBeenCalledOnce();
  expect(MockMediaRecorder.instances).toHaveLength(1);
});

it("uploads the recording and forwards the trimmed transcript", async () => {
  const { track } = grantMic();
  api.apiFetch.mockResolvedValue(okJson({ text: "  hello world  " }));
  const onTranscript = vi.fn();
  const { result } = renderHook(() => useVoiceRecorder(onTranscript));
  await act(async () => {
    await result.current.start();
  });
  const recorder = MockMediaRecorder.instances[0];
  act(() => {
    recorder.pendingChunk = new Blob(["chunk-bytes"]);
    result.current.stop();
  });
  expect(recorder.stop).toHaveBeenCalledOnce();
  await waitFor(() => expect(result.current.state).toBe("idle"));
  expect(api.apiFetch).toHaveBeenCalledOnce();
  const [url, init] = api.apiFetch.mock.calls[0];
  expect(url).toBe("/api/voice/stt");
  expect(init.method).toBe("POST");
  const file = (init.body as FormData).get("file") as File;
  expect(file.name).toBe("recording.webm");
  expect(onTranscript).toHaveBeenCalledWith("hello world");
  expect(track.stop).toHaveBeenCalled();
  expect(result.current.error).toBeNull();
});

it("returns to idle without uploading an empty recording", async () => {
  grantMic();
  const onTranscript = vi.fn();
  const { result } = renderHook(() => useVoiceRecorder(onTranscript));
  await act(async () => {
    await result.current.start();
  });
  act(() => {
    result.current.stop();
  });
  await waitFor(() => expect(result.current.state).toBe("idle"));
  expect(api.apiFetch).not.toHaveBeenCalled();
  expect(onTranscript).not.toHaveBeenCalled();
});

it("surfaces the backend detail when transcription fails", async () => {
  grantMic();
  api.apiFetch.mockResolvedValue({
    ok: false,
    status: 502,
    json: async () => ({ detail: "STT provider down" }),
  });
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  act(() => {
    MockMediaRecorder.instances[0].pendingChunk = new Blob(["chunk-bytes"]);
    result.current.stop();
  });
  await waitFor(() =>
    expect(result.current.error).toBe("STT provider down"),
  );
  expect(result.current.state).toBe("idle");
});

it("falls back to a status message when the error body is unreadable", async () => {
  grantMic();
  api.apiFetch.mockResolvedValue({
    ok: false,
    status: 500,
    json: async () => {
      throw new Error("no body");
    },
  });
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  act(() => {
    MockMediaRecorder.instances[0].pendingChunk = new Blob(["chunk-bytes"]);
    result.current.stop();
  });
  await waitFor(() =>
    expect(result.current.error).toBe("Transcription failed (HTTP 500)."),
  );
  expect(result.current.state).toBe("idle");
});

it("drops blank transcripts after a successful upload", async () => {
  grantMic();
  api.apiFetch.mockResolvedValue(okJson({ text: "   " }));
  const onTranscript = vi.fn();
  const { result } = renderHook(() => useVoiceRecorder(onTranscript));
  await act(async () => {
    await result.current.start();
  });
  act(() => {
    MockMediaRecorder.instances[0].pendingChunk = new Blob(["chunk-bytes"]);
    result.current.stop();
  });
  await waitFor(() => expect(result.current.state).toBe("idle"));
  expect(onTranscript).not.toHaveBeenCalled();
  expect(result.current.error).toBeNull();
});

it("toggle starts from idle and stops while recording", async () => {
  grantMic();
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    result.current.toggle();
  });
  await waitFor(() => expect(result.current.state).toBe("recording"));
  act(() => {
    result.current.toggle();
  });
  expect(MockMediaRecorder.instances[0].stop).toHaveBeenCalledOnce();
});

it("ignores toggle while transcription is in flight", async () => {
  const { getUserMedia } = grantMic();
  api.apiFetch.mockReturnValue(new Promise(() => {}));
  const { result } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  act(() => {
    MockMediaRecorder.instances[0].pendingChunk = new Blob(["chunk-bytes"]);
    result.current.stop();
  });
  await waitFor(() => expect(result.current.state).toBe("transcribing"));
  act(() => {
    result.current.toggle();
  });
  expect(getUserMedia).toHaveBeenCalledOnce();
  expect(result.current.state).toBe("transcribing");
});

it("stops the recorder and releases the mic on unmount", async () => {
  const { track } = grantMic();
  const { result, unmount } = renderHook(() => useVoiceRecorder(vi.fn()));
  await act(async () => {
    await result.current.start();
  });
  const recorder = MockMediaRecorder.instances[0];
  unmount();
  expect(recorder.stop).toHaveBeenCalledOnce();
  expect(track.stop).toHaveBeenCalled();
});
