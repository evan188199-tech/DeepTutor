import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

async function readSource(relativePath: string): Promise<string> {
  return readFile(join(process.cwd(), relativePath), "utf8");
}

test("MN4 writeback API exposes the review state machine", async () => {
  const source = await readSource("lib/immersive-reading-api.ts");

  assert.match(source, /export type MN4WritebackStatus/);
  assert.match(source, /"pending_confirmation"/);
  assert.match(source, /"rejected"/);
  assert.match(source, /"applying"/);
  assert.match(source, /"conflicted"/);
  assert.match(source, /\/mn4\/writebacks/);
  assert.match(source, /\/mn4\/writebacks\/approve/);
  assert.match(source, /\/mn4\/writebacks\/reject/);
  assert.match(source, /\/mn4\/writebacks\/pull/);
  assert.match(source, /\/mn4\/writebacks\/receipt/);
  assert.match(source, /document_id: source\?\.documentId \|\| ""/);
  assert.match(source, /source_object_id: source\?\.sourceObjectId \|\| ""/);
});

test("reading workspace exposes MN4 review and tags translations with their source", async () => {
  const page = await readSource("app/(workspace)/immersive-reading/page.tsx");
  const component = await readSource("components/immersive-reading/MN4WritebackReview.tsx");

  assert.match(page, /"sync-review"/);
  assert.match(page, /MN4WritebackReview/);
  assert.match(page, /refreshMN4Writebacks/);
  assert.match(page, /mn4WritebackApi\.approve/);
  assert.match(page, /mn4WritebackApi\.reject/);
  assert.match(page, /documentId,\s*sourceObjectId: currentSection\?\.id \|\| documentId/);
  assert.match(component, /status === "pending_confirmation"/);
  assert.match(component, /role="status"/);
  assert.match(component, /role="alert"/);
  assert.match(component, /No pending MarginNote 4 writebacks\./);
  assert.match(component, /onApprove/);
  assert.match(component, /onReject/);
});

test("MN4 review UI has English and Chinese copy", async () => {
  const english = JSON.parse(await readSource("locales/en/app.json")) as Record<string, string>;
  const chinese = JSON.parse(await readSource("locales/zh/app.json")) as Record<string, string>;
  const keys = [
    "Sync review",
    "MarginNote 4 Sync Review",
    "Review each generated item before it is written to MarginNote 4.",
    "Loading MarginNote 4 writebacks...",
    "No pending MarginNote 4 writebacks.",
    "Approve all",
    "Approve",
    "Reject",
  ];

  for (const key of keys) {
    assert.equal(english[key], key);
    assert.ok(chinese[key]);
  }
});
