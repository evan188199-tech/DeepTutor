import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchAdminBooks,
  fetchAdminResources,
  fetchBookPermission,
  fetchUserGrant,
  saveBookPermission,
  saveUserGrant,
} from "../../../features/multi-user/api";
import type {
  AdminBook,
  BookPermission,
  GrantPayload,
  MultiUserResources,
} from "../../../features/multi-user/types";

type RecordedCall = {
  input: string;
  method: string;
  contentType: string | null;
  body: string | null;
  credentials: string | undefined;
};

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): { restore: () => void; calls: RecordedCall[] } {
  const original = globalThis.fetch;
  const calls: RecordedCall[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (input, init) => {
    calls.push({
      input: String(input),
      method: init?.method ?? "GET",
      contentType: new Headers(init?.headers).get("content-type"),
      body: typeof init?.body === "string" ? init.body : null,
      credentials: init?.credentials,
    });
    return handler(input, init);
  };
  return {
    calls,
    restore: () => {
      (globalThis as { fetch: typeof fetch }).fetch = original;
    },
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const grant: GrantPayload = {
  version: 1,
  user_id: "u-1",
  models: { llm: [] },
  knowledge_bases: [],
  skills: [],
  partners: [],
  enabled_tools: null,
  mcp_tools: null,
  exec_enabled: null,
  learning_policy: null,
};

const permission: BookPermission = {
  create: true,
  default: "read",
  books: { "book-9": "edit" },
};

const resources: MultiUserResources = {
  models: {
    llm: [
      {
        profile_id: "p1",
        name: "Default",
        models: [{ model_id: "m1", name: "Model One", model: "model-one" }],
      },
    ],
  },
  knowledge_bases: [{ resource_id: "kb1", name: "KB", source: "admin" }],
  skills: [{ name: "summarize" }],
  partners: [{ partner_id: "pa1", name: "Partner" }],
  reading_materials: [
    {
      material_id: "rm1",
      title: "Material",
      filename: "material.pdf",
      render_mode: "pdf",
    },
  ],
  reading_extensions: [{ id: "ext1", name: "Ext", version: "1.0" }],
  tools: [{ name: "search" }],
  mcp_tools: [{ name: "fetch", kind: "mcp" }],
};

const books: AdminBook[] = [
  { book_id: "b1", title: "Shared", status: "ready", updated_at: 42 },
];

test("fetchAdminResources GETs the admin resources endpoint and returns the payload", async () => {
  const { restore, calls } = stubFetch(async () => jsonResponse(200, resources));
  try {
    const result = await fetchAdminResources();
    assert.deepEqual(result, resources);
    assert.deepEqual(calls, [
      {
        input: "/api/multi-user/admin/resources?dt_workspace=",
        method: "GET",
        contentType: null,
        body: null,
        credentials: "include",
      },
    ]);
  } finally {
    restore();
  }
});

test("fetchUserGrant encodes the user id into the grants path and unwraps grant", async () => {
  const { restore, calls } = stubFetch(async () =>
    jsonResponse(200, { grant }),
  );
  try {
    const result = await fetchUserGrant("u 1/b?");
    assert.deepEqual(result, grant);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, "GET");
    assert.equal(
      calls[0].input,
      "/api/multi-user/users/u%201%2Fb%3F/grants?dt_workspace=",
    );
  } finally {
    restore();
  }
});

test("saveUserGrant PUTs the grant envelope and returns the saved grant", async () => {
  const saved: GrantPayload = { ...grant, version: 2 };
  const { restore, calls } = stubFetch(async () =>
    jsonResponse(200, { grant: saved }),
  );
  try {
    const result = await saveUserGrant("u-1", grant);
    assert.deepEqual(result, saved);
    assert.deepEqual(calls, [
      {
        input: "/api/multi-user/users/u-1/grants?dt_workspace=",
        method: "PUT",
        contentType: "application/json",
        body: JSON.stringify({ grant }),
        credentials: "include",
      },
    ]);
  } finally {
    restore();
  }
});

test("fetchAdminBooks GETs the admin books endpoint and unwraps the books array", async () => {
  const { restore, calls } = stubFetch(async () => jsonResponse(200, { books }));
  try {
    const result = await fetchAdminBooks();
    assert.deepEqual(result, books);
    assert.deepEqual(calls, [
      {
        input: "/api/multi-user/admin/books?dt_workspace=",
        method: "GET",
        contentType: null,
        body: null,
        credentials: "include",
      },
    ]);
  } finally {
    restore();
  }
});

test("fetchBookPermission encodes the user id and unwraps the permission", async () => {
  const { restore, calls } = stubFetch(async () =>
    jsonResponse(200, { permission }),
  );
  try {
    const result = await fetchBookPermission("u 2");
    assert.deepEqual(result, permission);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, "GET");
    assert.equal(
      calls[0].input,
      "/api/multi-user/users/u%202/book-permission?dt_workspace=",
    );
  } finally {
    restore();
  }
});

test("saveBookPermission PUTs the permission object itself and returns it", async () => {
  const { restore, calls } = stubFetch(async () =>
    jsonResponse(200, { permission }),
  );
  try {
    const result = await saveBookPermission("u-2", permission);
    assert.deepEqual(result, permission);
    assert.deepEqual(calls, [
      {
        input: "/api/multi-user/users/u-2/book-permission?dt_workspace=",
        method: "PUT",
        contentType: "application/json",
        body: JSON.stringify(permission),
        credentials: "include",
      },
    ]);
  } finally {
    restore();
  }
});

test("error envelope detail is surfaced as the thrown message", async () => {
  const { restore } = stubFetch(async () =>
    jsonResponse(403, { detail: "Admin only" }),
  );
  try {
    await assert.rejects(fetchAdminResources(), {
      message: "Admin only",
    });
    await assert.rejects(fetchUserGrant("u-1"), {
      message: "Admin only",
    });
  } finally {
    restore();
  }
});

test("a non-JSON error body falls back to the call's own failure message", async () => {
  const { restore } = stubFetch(
    async () => new Response("<html>boom</html>", { status: 500 }),
  );
  try {
    await assert.rejects(fetchUserGrant("u-1"), {
      message: "Failed to load user grant",
    });
    await assert.rejects(saveUserGrant("u-1", grant), {
      message: "Failed to save user grant",
    });
    await assert.rejects(fetchBookPermission("u-1"), {
      message: "Failed to load book permission",
    });
    await assert.rejects(saveBookPermission("u-1", permission), {
      message: "Failed to save book permission",
    });
    await assert.rejects(fetchAdminBooks(), {
      message: "Failed to load shared books",
    });
  } finally {
    restore();
  }
});

test("an error envelope without a detail still uses the fallback message", async () => {
  const { restore } = stubFetch(async () => jsonResponse(500, { detail: null }));
  try {
    await assert.rejects(fetchAdminResources(), {
      message: "Failed to load assignable resources",
    });
  } finally {
    restore();
  }
});

test("network failure on reads propagates without retrying", async () => {
  const original = globalThis.fetch;
  let attempts = 0;
  (globalThis as { fetch: typeof fetch }).fetch = async () => {
    attempts += 1;
    throw new TypeError("network down");
  };
  try {
    await assert.rejects(fetchAdminResources(), {
      message: "network down",
    });
    await assert.rejects(fetchUserGrant("u-1"), { name: "TypeError" });
    assert.equal(attempts, 2);
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

test("network failure on writes propagates unchanged", async () => {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = async () => {
    throw new TypeError("socket hung up");
  };
  try {
    await assert.rejects(saveUserGrant("u-1", grant), {
      name: "TypeError",
      message: "socket hung up",
    });
    await assert.rejects(saveBookPermission("u-1", permission), {
      message: "socket hung up",
    });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});
