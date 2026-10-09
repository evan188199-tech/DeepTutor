import assert from 'node:assert/strict'
import test from 'node:test'

type UnreadModule = typeof import('../../lib/session-unread')

// lib/session-unread keeps its bookkeeping private and only exposes it
// through useSyncExternalStore. The node test axis has no DOM and no
// renderer, so before the module under test is first required we swap the
// resolved `react` entry for a stub that keeps every real React export and
// overrides just the two hooks the module uses. The stub simulates exactly
// one mounted client component: it subscribes on first render, counts the
// store change notifications, records the server snapshot sizes, and
// re-reads the client snapshot on every render.
const reactEntry: string = require.resolve('react')

let notifications = 0
const serverSnapshotSizes: number[] = []
let unsubscribe: (() => void) | null = null

function onStoreChange(): void {
  notifications += 1
}

require.cache[reactEntry] = {
  id: reactEntry,
  filename: reactEntry,
  loaded: true,
  exports: {
    ...require(reactEntry),
    useCallback: <T>(fn: T): T => fn,
    useSyncExternalStore: (
      subscribe: (onStoreChange: () => void) => () => void,
      getSnapshot: () => ReadonlySet<string>,
      getServerSnapshot?: () => ReadonlySet<string>
    ): ReadonlySet<string> => {
      if (!unsubscribe) unsubscribe = subscribe(onStoreChange)
      if (getServerSnapshot) serverSnapshotSizes.push(getServerSnapshot().size)
      return getSnapshot()
    },
  },
} as unknown as NodeModule

// Each test needs the module's private state (unread set, transition
// baseline, published snapshot) back at its origin value, so every test
// starts by evicting the compiled module from the require cache and
// re-requiring a pristine instance.
function freshStore(): UnreadModule {
  notifications = 0
  serverSnapshotSizes.length = 0
  if (unsubscribe) unsubscribe()
  unsubscribe = null
  const modulePath = require.resolve('../../lib/session-unread')
  delete require.cache[modulePath]
  return require('../../lib/session-unread') as UnreadModule
}

function unreadNow(store: UnreadModule): ReadonlySet<string> {
  return store.useUnreadSessions()
}

const live = (...ids: string[]): ReadonlySet<string> => new Set(ids)

const sorted = (set: ReadonlySet<string>): string[] => [...set].sort()

// ── baseline: the first reconcile never reports unread ───────────────

test('first reconcile establishes a baseline and marks nothing unread', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2'), null)
  const unread = unreadNow(store)
  assert.equal(unread.size, 0)

  // Reconciling the same live set again changes nothing: no notification,
  // and the hook keeps returning the identical snapshot object.
  store.reconcileUnread(live('s1', 's2'), null)
  assert.equal(unreadNow(store), unread)
  assert.equal(notifications, 0)
})

test('a running session that drops out of the live set becomes unread', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2'), null)
  assert.equal(unreadNow(store).size, 0, 'the baseline read mounts the subscriber')
  assert.equal(notifications, 0)

  store.reconcileUnread(live('s2'), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s1'])
  assert.equal(notifications, 1, 'the transition publishes exactly one snapshot')
})

test('a session already finished when first seen never becomes unread', () => {
  const store = freshStore()

  // The baseline is the empty live set: any session that exists but is not
  // running was finished before the reader ever looked, so it must not be
  // flagged as a change.
  store.reconcileUnread(live(), null)
  store.reconcileUnread(live(), null)
  store.reconcileUnread(live(), null)

  assert.equal(unreadNow(store).size, 0)
  assert.equal(notifications, 0)
})

test('the server snapshot stays empty regardless of accumulated unread', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1'), null)
  store.reconcileUnread(live(), null)
  assert.equal(unreadNow(store).size, 1)

  // Every render on the server must see no unread sessions.
  assert.ok(serverSnapshotSizes.length > 0)
  for (const size of serverSnapshotSizes) assert.equal(size, 0)
})

// ── clearing and re-arming ────────────────────────────────────────────

test('opening a session clears its unread flag', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2'), null)
  assert.equal(unreadNow(store).size, 0)
  store.reconcileUnread(live(), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s1', 's2'])

  store.reconcileUnread(live(), 's1')
  assert.deepEqual(sorted(unreadNow(store)), ['s2'])
  assert.equal(notifications, 2, 'the transition and the clear each emit once')
})

test('the active session never becomes unread even while it finishes', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2'), 's1')
  store.reconcileUnread(live(), 's1')

  assert.deepEqual(sorted(unreadNow(store)), ['s2'])
})

test('a cleared session re-arms and flags again when it finishes once more', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1'), null)
  store.reconcileUnread(live(), null)
  assert.equal(unreadNow(store).size, 1)

  store.reconcileUnread(live(), 's1')
  assert.equal(unreadNow(store).size, 0, 'opening the session marks it read')

  store.reconcileUnread(live('s1'), 's1')
  store.reconcileUnread(live(), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s1'], 'the second finish is a fresh unread signal')
})

// ── aggregation across sessions ───────────────────────────────────────

test('sessions finishing in the same transition aggregate into one snapshot', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2', 's3'), null)
  assert.equal(unreadNow(store).size, 0)
  store.reconcileUnread(live(), null)

  assert.deepEqual(sorted(unreadNow(store)), ['s1', 's2', 's3'])
  assert.equal(notifications, 1, 'one transition notifies the subscriber exactly once')
})

test('sessions finishing at different times accumulate across snapshots', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', 's2'), null)
  store.reconcileUnread(live('s2'), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s1'])

  store.reconcileUnread(live(), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s1', 's2'])
})

test('a no-op reconcile keeps the previous snapshot identity and stays silent', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1'), null)
  assert.equal(unreadNow(store).size, 0)
  store.reconcileUnread(live(), null)
  const marked = unreadNow(store)

  store.reconcileUnread(live(), null)
  store.reconcileUnread(live(), 'ghost')
  assert.equal(unreadNow(store), marked)
  assert.equal(notifications, 1)
})

// ── malformed live lists must not crash the fold ──────────────────────

test('non-string junk entries in the live set are carried through without crashing', () => {
  const store = freshStore()

  const junk = live('s1', 42 as unknown as string)
  store.reconcileUnread(junk, null)
  assert.equal(unreadNow(store).size, 0, 'the first sight is still only a baseline')

  store.reconcileUnread(live('s1'), null)
  const unread = unreadNow(store)
  assert.equal(unread.size, 1)
  assert.ok(unread.has(42 as unknown as string), 'a junk id is tracked like any other')
})

test('degenerate session ids fold without crashing', () => {
  const store = freshStore()

  store.reconcileUnread(live('s1', ''), null)
  store.reconcileUnread(live('s1'), null)

  const unread = unreadNow(store)
  assert.equal(unread.size, 1)
  assert.ok(unread.has(''), 'an empty-string id is tracked like any other')
})

test('a missing live list on the first call is treated as an empty baseline', () => {
  const store = freshStore()

  store.reconcileUnread(null as unknown as ReadonlySet<string>, null)
  assert.equal(unreadNow(store).size, 0)

  // The empty baseline still arms later transitions.
  store.reconcileUnread(live('s9'), null)
  store.reconcileUnread(live(), null)
  assert.deepEqual(sorted(unreadNow(store)), ['s9'])
})
