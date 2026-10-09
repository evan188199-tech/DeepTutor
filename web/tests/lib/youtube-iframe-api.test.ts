import test from 'node:test'
import assert from 'node:assert/strict'

import { loadYouTubeApi } from '../../lib/youtube-iframe-api'
import type { YouTubeNamespace } from '../../lib/youtube-iframe-api'

const API_SRC = 'https://www.youtube.com/iframe_api'

interface FakeTimer {
  id: number
  fn: () => void
  ms: number
  cleared: boolean
}

interface FakeScript {
  src: string
  async: boolean
  removed: boolean
  fireError: () => void
}

function fakeNamespace(): YouTubeNamespace {
  return { Player: function fakePlayer() {} } as unknown as YouTubeNamespace
}

function installDom() {
  const timers: FakeTimer[] = []
  const scripts: FakeScript[] = []
  const appended: FakeScript[] = []
  let nextTimerId = 1

  const createScript = (): FakeScript => {
    const listeners: Array<{ type: string; handler: () => void; once: boolean }> = []
    const script = {
      src: '',
      async: false,
      removed: false,
      fireError: () => {
        for (const listener of listeners.filter(entry => entry.type === 'error')) {
          if (listener.once) {
            listeners.splice(listeners.indexOf(listener), 1)
          }
          listener.handler()
        }
      },
    } as FakeScript
    const scriptRecord = script as unknown as Record<string, unknown>
    scriptRecord.addEventListener = (type: string, handler: () => void, options?: { once?: boolean }) => {
      listeners.push({ type, handler, once: options?.once ?? false })
    }
    scriptRecord.remove = () => {
      script.removed = true
    }
    scripts.push(script)
    return script
  }

  const win: Record<string, unknown> = {
    setTimeout: (fn: () => void, ms?: number) => {
      const timer: FakeTimer = { id: nextTimerId++, fn, ms: ms ?? 0, cleared: false }
      timers.push(timer)
      return timer.id
    },
    clearTimeout: (id: number) => {
      const timer = timers.find(entry => entry.id === id)
      if (timer) timer.cleared = true
    },
  }

  global.window = win as unknown as Window & typeof globalThis
  global.document = {
    querySelector: (selector: string) => {
      const match = selector.match(/^script\[src="(.*)"\]$/)
      if (!match) return null
      return scripts.find(script => script.src === match[1] && !script.removed) ?? null
    },
    createElement: () => createScript(),
    head: {
      appendChild: (node: FakeScript) => {
        appended.push(node)
      },
    },
  } as unknown as Document

  return { win, timers, scripts, appended, createScript }
}

function readyCallback(): () => void {
  const callback = (global.window as unknown as Record<string, unknown>).onYouTubeIframeAPIReady
  assert.equal(typeof callback, 'function')
  return callback as () => void
}

test('resolves immediately from an existing YT namespace without injecting the script', async () => {
  const dom = installDom()
  const namespace = fakeNamespace()
  dom.win.YT = namespace
  dom.win.onYouTubeIframeAPIReady = () => {}

  const promise = loadYouTubeApi()

  assert.equal(await promise, namespace)
  assert.equal(dom.appended.length, 0)
  assert.equal(dom.timers.length, 0)
})

test('rejects when the ready callback fires before YT.Player exists and allows retrying', async () => {
  const dom = installDom()
  let previousCalled = 0
  dom.win.onYouTubeIframeAPIReady = () => {
    previousCalled += 1
  }

  const previous = dom.win.onYouTubeIframeAPIReady
  const first = loadYouTubeApi()
  assert.equal(dom.appended.length, 1)
  assert.equal(dom.appended[0].src, API_SRC)
  assert.equal(dom.appended[0].async, true)

  const wrapped = readyCallback()
  assert.notEqual(wrapped, previous)
  wrapped()
  await assert.rejects(first, /did not initialize/)
  assert.equal(previousCalled, 1)
  assert.equal(dom.timers[0].cleared, true)

  const second = loadYouTubeApi()
  assert.equal(dom.timers.length, 2)
  dom.timers[1].fn()
  await assert.rejects(second, /timed out/)
})

test('rejects and removes the injected script when the API script fails to load', async () => {
  const dom = installDom()

  const failing = loadYouTubeApi()
  const script = dom.appended[0]

  script.fireError()

  await assert.rejects(failing, /could not be loaded/)
  assert.equal(script.removed, true)
  assert.equal(dom.timers[0].cleared, true)
})

test('attaches to an existing API script tag instead of injecting another one', async () => {
  const dom = installDom()
  const existing = dom.createScript()
  existing.src = API_SRC

  const promise = loadYouTubeApi()

  assert.equal(dom.appended.length, 0)
  existing.fireError()
  await assert.rejects(promise, /could not be loaded/)
  assert.equal(existing.removed, true)
})

test('returns the same in-flight promise and injects a single script for concurrent loaders', async () => {
  const dom = installDom()

  const first = loadYouTubeApi()
  const second = loadYouTubeApi()

  assert.equal(first, second)
  assert.equal(dom.appended.length, 1)
  assert.equal(dom.timers.length, 1)

  dom.appended[0].fireError()
  await assert.rejects(first, /could not be loaded/)
  await assert.rejects(second, /could not be loaded/)
})

test('rejects after the load timeout and schedules a fresh timer for the next attempt', async () => {
  const dom = installDom()

  const first = loadYouTubeApi()
  assert.equal(dom.timers.length, 1)
  assert.equal(dom.timers[0].ms, 10_000)

  dom.timers[0].fn()
  await assert.rejects(first, /timed out/)

  const second = loadYouTubeApi()
  assert.equal(dom.timers.length, 2)
  assert.equal(dom.timers[1].cleared, false)
  dom.timers[1].fn()
  await assert.rejects(second, /timed out/)
})

test('resolves on the ready callback, clears the timeout, and ignores late failure signals', async () => {
  const dom = installDom()
  const namespace = fakeNamespace()
  let previousCalled = 0
  dom.win.onYouTubeIframeAPIReady = () => {
    previousCalled += 1
  }

  const previous = dom.win.onYouTubeIframeAPIReady
  const promise = loadYouTubeApi()
  const wrapped = readyCallback()
  assert.notEqual(wrapped, previous)

  dom.win.YT = namespace
  wrapped()

  assert.equal(await promise, namespace)
  assert.equal(previousCalled, 1)
  assert.equal(dom.timers[0].cleared, true)

  dom.appended[0].fireError()
  assert.equal(dom.appended[0].removed, true)
  assert.equal(await loadYouTubeApi(), namespace)
  wrapped()
  assert.equal(await promise, namespace)
})
