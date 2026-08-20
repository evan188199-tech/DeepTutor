import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function readWorkspaceSource(relativePath: string): string {
  return readFileSync(path.resolve(process.cwd(), relativePath), "utf8");
}

test("interactive learning outcomes flow from the iframe into Book progress", () => {
  const api = readWorkspaceSource("lib/book-api.ts");
  const viewer = readWorkspaceSource("components/visualize/VisualizationViewer.tsx");
  const interactive = readWorkspaceSource(
    "app/(workspace)/book/components/blocks/InteractiveBlock.tsx",
  );
  const page = readWorkspaceSource("app/(workspace)/book/page.tsx");

  assert.match(api, /recordLearningActivity/);
  assert.match(api, /\/books\/learning-activity/);
  assert.match(viewer, /parseIframeLearningOutcome/);
  assert.match(interactive, /learning_objectives/);
  assert.match(interactive, /onLearningOutcome/);
  assert.match(page, /bookApi\.recordLearningActivity/);
});
