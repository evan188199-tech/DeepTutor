#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { configureTypeIncludes } from './next-type-includes.mjs'

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const nextBin = path.join(webRoot, 'node_modules', 'next', 'dist', 'bin', 'next')

// Next 16 rewrites these checked-in generated inputs when it type-checks. The
// launcher used to repair them only after `npm run build` returned; moving the
// restore here also protects direct `npm run build` invocations.
const generatedPaths = [path.join(webRoot, "next-env.d.ts"), path.join(webRoot, "tsconfig.json")]

function snapshot(path) {
  return readFileSync(path, 'utf8')
}

function restore(path, contents) {
  writeFileSync(path, contents, 'utf8')
}

function restoreAll(snapshots) {
  for (const [path, contents] of snapshots) restore(path, contents)
}

function completeStandaloneBundle() {
  const distDir = path.resolve(webRoot, process.env.DEEPTUTOR_NEXT_DIST_DIR || '.next')
  const standaloneDir = path.join(distDir, 'standalone')
  const staticDir = path.join(distDir, 'static')
  if (!existsSync(path.join(standaloneDir, 'server.js'))) {
    throw new Error(`Next build did not create ${path.join(standaloneDir, 'server.js')}`)
  }
  if (!existsSync(staticDir)) {
    throw new Error(`Next build did not create ${staticDir}`)
  }

  // Standalone server bundles omit browser assets. Keep the default /_next
  // path self-contained, and mirror assets under a custom distDir for launchers
  // that resolve /_next from their configured dist directory.
  const runtimeDistDir = path.relative(webRoot, distDir)
  const staticTargets = [path.join(standaloneDir, ".next", "static")]
  if (runtimeDistDir !== '.next') {
    staticTargets.push(path.join(standaloneDir, runtimeDistDir, "static"))
  }
  for (const target of staticTargets) {
    rmSync(target, { recursive: true, force: true })
    mkdirSync(path.dirname(target), { recursive: true })
    cpSync(staticDir, target, { recursive: true, force: true })
  }

  const publicDir = path.join(webRoot, 'public')
  const publicTarget = path.join(standaloneDir, "public")
  rmSync(publicTarget, { recursive: true, force: true })
  cpSync(publicDir, publicTarget, { recursive: true, force: true })
}

function prepareBuildTsconfig(snapshots, distDir) {
  const tsconfigPath = path.join(webRoot, 'tsconfig.json')
  const tsconfig = snapshots.find(([filePath]) => filePath === tsconfigPath)
  if (!tsconfig) return null
  const buildTsconfigPath = path.join(webRoot, `tsconfig.deeptutor-build-${process.pid}.json`)
  restore(buildTsconfigPath, configureTypeIncludes(tsconfig[1], distDir))
  return buildTsconfigPath
}

const snapshots = generatedPaths
  .filter(path => process.env.DEEPTUTOR_BUILD_SKIP_MISSING !== '1')
  .map(path => [path, snapshot(path)])

const isEntry = import.meta.url === pathToFileURL(process.argv[1] ?? '').href

export { restoreAll }

if (isEntry) {
  const distDir = process.env.DEEPTUTOR_NEXT_DIST_DIR || '.next'
  const buildTsconfigPath = prepareBuildTsconfig(snapshots, distDir)
  let result
  try {
    result = spawnSync(
      process.execPath,
      // Next.js 16 defaults to Turbopack, which does not emit the standalone
      // server bundle expected by `deeptutor start`. The production launcher
      // needs the Webpack output at `.next-deeptutor/standalone/server.js`.
      [nextBin, "build", "--webpack", ...process.argv.slice(2)],
      {
        cwd: webRoot,
        stdio: "inherit",
        env: {
          ...process.env,
          ...(buildTsconfigPath
            ? { DEEPTUTOR_NEXT_TSCONFIG: path.basename(buildTsconfigPath) }
            : {}),
        },
      }
    )
  } finally {
    if (buildTsconfigPath) rmSync(buildTsconfigPath, { force: true })
    restoreAll(snapshots)
  }
  if (result.error) {
    console.error(result.error)
    process.exit(1)
  }
  const status = result.status ?? 1
  if (status === 0) completeStandaloneBundle()
  process.exit(status)
}
