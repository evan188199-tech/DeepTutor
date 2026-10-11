import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  checkAppUpdate,
  fetchAppUpdateJob,
  fetchAppUpdateStatus,
  requestAppUpdate,
  setAppUpdateChecks,
  subscribeAppUpdateStatus,
  updateJobIsActive,
} from "../lib/app-update";

const statusPayload = {
  current_version: "1.6.1",
  check_enabled: true,
  checked_at: "2026-08-30T00:00:00Z",
  cached: false,
  check_error: "",
  update_available: true,
  release: {
    version: "1.7.0",
    name: "DeepTutor 1.7",
    published_at: "2026-08-30T00:00:00Z",
    url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
    excerpt: "A stable release.",
    migration_warning: false,
  },
  installation: {
    mode: "pypi",
    automatic_update: true,
    command: "pip install -U deeptutor",
    reason: "",
  },
  launcher_managed: true,
  is_admin: true,
  job: null,
} as const;

const jobPayload = {
  id: "job-1",
  status: "pending",
  current_version: "1.6.1",
  target_version: "1.7.0",
  created_at: "2026-08-30T00:00:00Z",
  started_at: null,
  finished_at: null,
  error: null,
  restart_count: 0,
} as const;

test("app update client uses the canonical system routes", async () => {
  const requests: Array<{ path: string; method: string; body?: string }> = [];
  const signals: Array<{ version?: string; error: string }> = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) => {
    signals.push({
      version: signal.status?.current_version,
      error: signal.error,
    });
  });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    requests.push({
      path: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : undefined,
    });
    const updateRequest =
      String(input) === "/api/system/update?dt_workspace=" && init?.method === "POST";
    const body =
      String(input).endsWith("/job?dt_workspace=") || updateRequest
        ? jobPayload
        : statusPayload;
    return new Response(JSON.stringify(body), {
      status: updateRequest ? 202 : 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    assert.equal((await fetchAppUpdateStatus()).current_version, "1.6.1");
    assert.equal((await checkAppUpdate()).release?.version, "1.7.0");
    assert.equal((await setAppUpdateChecks(false)).check_enabled, true);
    assert.equal((await requestAppUpdate()).id, "job-1");
    assert.equal((await fetchAppUpdateJob())?.id, "job-1");
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(
    requests.map(({ path, method }) => ({ path, method })),
    [
      { path: "/api/system/update?dt_workspace=", method: "GET" },
      { path: "/api/system/update/check?dt_workspace=", method: "POST" },
      { path: "/api/system/update/settings?dt_workspace=", method: "PUT" },
      { path: "/api/system/update?dt_workspace=", method: "POST" },
      { path: "/api/system/update/job?dt_workspace=", method: "GET" },
    ],
  );
  assert.equal(requests[2]?.body, JSON.stringify({ enabled: false }));
  assert.equal(
    requests[3]?.body,
    JSON.stringify({ confirmation: "update-and-restart" }),
  );
  assert.deepEqual(signals, [
    { version: "1.6.1", error: "" },
    { version: "1.6.1", error: "" },
    { version: "1.6.1", error: "" },
  ]);
});

test("failed version checks notify compact status surfaces", async () => {
  const signals: string[] = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) =>
    signals.push(signal.error),
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "Unable to check for updates" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    });

  try {
    await assert.rejects(checkAppUpdate(), /Unable to check for updates/);
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(signals, ["Unable to check for updates"]);
});

test("app update client preserves FastAPI error details", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ detail: "Finish the active conversation." }),
      {
        status: 409,
        headers: { "content-type": "application/json" },
      },
    );

  try {
    await assert.rejects(requestAppUpdate(), /Finish the active conversation/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("only non-terminal jobs remain active", () => {
  for (const status of [
    "pending",
    "handoff",
    "running",
    "restarting",
  ] as const) {
    assert.equal(updateJobIsActive(status), true);
  }
  assert.equal(updateJobIsActive("succeeded"), false);
  assert.equal(updateJobIsActive("failed"), false);
});

test("background check failures keep the status usable and surface check_error", async () => {
  const signals: Array<{ version?: string; error: string }> = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) => {
    signals.push({
      version: signal.status?.current_version,
      error: signal.error,
    });
  });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        ...statusPayload,
        cached: true,
        check_error: "GitHub API rate limit exceeded",
        update_available: false,
        release: null,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );

  try {
    const status = await fetchAppUpdateStatus();
    assert.equal(status.check_error, "GitHub API rate limit exceeded");
    assert.equal(status.update_available, false);
    assert.equal(status.release, null);
    assert.equal(status.current_version, "1.6.1");
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(signals, [
    { version: "1.6.1", error: "GitHub API rate limit exceeded" },
  ]);
});

test("non-JSON failures degrade to the status-only update error", async () => {
  const signals: string[] = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) =>
    signals.push(signal.error),
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response("<html>Service Unavailable</html>", {
      status: 503,
      headers: { "content-type": "text/html" },
    });

  try {
    await assert.rejects(
      checkAppUpdate(),
      /Update request failed \(HTTP 503\)/,
    );
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(signals, ["Update request failed (HTTP 503)"]);
});

test("structured FastAPI details fall back to the status-only update error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: { reason: "not updatable" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    });

  try {
    await assert.rejects(
      requestAppUpdate(),
      /Update request failed \(HTTP 409\)/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("unreadable status payloads reject and notify compact surfaces", async () => {
  const signals: string[] = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) =>
    signals.push(signal.error),
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response("not json", {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  let caught: unknown;
  try {
    await fetchAppUpdateStatus();
  } catch (error) {
    caught = error;
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.ok(caught instanceof Error);
  assert.deepEqual(signals, [caught.message]);
});

test("update job snapshots may be absent", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(null), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  try {
    assert.equal(await fetchAppUpdateJob(), null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("unsubscribed compact surfaces stop receiving update signals", async () => {
  const signals: Array<{ version?: string; error: string }> = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) => {
    signals.push({ version: signal.status?.current_version, error: signal.error });
  });
  unsubscribe();

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(statusPayload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  try {
    await fetchAppUpdateStatus();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(signals, []);
});

test("client forwards abort signals to update requests", async () => {
  const seenSignals: Array<AbortSignal | null | undefined> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    seenSignals.push(init?.signal);
    return new Response(JSON.stringify(statusPayload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const controller = new AbortController();

  try {
    await fetchAppUpdateStatus(controller.signal);
    await fetchAppUpdateJob(controller.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(seenSignals[0], controller.signal);
  assert.equal(seenSignals[1], controller.signal);
});

test("status payloads follow the backend app_update contract", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        current_version: "1.6.1",
        check_enabled: true,
        checked_at: "2026-08-30T00:00:00Z",
        cached: false,
        check_error: "",
        update_available: true,
        release: {
          version: "1.7.0",
          name: "DeepTutor 1.7",
          published_at: "2026-08-30T00:00:00Z",
          url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
          excerpt: "Use the new updater with one confirmation.",
          migration_warning: true,
        },
        installation: {
          mode: "source",
          automatic_update: false,
          command: "git pull && pip install -e .",
          reason: "Source checkouts update via git pull.",
        },
        launcher_managed: false,
        is_admin: false,
        job: jobPayload,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );

  let status: Awaited<ReturnType<typeof fetchAppUpdateStatus>> | undefined;
  try {
    status = await fetchAppUpdateStatus();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.ok(status);
  assert.equal(status.release?.version, "1.7.0");
  assert.equal(status.release?.name, "DeepTutor 1.7");
  assert.equal(status.release?.published_at, "2026-08-30T00:00:00Z");
  assert.equal(
    status.release?.url,
    "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
  );
  assert.equal(
    status.release?.excerpt,
    "Use the new updater with one confirmation.",
  );
  assert.equal(status.release?.migration_warning, true);
  assert.equal(status.installation.mode, "source");
  assert.equal(status.installation.automatic_update, false);
  assert.equal(status.installation.command, "git pull && pip install -e .");
  assert.equal(status.launcher_managed, false);
  assert.equal(status.is_admin, false);
  assert.equal(status.job?.status, "pending");
  assert.equal(updateJobIsActive("handoff"), true);
});

test("sidebar presents the update state as a clickable status dot", () => {
  const badge = readFileSync(
    path.join(process.cwd(), "components", "sidebar", "VersionBadge.tsx"),
    "utf8",
  );
  const shell = readFileSync(
    path.join(process.cwd(), "components", "sidebar", "SidebarShell.tsx"),
    "utf8",
  );

  assert.match(badge, /subscribeAppUpdateStatus/);
  assert.match(badge, /label: t\("Up to date"\)/);
  assert.match(badge, /bg-amber-500/);
  assert.match(badge, /bg-red-500/);
  assert.match(badge, /href="\/settings\/about"/);
  assert.match(badge, /aria-label=\{state\.label/);
  assert.doesNotMatch(badge, /displayTag/);
  assert.doesNotMatch(shell, /GitHubMarkLink/);
  assert.doesNotMatch(shell, /GITHUB_REPO_URL/);
});
