import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  RAG_PIPELINE_PROVIDERS,
  ragPipelineConfigPath,
  getGraphRagConfig,
  getImaConfig,
  getLlamaIndexConfig,
  getLightRagConfig,
  getLightRagServerConfig,
  getPageIndexConfig,
  updateGraphRagConfig,
  updateImaConfig,
  updateLlamaIndexConfig,
  updateLightRagConfig,
  updateLightRagServerConfig,
  updatePageIndexConfig,
  type RagPipelineProvider,
} from "../features/knowledge/api/client";

const CONTRACT_CONFIG_ROUTES: Record<RagPipelineProvider, string> = {
  graphrag: "/api/knowledge-bases/rag-pipelines/graphrag/config",
  ima: "/api/knowledge-bases/rag-pipelines/ima/config",
  "lightrag-server": "/api/knowledge-bases/rag-pipelines/lightrag-server/config",
  lightrag: "/api/knowledge-bases/rag-pipelines/lightrag/config",
  llamaindex: "/api/knowledge-bases/rag-pipelines/llamaindex/config",
  pageindex: "/api/knowledge-bases/rag-pipelines/pageindex/config",
};

function loadContractPaths(): string[] {
  const contractPath = path.join(
    process.cwd(),
    "contracts",
    "schema",
    "openapi.json",
  );
  const spec = JSON.parse(fs.readFileSync(contractPath, "utf8")) as {
    paths: Record<string, unknown>;
  };
  return Object.keys(spec.paths);
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = original;
  };
}

test("provider union covers exactly the six backend literal config routes", () => {
  assert.deepEqual(
    [...RAG_PIPELINE_PROVIDERS].sort(),
    [
      "graphrag",
      "ima",
      "lightrag",
      "lightrag-server",
      "llamaindex",
      "pageindex",
    ],
  );
});

test("contract declares each provider config route literally, without a parameterized route", () => {
  const declared = loadContractPaths().filter(
    (route) => route.includes("/rag-pipelines/") && route.endsWith("/config"),
  );
  assert.deepEqual(
    declared.sort(),
    Object.values(CONTRACT_CONFIG_ROUTES).sort(),
  );
  assert.equal(
    declared.filter((route) => route.includes("{provider}")).length,
    0,
    "backend /config routes are literal; a {provider} parameterization would invalidate this map",
  );
});

test("config path helper returns the literal route for every provider", () => {
  for (const provider of RAG_PIPELINE_PROVIDERS) {
    assert.equal(ragPipelineConfigPath(provider), CONTRACT_CONFIG_ROUTES[provider]);
  }
});

test("unknown provider fails fast instead of building a doomed URL", () => {
  assert.throws(
    () => ragPipelineConfigPath("definitely-not-a-provider"),
    /Unknown RAG pipeline provider: definitely-not-a-provider/,
  );
});

test("invalid provider values are rejected by the literal union type", () => {
  // @ts-expect-error values outside the provider union must not typecheck
  const invalid: RagPipelineProvider = "no-such-engine";
  assert.throws(() => ragPipelineConfigPath(invalid));
});

test("engine config reads and writes target per-provider literal routes", async () => {
  const requestedUrls: string[] = [];
  const restore = stubFetch(async (input) => {
    requestedUrls.push(String(input));
    return new Response(JSON.stringify({ version: 1 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });

  try {
    await getGraphRagConfig();
    await getImaConfig();
    await getLightRagConfig();
    await getLightRagServerConfig();
    await getLlamaIndexConfig();
    await getPageIndexConfig();

    await updateGraphRagConfig({});
    await updateImaConfig({ api_key: "k" });
    await updateLightRagConfig({});
    await updateLightRagServerConfig({ server_url: "http://lightrag.local" });
    await updateLlamaIndexConfig({});
    await updatePageIndexConfig({ api_key: "k" });
  } finally {
    restore();
  }

  assert.deepEqual(
    requestedUrls.sort(),
    RAG_PIPELINE_PROVIDERS.flatMap((provider) => [
      `${CONTRACT_CONFIG_ROUTES[provider]}?dt_workspace=`,
      `${CONTRACT_CONFIG_ROUTES[provider]}?dt_workspace=`,
    ]).sort(),
  );
  assert.ok(
    requestedUrls.every((url) => !url.includes("%7Bprovider%7D")),
    "no provider placeholder may leak into a request URL",
  );
});
