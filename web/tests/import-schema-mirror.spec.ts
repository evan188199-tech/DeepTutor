import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Cross-end upload contract: the browser adapters normalize external chat
// histories to `NormalizedMessage` / `NormalizedSession` (web/lib/chat-import/
// types.ts) and POST them to `/api/imports/chat-history`, where the backend
// `ImportedMessage` / `ImportedSession` Pydantic models
// (deeptutor/api/routers/imports.py) validate them. There is no shared schema
// between the two ends, so this spec parses both files and asserts the web
// field sets stay a subset of the backend ones. It is red in both break
// directions: a backend field removal and a web field addition both fail.

// Vitest resolves the suite from the `web/` root, so repo paths are cwd-based.
const webRoot = process.cwd();

const typesSource = fs.readFileSync(
  path.join(webRoot, "lib/chat-import/types.ts"),
  "utf8",
);
const backendSource = fs.readFileSync(
  path.join(webRoot, "../deeptutor/api/routers/imports.py"),
  "utf8",
);

/** Top-level property names of a `export interface <name> { ... }` block. */
function tsInterfaceFields(source: string, name: string): string[] {
  const match = new RegExp(`export interface ${name}\\s*\\{`).exec(source);
  if (!match) throw new Error(`interface ${name} not found in types.ts`);
  const open = match.index + match[0].length - 1;
  let depth = 0;
  let end = -1;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  if (end === -1) throw new Error(`interface ${name} is never closed`);
  const fields: string[] = [];
  for (const raw of source.slice(open + 1, end).split("\n")) {
    const line = raw.replace(/\/\/.*$/, "").trim();
    if (!line || line.startsWith("*") || line.startsWith("/*")) continue;
    const field = /^(\w+)\??\s*:/.exec(line);
    if (field) fields.push(field[1]);
  }
  if (!fields.length) throw new Error(`interface ${name}: no fields parsed`);
  return fields;
}

/** Field names of a `class <name>(BaseModel):` block until dedent. */
function pyModelFields(source: string, name: string): string[] {
  const match = new RegExp(`^class ${name}\\(BaseModel\\):\\n`, "m").exec(source);
  if (!match) throw new Error(`model ${name} not found in imports.py`);
  const fields: string[] = [];
  for (const line of source.slice(match.index + match[0].length).split("\n")) {
    if (line.trim() && !line.startsWith("    ")) break;
    const field = /^    (\w+)\s*:/.exec(line);
    if (field) fields.push(field[1]);
  }
  if (!fields.length) throw new Error(`model ${name}: no fields parsed`);
  return fields;
}

function expectWebSubsetOfBackend(
  webFields: string[],
  backendFields: string[],
  payload: string,
  model: string,
): void {
  const webOnly = webFields.filter((field) => !backendFields.includes(field));
  expect(
    webOnly,
    `${payload} has fields the backend ${model} does not accept — the web ` +
      `side grew a field without a matching backend one, or the backend ` +
      `dropped a field the upload still sends. ` +
      `web=[${webFields.join(", ")}] backend=[${backendFields.join(", ")}]`,
  ).toEqual([]);
}

describe("import upload schema mirror (web Normalized* ⊆ backend Imported*)", () => {
  it("every NormalizedMessage field exists on the backend ImportedMessage", () => {
    expectWebSubsetOfBackend(
      tsInterfaceFields(typesSource, "NormalizedMessage"),
      pyModelFields(backendSource, "ImportedMessage"),
      "NormalizedMessage",
      "ImportedMessage",
    );
  });

  it("every NormalizedSession field exists on the backend ImportedSession", () => {
    expectWebSubsetOfBackend(
      tsInterfaceFields(typesSource, "NormalizedSession"),
      pyModelFields(backendSource, "ImportedSession"),
      "NormalizedSession",
      "ImportedSession",
    );
  });
});
