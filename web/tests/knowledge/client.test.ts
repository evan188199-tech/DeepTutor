import assert from "node:assert/strict";
import test from "node:test";

import {
  getEmbeddingUsage,
  invalidateKnowledgeCaches,
  knowledgeBaseFilePath,
  knowledgeBaseFilePreviewTextPath,
  listKnowledgeBases,
} from "../../features/knowledge/api/client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function textResponse(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/plain" },
  });
}

interface CapturedRequest {
  url: string;
  init?: RequestInit;
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): { requests: CapturedRequest[]; restore: () => void } {
  const requests: CapturedRequest[] = [];
  const original = globalThis.fetch;
  const stub = async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({ url: String(input), init });
    return handler(input, init);
  };
  (globalThis as { fetch: typeof fetch }).fetch = stub as typeof fetch;
  return {
    requests,
    restore: () => {
      (globalThis as { fetch: typeof fetch }).fetch = original;
    },
  };
}

function installWindow(pathname = "/", search = ""): void {
  (globalThis as { window?: unknown }).window = {
    location: { pathname, search, origin: "http://localhost" },
  };
}

function clearWindow(): void {
  delete (globalThis as { window?: unknown }).window;
}

test("listKnowledgeBases requests the workspace endpoint without resource_library outside the library", async () => {
  const { requests, restore } = stubFetch(async () =>
    jsonResponse(200, [{ id: "kb-1", name: "Papers" }]),
  );
  try {
    assert.deepEqual(await listKnowledgeBases(), [{ id: "kb-1", name: "Papers" }]);
  } finally {
    restore();
  }

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/knowledge-bases?dt_workspace=");
  assert.equal(requests[0].init?.cache, "no-store");
});

test("listKnowledgeBases flags the knowledge library scope with resource_library=true", async () => {
  installWindow("/knowledge-bases");
  const { requests, restore } = stubFetch(async () =>
    jsonResponse(200, { knowledge_bases: [{ name: "Reading" }] }),
  );
  try {
    assert.deepEqual(await listKnowledgeBases(), [{ name: "Reading" }]);
  } finally {
    restore();
    clearWindow();
  }

  assert.equal(
    requests[0].url,
    "/api/knowledge-bases?dt_workspace=&resource_library=true",
  );
});

test("listKnowledgeBases({library: true}) targets the resource library explicitly", async () => {
  const { requests, restore } = stubFetch(async () => jsonResponse(200, []));
  try {
    assert.deepEqual(await listKnowledgeBases({ library: true }), []);
  } finally {
    restore();
  }

  assert.equal(
    requests[0].url,
    "/api/knowledge-bases?resource_library=true&dt_workspace=",
  );
});

test("listKnowledgeBases normalizes object payloads and empty shapes to arrays", async () => {
  let call = 0;
  const { restore } = stubFetch(async () => {
    call += 1;
    if (call === 1) return jsonResponse(200, {});
    return jsonResponse(200, { knowledge_bases: "not-an-array" });
  });
  try {
    assert.deepEqual(await listKnowledgeBases(), []);
    assert.deepEqual(await listKnowledgeBases(), []);
  } finally {
    restore();
  }
});

test("getEmbeddingUsage always hits the wire and never serves from cache", async () => {
  installWindow("/", "?dt_workspace=ws-usage");
  invalidateKnowledgeCaches();
  const { requests, restore } = stubFetch(async () =>
    jsonResponse(200, {
      knowledge_bases: [
        {
          profile_id: "p-1",
          model_id: "m-1",
          name: "Embed",
          workspace_name: "WS",
        },
      ],
    }),
  );
  try {
    const first = await getEmbeddingUsage();
    const second = await getEmbeddingUsage();
    assert.equal(first[0].profile_id, "p-1");
    assert.equal(first[0].workspace_name, "WS");
    assert.deepEqual(first, second);
  } finally {
    restore();
    clearWindow();
  }

  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.url, "/api/knowledge-bases/embedding-usage?dt_workspace=ws-usage");
    assert.equal(request.init?.cache, "no-store");
  }
});

test("4xx responses surface the backend error detail", async () => {
  let call = 0;
  const { restore } = stubFetch(async () => {
    call += 1;
    if (call === 1) {
      return jsonResponse(400, { detail: "Workspace is not accessible" });
    }
    return jsonResponse(500, { detail: "usage backend exploded" });
  });
  try {
    await assert.rejects(listKnowledgeBases(), /Workspace is not accessible/);
    await assert.rejects(getEmbeddingUsage(), /usage backend exploded/);
  } finally {
    restore();
  }
});

test("non-JSON error bodies fall back to the endpoint-specific message", async () => {
  let call = 0;
  const { restore } = stubFetch(async () => {
    call += 1;
    if (call === 1) return textResponse(502, "Bad Gateway");
    return textResponse(429, "rate limited");
  });
  try {
    await assert.rejects(listKnowledgeBases(), /Failed to list knowledge bases/);
    await assert.rejects(getEmbeddingUsage(), /Failed to load embedding model usage/);
  } finally {
    restore();
  }
});

test("knowledgeBaseFilePath builders encode segments and carry the library flag", () => {
  installWindow("/knowledge-bases");
  try {
    assert.equal(
      knowledgeBaseFilePath("Team Notes/2026", "Papers/a.pdf"),
      "/api/knowledge-bases/Team%20Notes%2F2026/files/Papers/a.pdf?resource_library=true",
    );
    assert.equal(
      knowledgeBaseFilePreviewTextPath("kb", "notes/x.md"),
      "/api/knowledge-bases/kb/file-preview-text/notes/x.md?resource_library=true",
    );
  } finally {
    clearWindow();
  }
  assert.equal(
    knowledgeBaseFilePath("Team Notes/2026", "Papers/a.pdf"),
    "/api/knowledge-bases/Team%20Notes%2F2026/files/Papers/a.pdf",
  );
});

test("listKnowledgeBases caches per scope and invalidateKnowledgeCaches forces a refetch", async () => {
  installWindow("/", "?dt_workspace=ws-cache");
  invalidateKnowledgeCaches();
  let payload: unknown = { knowledge_bases: [{ name: "first" }] };
  const { requests, restore } = stubFetch(async () =>
    jsonResponse(200, payload),
  );
  try {
    assert.deepEqual(await listKnowledgeBases(), [{ name: "first" }]);
    assert.deepEqual(await listKnowledgeBases(), [{ name: "first" }]);
    assert.equal(requests.length, 1);

    invalidateKnowledgeCaches();
    payload = { knowledge_bases: [{ name: "second" }] };
    assert.deepEqual(await listKnowledgeBases(), [{ name: "second" }]);
    assert.equal(requests.length, 2);

    assert.deepEqual(await listKnowledgeBases({ force: true }), [
      { name: "second" },
    ]);
    assert.equal(requests.length, 3);

    assert.deepEqual(await listKnowledgeBases({ library: true }), [
      { name: "second" },
    ]);
    assert.equal(requests.length, 4);
    assert.deepEqual(await listKnowledgeBases(), [{ name: "second" }]);
    assert.equal(requests.length, 4);
  } finally {
    restore();
    invalidateKnowledgeCaches();
    clearWindow();
  }

  assert.match(requests[0].url, /^\/api\/knowledge-bases\?dt_workspace=ws-cache/);
  assert.match(requests[3].url, /resource_library=true/);
});
