import { afterEach, expect, it, vi } from "vitest";

import { extractBase64FromDataUrl, readFileAsDataUrl } from "@/lib/file-attachments";

it("readFileAsDataUrl: resolves a base64 data URL for text content", async () => {
  const file = new File(["hello"], "a.txt", { type: "text/plain" });

  const dataUrl = await readFileAsDataUrl(file);

  expect(dataUrl).toBe("data:text/plain;base64,aGVsbG8=");
});

it("readFileAsDataUrl: round-trips binary content through base64", async () => {
  const bytes = Uint8Array.from([0, 1, 2, 250, 251, 252, 253, 254, 255]);
  const file = new File([bytes], "blob.bin", { type: "application/octet-stream" });

  const dataUrl = await readFileAsDataUrl(file);

  expect(dataUrl.startsWith("data:application/octet-stream;base64,")).toBe(true);
  const decoded = Uint8Array.from(
    atob(dataUrl.split(",")[1]),
    (ch) => ch.charCodeAt(0),
  );
  expect([...decoded]).toEqual([...bytes]);
});

it("readFileAsDataUrl: resolves a bare data URL for an empty untyped file", async () => {
  const file = new File([], "empty");

  const dataUrl = await readFileAsDataUrl(file);

  expect(dataUrl.startsWith("data:")).toBe(true);
});

it("readFileAsDataUrl: rejects with the reader error when reading fails", async () => {
  class FailingReader {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    result: string | null = null;
    error: DOMException | null = null;
    readAsDataURL(): void {
      this.error = new DOMException("boom", "NotReadableError");
      this.onerror?.();
    }
  }
  vi.stubGlobal("FileReader", FailingReader);
  try {
    const file = new File(["hello"], "a.txt", { type: "text/plain" });

    await expect(readFileAsDataUrl(file)).rejects.toMatchObject({
      name: "NotReadableError",
    });
  } finally {
    vi.unstubAllGlobals();
  }
});

it("extractBase64FromDataUrl: strips the data URL prefix", () => {
  expect(extractBase64FromDataUrl("data:text/plain;base64,aGVsbG8=")).toBe(
    "aGVsbG8=",
  );
});

it("extractBase64FromDataUrl: returns the input unchanged without a comma", () => {
  expect(extractBase64FromDataUrl("cGxhaW4=")).toBe("cGxhaW4=");
  expect(extractBase64FromDataUrl("")).toBe("");
});

it("extractBase64FromDataUrl: keeps payload up to the first comma only", () => {
  expect(extractBase64FromDataUrl("data:,QUJD,RGVm")).toBe("QUJD");
});

afterEach(() => {
  vi.unstubAllGlobals();
});
