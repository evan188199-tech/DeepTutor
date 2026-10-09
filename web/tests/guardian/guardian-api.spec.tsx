import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));

import {
  authorizeGuardianRelationship,
  getGuardianMaterials,
  getGuardianReport,
  getGuardianRestrictions,
  listAdminGuardianRelationships,
  listGuardianRelationships,
  resetLearnerCredentials,
  revokeGuardianRelationship,
  revokeMyGuardianRelationship,
  saveGuardianMaterials,
  saveGuardianRestrictions,
} from "@/lib/guardian-api";

const reply = (value: unknown, ok = true, status = ok ? 200 : 400) => ({
  ok,
  status,
  json: async () => value,
});
const lastCall = () =>
  mocks.fetch.mock.calls[mocks.fetch.mock.calls.length - 1] as [
    string,
    RequestInit | undefined,
  ];

const relationship = {
  id: "rel-1",
  guardian_user_id: "g1",
  guardian_username: "Guardian Grace",
  learner_user_id: "l1",
  learner_username: "Learner Lou",
  permissions: ["view_reports"],
  revoked_at: null,
};
const restrictions = {
  age_band: "9-12" as const,
  allow_upload: false,
  allowed_surfaces: ["chat" as const],
  extensions: [],
};

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.fetch.mockResolvedValue(reply({}));
});

it("lists relationships from the me and admin guardianship endpoints", async () => {
  mocks.fetch.mockResolvedValue(reply({ relationships: [relationship] }));
  await expect(listGuardianRelationships()).resolves.toEqual([relationship]);
  const [meUrl, meInit] = lastCall();
  expect(meUrl).toBe("/api/multi-user/me/guardianships");
  expect(meInit?.method).toBeUndefined();
  await expect(listAdminGuardianRelationships()).resolves.toEqual([
    relationship,
  ]);
  expect(lastCall()[0]).toBe("/api/multi-user/guardians");
});

it("authorizes a guardian by posting the permission set and unwrapping the envelope", async () => {
  mocks.fetch.mockResolvedValue(reply({ relationship }));
  await expect(
    authorizeGuardianRelationship("g1", "l1", ["view_reports"]),
  ).resolves.toEqual(relationship);
  const [url, init] = lastCall();
  expect(url).toBe("/api/multi-user/guardians");
  expect(init?.method).toBe("POST");
  expect(init?.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(String(init?.body))).toEqual({
    guardian_user_id: "g1",
    learner_user_id: "l1",
    permissions: ["view_reports"],
  });
});

it("deletes guardian and self revocations with an encoded relationship id", async () => {
  await revokeGuardianRelationship("rel/1 a");
  const [adminUrl, adminInit] = lastCall();
  expect(adminUrl).toBe("/api/multi-user/guardians/rel%2F1%20a");
  expect(adminInit?.method).toBe("DELETE");
  await revokeMyGuardianRelationship("rel 2");
  const [meUrl, meInit] = lastCall();
  expect(meUrl).toBe("/api/multi-user/me/guardianships/rel%202");
  expect(meInit?.method).toBe("DELETE");
});

it("unwraps the report, materials, and restrictions envelopes", async () => {
  const report = {
    learner: { id: "l1", username: "Learner Lou", disabled: false },
    assigned_materials: [],
    grant_summary: { model_count: 1, knowledge_base_count: 2, skill_count: 3 },
  };
  mocks.fetch.mockResolvedValue(reply(report));
  await expect(getGuardianReport("l1")).resolves.toEqual(report);
  expect(lastCall()[0]).toBe("/api/multi-user/learners/l1/guardian-report");

  mocks.fetch.mockResolvedValue(
    reply({
      materials: [{ book_id: "b1", assigned: true, permission: "read" }],
    }),
  );
  await expect(getGuardianMaterials("l1")).resolves.toEqual([
    { book_id: "b1", assigned: true, permission: "read" },
  ]);
  expect(lastCall()[0]).toBe("/api/multi-user/learners/l1/materials");

  await saveGuardianMaterials("l1", ["b1", "b2"]);
  const [putUrl, putInit] = lastCall();
  expect(putUrl).toBe("/api/multi-user/learners/l1/materials");
  expect(putInit?.method).toBe("PUT");
  expect(JSON.parse(String(putInit?.body))).toEqual({
    book_ids: ["b1", "b2"],
  });

  const payload = {
    restrictions,
    available_extensions: [
      { id: "ext-1", name: "Math Pack", version: "1.0" },
    ],
  };
  mocks.fetch.mockResolvedValue(reply(payload));
  await expect(getGuardianRestrictions("l1")).resolves.toEqual(payload);
  expect(lastCall()[0]).toBe("/api/multi-user/learners/l1/restrictions");

  mocks.fetch.mockResolvedValue(reply({ restrictions }));
  await expect(saveGuardianRestrictions("l1", restrictions)).resolves.toEqual(
    restrictions,
  );
  const [saveUrl, saveInit] = lastCall();
  expect(saveUrl).toBe("/api/multi-user/learners/l1/restrictions");
  expect(saveInit?.method).toBe("PUT");
  expect(JSON.parse(String(saveInit?.body))).toEqual(restrictions);
});

it("posts only the new password on credential reset", async () => {
  await resetLearnerCredentials("l1", "brand-new-passphrase");
  const [url, init] = lastCall();
  expect(url).toBe("/api/multi-user/learners/l1/credentials/reset");
  expect(init?.method).toBe("POST");
  expect(init?.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(String(init?.body))).toEqual({
    new_password: "brand-new-passphrase",
  });
});

it("surfaces the API detail string as the rejection message", async () => {
  mocks.fetch.mockResolvedValue(
    reply({ detail: "Not authorized for this learner" }, false, 403),
  );
  await expect(getGuardianReport("l1")).rejects.toThrow(
    "Not authorized for this learner",
  );
});

it("falls back to a generic message when the error envelope has no detail string", async () => {
  mocks.fetch.mockResolvedValue(
    reply({ detail: { message: "boom" } }, false, 500),
  );
  await expect(listGuardianRelationships()).rejects.toThrow("Request failed");

  mocks.fetch.mockResolvedValue(reply("gateway timeout", false, 504));
  await expect(listGuardianRelationships()).rejects.toThrow("Request failed");
});

it("falls back to a generic message when the error body is not JSON", async () => {
  mocks.fetch.mockResolvedValue({
    ok: false,
    status: 502,
    json: async () => {
      throw new SyntaxError("unexpected token");
    },
  });
  await expect(revokeGuardianRelationship("rel-1")).rejects.toThrow(
    "Request failed",
  );
});

it("resolves void saves even when the success response has no body", async () => {
  mocks.fetch.mockResolvedValue({
    ok: true,
    status: 204,
    json: async () => {
      throw new SyntaxError("no content");
    },
  });
  await expect(saveGuardianMaterials("l1", [])).resolves.toBeUndefined();
  const [url, init] = lastCall();
  expect(url).toBe("/api/multi-user/learners/l1/materials");
  expect(init?.method).toBe("PUT");
});
