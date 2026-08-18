import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

test("PWA manifest and service worker expose an offline shell", async () => {
  const manifest = JSON.parse(
    await readFile(join(process.cwd(), "public/manifest.json"), "utf8"),
  );
  const serviceWorker = await readFile(join(process.cwd(), "public/sw.js"), "utf8");
  const layout = await readFile(join(process.cwd(), "app/layout.tsx"), "utf8");

  assert.equal(manifest.name, "DeepTutor");
  assert.equal(manifest.display, "standalone");
  assert.ok(manifest.icons.length >= 1);
  assert.match(serviceWorker, /caches\.open\(CACHE_NAME\)/);
  assert.match(serviceWorker, /request\.method !== "GET"/);
  assert.match(serviceWorker, /pathname\.startsWith\("\/api\/"\)/);
  assert.match(serviceWorker, /request\.mode === "navigate"/);
  assert.match(layout, /manifest: "\/manifest\.json"/);
  assert.match(layout, /navigator\.serviceWorker\.register\('\/sw\.js'\)/);
  assert.doesNotMatch(layout, /userScalable:\s*false/);
});
