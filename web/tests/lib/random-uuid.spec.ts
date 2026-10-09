import { afterEach, describe, expect, it, vi } from "vitest";

import { randomUuid } from "@/lib/random-uuid";

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function deterministicBytes(target: Uint8Array): Uint8Array {
  for (let i = 0; i < target.length; i += 1) target[i] = i;
  return target;
}

describe("randomUuid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("delegates to crypto.randomUUID when available", () => {
    const minted = "decafbad-cafe-4000-8000-000000000001";
    vi.stubGlobal(
      "crypto",
      Object.assign(new EventTarget(), {
        randomUUID: vi.fn(() => minted),
        getRandomValues: vi.fn(),
      }),
    );

    expect(randomUuid()).toBe(minted);
  });

  it("formats the getRandomValues fallback with v4 version and variant bits", () => {
    vi.stubGlobal(
      "crypto",
      Object.assign(new EventTarget(), {
        randomUUID: undefined,
        getRandomValues: vi.fn(deterministicBytes),
      }),
    );

    expect(randomUuid()).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
  });

  it("fills a 16-byte buffer through getRandomValues", () => {
    const getRandomValues = vi.fn(deterministicBytes);
    vi.stubGlobal(
      "crypto",
      Object.assign(new EventTarget(), {
        randomUUID: undefined,
        getRandomValues,
      }),
    );

    randomUuid();

    expect(getRandomValues).toHaveBeenCalledTimes(1);
    const [buffer] = getRandomValues.mock.calls[0] as [Uint8Array];
    expect(buffer).toBeInstanceOf(Uint8Array);
    expect(buffer.length).toBe(16);
  });

  it("mints a valid v4 uuid without Web Crypto at all", () => {
    vi.stubGlobal("crypto", undefined);

    const value = randomUuid();

    expect(value).toMatch(UUID_V4_PATTERN);
  });

  it("ignores a non-function randomUUID and still uses getRandomValues", () => {
    const getRandomValues = vi.fn(deterministicBytes);
    vi.stubGlobal(
      "crypto",
      Object.assign(new EventTarget(), {
        randomUUID: 42,
        getRandomValues,
      }),
    );

    expect(randomUuid()).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
    expect(getRandomValues).toHaveBeenCalledTimes(1);
  });

  it("ignores a non-function getRandomValues and still mints a v4 uuid", () => {
    vi.stubGlobal(
      "crypto",
      Object.assign(new EventTarget(), {
        randomUUID: undefined,
        getRandomValues: "not-a-function",
      }),
    );

    expect(randomUuid()).toMatch(UUID_V4_PATTERN);
  });

  it("produces the canonical 8-4-4-4-12 shape in the browser runtime", () => {
    const value = randomUuid();

    const parts = value.split("-");
    expect(parts.map((part) => part.length)).toEqual([8, 4, 4, 4, 12]);
    expect(value).toMatch(UUID_V4_PATTERN);
    expect(value).toBe(value.toLowerCase());
  });

  it("mints distinct ids across calls", () => {
    const first = randomUuid();
    const second = randomUuid();

    expect(first).not.toBe(second);
  });
});
