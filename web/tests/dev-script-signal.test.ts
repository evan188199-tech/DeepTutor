import test from "node:test";
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

/**
 * scripts/dev.mjs forwards SIGINT/SIGTERM/SIGHUP to `next dev` and re-raises
 * the child's fatal signal on itself, so the shell sees the wrapper die the
 * same death as the server. The forwarding listeners used to swallow that
 * re-raised signal — `child.kill()` on the already-dead child is a no-op and
 * nothing called `process.exit` — so after the child died from a signal the
 * `node ./scripts/dev.mjs` process stayed alive forever (signal audit #14).
 * These tests exercise the real script against a stub `next` binary; no real
 * dev server is started. Signal-death semantics are POSIX, so skip win32.
 */

// The unfixed wrapper never exits on these paths, so this bound is the
// regression signal: the wrapper must follow its child down within it.
const EXIT_TIMEOUT_MS = 10_000;

const webRoot = process.cwd();

interface WrapperResult {
  code: number | null;
  signal: string | null;
  elapsedMs: number;
}

function buildSandbox(nextSource: string): string {
  const sandbox = mkdtempSync(path.join(tmpdir(), "dev-mjs-signal-"));
  mkdirSync(path.join(sandbox, "scripts"), { recursive: true });
  copyFileSync(
    path.join(webRoot, "scripts", "dev.mjs"),
    path.join(sandbox, "scripts", "dev.mjs"),
  );
  // The stub the wrapper launches instead of the real `next dev` binary.
  const nextBin = path.join(sandbox, "node_modules", "next", "dist", "bin");
  mkdirSync(nextBin, { recursive: true });
  writeFileSync(path.join(nextBin, "next"), nextSource);
  return sandbox;
}

function runWrapper(
  sandbox: string,
  env: NodeJS.ProcessEnv = {},
): ChildProcess {
  return spawn(
    process.execPath,
    [path.join(sandbox, "scripts", "dev.mjs")],
    { cwd: sandbox, stdio: "ignore", env: { ...process.env, ...env } },
  );
}

function awaitExit(wrapper: ChildProcess): Promise<WrapperResult> {
  return new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const timer = setTimeout(() => {
      wrapper.kill("SIGKILL");
      reject(new Error(`wrapper still alive after ${EXIT_TIMEOUT_MS}ms`));
    }, EXIT_TIMEOUT_MS);
    wrapper.on("exit", (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, elapsedMs: Date.now() - startedAt });
    });
    wrapper.on("error", reject);
  });
}

function waitFor(file: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 5_000;
    const poll = setInterval(() => {
      if (existsSync(file)) {
        clearInterval(poll);
        resolve();
      } else if (Date.now() > deadline) {
        clearInterval(poll);
        reject(new Error(`stub never announced itself: ${file}`));
      }
    }, 25);
  });
}

async function withSandbox(
  nextSource: string,
  run: (sandbox: string) => Promise<void>,
): Promise<void> {
  const sandbox = buildSandbox(nextSource);
  try {
    await run(sandbox);
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

const skipWindows = { skip: process.platform === "win32" };

test("wrapper dies from the child's signal instead of hanging", skipWindows, async () => {
  await withSandbox("process.kill(process.pid, 'SIGINT');\n", async (sandbox) => {
    const result = await awaitExit(runWrapper(sandbox));
    assert.equal(
      result.signal,
      "SIGINT",
      `wrapper must be killed by SIGINT, got code=${result.code} signal=${result.signal}`,
    );
    assert.equal(result.code, null);
    assert.ok(result.elapsedMs < EXIT_TIMEOUT_MS);
  });
});

test("wrapper propagates the child's normal exit code", skipWindows, async () => {
  await withSandbox("process.exit(42);\n", async (sandbox) => {
    const result = await awaitExit(runWrapper(sandbox));
    assert.equal(result.code, 42);
    assert.equal(result.signal, null);
  });
});

test("wrapper forwards a parent signal and dies from it with the child", skipWindows, async () => {
  // Idle stub: announces its pid, dies on SIGINT (default disposition), and
  // self-destructs so a broken test cannot leak it.
  const nextSource = `
const fs = require("node:fs");
if (process.env.READY_FILE) fs.writeFileSync(process.env.READY_FILE, String(process.pid));
setTimeout(() => process.exit(98), 15000);
`;
  await withSandbox(nextSource, async (sandbox) => {
    const readyFile = path.join(sandbox, "ready");
    const wrapper = runWrapper(sandbox, { READY_FILE: readyFile });
    const exit = awaitExit(wrapper);
    await waitFor(readyFile);
    wrapper.kill("SIGINT");
    const result = await exit;
    assert.equal(
      result.signal,
      "SIGINT",
      `wrapper must be killed by the forwarded SIGINT, got code=${result.code} signal=${result.signal}`,
    );
    const childPid = Number(readFileSync(readyFile, "utf8"));
    assert.throws(
      () => process.kill(childPid, 0),
      (err: NodeJS.ErrnoException) => err.code === "ESRCH",
      "forwarded SIGINT must have taken the child down",
    );
  });
});
