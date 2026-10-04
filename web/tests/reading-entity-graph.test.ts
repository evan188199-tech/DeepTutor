import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const component = readFileSync(
  path.resolve(process.cwd(), "components/reading/ReadingExtensionBar.tsx"),
  "utf8",
);
const tasks = readFileSync(
  path.resolve(process.cwd(), "components/settings/TaskModelsWorkspace.tsx"),
  "utf8",
);
const english = readFileSync(path.resolve(process.cwd(), "locales/en/app.json"), "utf8");
const chinese = readFileSync(path.resolve(process.cwd(), "locales/zh/app.json"), "utf8");

test("the built-in entity-graph action is localized", () => {
  assert.match(component, /extensionId === "entity_graph" && actionId === "build"/);
  assert.match(english, /"Relationship graph": "Relationship graph"/);
  assert.match(chinese, /"Relationship graph": "人物与实体关系图"/);
});

test("the entity-graph task model row is named", () => {
  assert.match(tasks, /reading_entity_graph: \{/);
  assert.match(tasks, /label: "Character & entity graph"/);
  assert.match(english, /"Character & entity graph": "Character & entity graph"/);
  assert.match(chinese, /"Character & entity graph": "人物与实体关系图"/);
});

test("the graph renders through the shared strict Mermaid renderer", () => {
  assert.match(component, /import Mermaid from "@\/components\/Mermaid"/);
  assert.match(component, /String\(result\.payload\.mermaid \|\| ""\)/);
  // Only a chart the server actually produced is rendered; a degraded
  // extraction (empty mermaid) must not draw anything.
  assert.match(component, /graphMermaid \? <Mermaid chart=\{graphMermaid\}/);
});

test("relationship edges show their label and supporting evidence", () => {
  assert.match(component, /result\.payload\.edges/);
  assert.match(component, /String\(edge\.label \|\| ""\)/);
  assert.match(component, /String\(edge\.evidence \|\| ""\)/);
  assert.match(component, /\{edge\.source\} → \{edge\.target\}/);
  assert.match(component, /\{edge\.label\}/);
  assert.match(component, /\{edge\.evidence\}/);
});

test("entity-graph results never inject browser JavaScript or raw HTML", () => {
  assert.doesNotMatch(component, /dangerouslySetInnerHTML|eval\(|new Function/);
});
