import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  hydrateTopicSource,
  toggleSourceSelection,
  useTopicSourceLibrary,
  type SourceCandidate,
} from '@/hooks/useTopicSourceLibrary'
import { apiFetch } from '@/lib/api'
import { listNotebookEntries } from '@/lib/notebook-api'
import { getPartnerSessions, listPartners } from '@/lib/partners-api'
import { listPartnerGroupSessions, listPartnerGroups } from '@/lib/partner-groups-api'

vi.mock('@/lib/api', () => ({ apiUrl: (path: string) => path, apiFetch: vi.fn() }))
vi.mock('@/lib/workspace-scope', () => ({ scopedUrl: (path: string) => path }))
vi.mock('@/lib/partners-api', () => ({ listPartners: vi.fn(), getPartnerSessions: vi.fn() }))
vi.mock('@/lib/partner-groups-api', () => ({
  listPartnerGroups: vi.fn(),
  listPartnerGroupSessions: vi.fn(),
}))
vi.mock('@/lib/notebook-api', () => ({ listNotebookEntries: vi.fn() }))

const translate = (cn: string) => cn

const KINDS = ['books', 'notebooks', 'knowledge', 'chats', 'practice', 'drafts'] as const
type Kind = (typeof KINDS)[number]

type Row = Record<string, unknown>
type Listing = { items: Row[]; unavailable_workspaces?: string[] }
type Route = Row[] | Listing | Error

const listingResponse = (route?: Route) => {
  const payload = route instanceof Error || Array.isArray(route) ? { items: route } : route
  return new Response(
    JSON.stringify({ items: [], unavailable_workspaces: [], ...payload }),
    { status: 200 },
  )
}

const fetchedPaths = () =>
  vi
    .mocked(apiFetch)
    .mock.calls.map(call => new URL(String(call[0]), 'http://localhost').pathname)

const sourceLibraryPaths = () =>
  fetchedPaths().filter(path => path.startsWith('/api/dashboard/source-library/'))

function mockSourceLibrary(routes: Partial<Record<Kind, Route>>) {
  vi.mocked(apiFetch).mockImplementation(async url => {
    const path = new URL(String(url), 'http://localhost').pathname
    const kind = KINDS.find(name => path === `/api/dashboard/source-library/${name}`)

    if (!kind) throw new Error(`unexpected fetch: ${path}`)
    const route = routes[kind]
    if (route instanceof Error) throw route
    return listingResponse(route)
  })
}

async function renderLibrary(routes: Partial<Record<Kind, Route>> = {}) {
  mockSourceLibrary(routes)
  const { result } = renderHook(() => useTopicSourceLibrary(translate))
  await waitFor(() => expect(result.current.loading).toBe(false))
  return result
}

beforeEach(() => {
  vi.mocked(listPartners).mockResolvedValue([])
  vi.mocked(listPartnerGroups).mockResolvedValue([])
  vi.mocked(getPartnerSessions).mockResolvedValue([])
  vi.mocked(listPartnerGroupSessions).mockResolvedValue([])
  vi.mocked(listNotebookEntries).mockResolvedValue({
    items: [],
    total: 0,
  } as Awaited<ReturnType<typeof listNotebookEntries>>)
})

it('starts loading and settles only after every listing has been fetched', async () => {
  mockSourceLibrary({})
  const { result } = renderHook(() => useTopicSourceLibrary(translate))
  expect(result.current.loading).toBe(true)
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(sourceLibraryPaths().sort()).toEqual(
    KINDS.map(kind => `/api/dashboard/source-library/${kind}`).sort()
  )
  expect(result.current.library).toMatchObject({
    books: [],
    notebooks: [],
    knowledgeBases: [],
    chats: [],
    questionSets: [],
    drafts: [],
    partners: [],
    failures: [],
  })
})

it('maps every kind into its section with keys, excerpts and workspace identity', async () => {
  const result = await renderLibrary({
    books: [{ id: 'b1', title: 'Algebra', content_workspace_id: 'ws1', content_workspace_name: 'WS1' }],
    notebooks: [{ id: 'n1', name: 'Notes' }],
    chats: [{ session_id: 's1', title: 'Chat', last_message: 'hello' }],
    practice: [{ id: 'q1', question: 'What is a vector?' }],
    drafts: [{ id: 'd1', title: 'Draft', preview: 'first lines' }],
  })

  expect(result.current.library.books[0]).toMatchObject({
    kind: 'book',
    sourceId: 'b1',
    label: 'Algebra',
    key: JSON.stringify(['ws1', 'book', 'b1']),
    content_workspace_id: 'ws1',
    content_workspace_name: 'WS1',
    available: true,
  })
  expect(result.current.library.notebooks[0]).toMatchObject({ kind: 'notebook', sourceId: 'n1', label: 'Notes' })
  expect(result.current.library.chats[0]).toMatchObject({ kind: 'chat', sourceId: 's1', excerpt: 'hello' })
  expect(result.current.library.questionSets[0]).toMatchObject({
    kind: 'question_bank',
    sourceId: 'q1',
    label: 'What is a vector?',
    excerpt: 'What is a vector?',
  })
  expect(result.current.library.drafts[0]).toMatchObject({ kind: 'cowriter', sourceId: 'd1', excerpt: 'first lines' })
})

it('falls back to the translated label and honours unavailable rows', async () => {
  const result = await renderLibrary({
    books: [{ id: 'b2', title: '', available: false }],
    notebooks: [{ id: 'n2', name: null, unreadable: true }],
  })
  expect(result.current.library.books[0]).toMatchObject({ label: 'Untitled', available: false })
  expect(result.current.library.notebooks[0]).toMatchObject({ label: 'Untitled', available: false })
})

it('hides subagent knowledge bases and marks the rest expandable', async () => {
  const result = await renderLibrary({
    knowledge: [
      { id: 'kb1', name: 'course' },
      { name: 'scratchpad', metadata: { type: 'subagent' } },
    ],
  })
  expect(result.current.library.knowledgeBases).toHaveLength(1)
  expect(result.current.library.knowledgeBases[0]).toMatchObject({
    kind: 'knowledge_base',
    sourceId: 'kb1',
    expandable: true,
  })
})

it('keeps failed kinds visible without blocking the others', async () => {
  const result = await renderLibrary({
    books: new Error('Could not load source (500)'),
    notebooks: [{ id: 'n1', name: 'Notes' }],
  })
  expect(result.current.library.failures).toEqual(['books'])
  expect(result.current.library.books).toEqual([])
  expect(result.current.library.notebooks[0]).toMatchObject({ sourceId: 'n1' })
})

it('reports kinds carrying unavailable workspaces as failures', async () => {
  const result = await renderLibrary({
    knowledge: { items: [{ id: 'kb1', name: 'course' }], unavailable_workspaces: ['ws9'] },
  })
  expect(result.current.library.failures).toEqual(['knowledge'])
  expect(result.current.library.knowledgeBases).toHaveLength(1)
})

it('offers partners and groups to open but never to select', async () => {
  vi.mocked(listPartners).mockResolvedValue([
    { partner_id: 'p1', name: 'Tutor' } as Awaited<ReturnType<typeof listPartners>>[number],
  ])
  vi.mocked(listPartnerGroups).mockResolvedValue([
    {
      group_id: 'g1',
      name: 'Team',
    } as unknown as Awaited<ReturnType<typeof listPartnerGroups>>[number],
  ])
  const result = await renderLibrary()
  expect(result.current.library.partners).toMatchObject([
    { key: 'partner:p1', kind: 'partner', sourceId: 'p1', selectable: false, expandable: true },
    {
      key: 'partner_group_root:g1',
      kind: 'partner_group_root',
      sourceId: 'g1',
      selectable: false,
      expandable: true,
    },
  ])
  expect(result.current.candidates).toEqual([])
})

it('lists candidates in section order with expanded children last', async () => {
  vi.mocked(listPartners).mockResolvedValue([
    { partner_id: 'p1', name: 'Tutor' } as Awaited<ReturnType<typeof listPartners>>[number],
  ])
  const result = await renderLibrary({
    books: [{ id: 'b1', title: 'Algebra' }],
    knowledge: [{ id: 'kb1', name: 'course' }],
    chats: [{ session_id: 's1', title: 'Chat' }],
  })
  const kb = result.current.library.knowledgeBases[0]
  vi.mocked(apiFetch).mockImplementation(async () =>
    new Response(JSON.stringify({ files: [{ name: 'a.pdf', type: 'file' }] }), { status: 200 })
  )
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  expect(result.current.candidates.map(entry => `${entry.kind}:${entry.sourceId}`)).toEqual([
    'book:b1',
    'knowledge_base:kb1',
    'chat:s1',
    'file:a.pdf',
  ])
  expect(result.current.candidates.some(entry => entry.kind === 'partner')).toBe(false)
})

it('opens a knowledge base into its non-folder files pinned to the parent', async () => {
  const result = await renderLibrary({ knowledge: [{ id: 'kb1', name: 'course' }] })
  vi.mocked(apiFetch).mockImplementation(async url => {
    const path = new URL(String(url), 'http://localhost').pathname
    expect(path).toBe('/api/knowledge-bases/kb1/files')
    return new Response(
      JSON.stringify({
        files: [
          { name: 'a.pdf', type: 'file' },
          { name: 'docs', type: 'folder' },
        ],
      }),
      { status: 200 }
    )
  })
  const kb = result.current.library.knowledgeBases[0]
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  const entry = result.current.childLists[kb.key]
  expect(entry.error).toBe('')
  expect(entry.candidates).toHaveLength(1)
  expect(entry.candidates[0]).toMatchObject({
    kind: 'file',
    sourceId: 'a.pdf',
    label: 'a.pdf',
    detail: 'kb1 中的文件',
    kbName: 'kb1',
    path: 'a.pdf',
    parentKey: kb.key,
    key: JSON.stringify(['', 'file', 'kb1', 'a.pdf']),
  })
})

it('opens a question-bank category capped at fifty entries', async () => {
  vi.mocked(listNotebookEntries).mockResolvedValue({
    items: [
      { id: 71, question: 'x'.repeat(120), is_correct: true },
      { id: 72, question: 'short', is_correct: false },
    ],
  } as Awaited<ReturnType<typeof listNotebookEntries>>)
  const result = await renderLibrary()
  const category: SourceCandidate = {
    key: 'category:7',
    kind: 'category',
    sourceId: '7',
    label: '错题本',
    detail: '',
    available: true,
  }
  await act(async () => {
    await result.current.loadChildren(category)
  })
  expect(vi.mocked(listNotebookEntries)).toHaveBeenCalledWith({ category_id: 7, limit: 50 })
  const entry = result.current.childLists[category.key]
  expect(entry.candidates[0]).toMatchObject({
    kind: 'question_bank',
    sourceId: '71',
    label: 'x'.repeat(80),
    detail: '已答对',
    excerpt: 'x'.repeat(120),
    parentKey: 'category:7',
  })
  expect(entry.candidates[1]).toMatchObject({ sourceId: '72', detail: '答错过' })
})

it('opens partners and partner groups into their session transcripts', async () => {
  vi.mocked(getPartnerSessions).mockResolvedValue([
    {
      session_key: 's9',
      title: 'Talk',
      message_count: 3,
      updated_at: '',
      last_message: 'hi',
    },
  ])
  vi.mocked(listPartnerGroupSessions).mockResolvedValue([
    { session_key: 'g9', title: '', message_count: 1, updated_at: '', created_at: '' },
  ])
  const result = await renderLibrary()
  const partner: SourceCandidate = {
    key: 'partner:p1',
    kind: 'partner',
    sourceId: 'p1',
    label: 'Tutor',
    detail: '',
    available: true,
  }
  const group: SourceCandidate = {
    key: 'partner_group_root:g1',
    kind: 'partner_group_root',
    sourceId: 'g1',
    label: 'Team',
    detail: '',
    available: true,
  }
  await act(async () => {
    await result.current.loadChildren(partner)
    await result.current.loadChildren(group)
  })
  expect(vi.mocked(getPartnerSessions)).toHaveBeenCalledWith('p1')
  expect(vi.mocked(listPartnerGroupSessions)).toHaveBeenCalledWith('g1')
  expect(result.current.childLists['partner:p1'].candidates[0]).toMatchObject({
    kind: 'chat',
    key: 'chat:partner:p1:s9',
    sourceId: 'partner:p1:s9',
    label: 'Talk',
    detail: '3 条消息',
    excerpt: 'hi',
  })
  expect(result.current.childLists['partner_group_root:g1'].candidates[0]).toMatchObject({
    kind: 'partner_group',
    key: 'partner_group:g1:g9',
    sourceId: 'g1:g9',
    label: '未命名讨论',
  })
})

it('keeps already loaded children on screen instead of blanking them on reopen', async () => {
  const result = await renderLibrary({ knowledge: [{ id: 'kb1', name: 'course' }] })
  vi.mocked(apiFetch).mockImplementation(async () =>
    new Response(JSON.stringify({ files: [{ name: 'a.pdf', type: 'file' }] }), { status: 200 })
  )
  const kb = result.current.library.knowledgeBases[0]
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  expect(result.current.childLists[kb.key].candidates).toHaveLength(1)

  const slow = Promise.withResolvers<Response>()
  vi.mocked(apiFetch).mockImplementation(async () => slow.promise)
  await act(async () => {
    result.current.loadChildren(kb)
  })
  expect(result.current.childLists[kb.key]).toMatchObject({ loading: false, error: '' })
  expect(result.current.childLists[kb.key].candidates).toHaveLength(1)

  await act(async () => {
    slow.resolve(new Response(JSON.stringify({ files: [] }), { status: 200 }))
  })
})

it('surfaces child list failures on the row that failed', async () => {
  const result = await renderLibrary({ knowledge: [{ id: 'kb1', name: 'course' }] })
  const kb = result.current.library.knowledgeBases[0]

  vi.mocked(apiFetch).mockImplementation(async () => {
    throw new Error('boom')
  })
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  expect(result.current.childLists[kb.key]).toMatchObject({ loading: false, error: 'boom' })

  vi.mocked(apiFetch).mockImplementation(async () => {
    throw 'nope'
  })
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  expect(result.current.childLists[kb.key].error).toBe('无法读取列表')
})

it('reloads when the translator changes and discards the stale response', async () => {
  let round = 0
  const stale = Promise.withResolvers<Response>()
  const fresh = Promise.withResolvers<Response>()
  vi.mocked(apiFetch).mockImplementation(async url => {
    const path = new URL(String(url), 'http://localhost').pathname
    if (path === '/api/dashboard/source-library/notebooks') {
      return round === 0 ? stale.promise : fresh.promise
    }
    return listingResponse()
  })
  let tr = translate
  const { result, rerender } = renderHook(() => useTopicSourceLibrary(tr))
  expect(result.current.loading).toBe(true)

  round = 1
  tr = (cn: string) => cn
  rerender()
  await act(async () => {
    fresh.resolve(listingResponse({ items: [{ id: 'n9', name: 'fresh' }] }))
  })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.library.notebooks.map(row => row.label)).toEqual(['fresh'])
  expect(sourceLibraryPaths()).toHaveLength(12)

  await act(async () => {
    stale.resolve(listingResponse({ items: [{ id: 'n0', name: 'stale' }] }))
  })
  expect(result.current.library.notebooks.map(row => row.label)).toEqual(['fresh'])
  expect(result.current.loading).toBe(false)
})

it('marks a book source unavailable when its spine cannot be read', async () => {
  const result = await renderLibrary({ books: [{ id: 'b1', title: 'Algebra' }] })
  vi.mocked(apiFetch).mockImplementation(async () => new Response(null, { status: 500 }))
  const source = await act(async () =>
    hydrateTopicSource(result.current.library.books[0])
  )
  expect(source).toMatchObject({
    kind: 'book',
    source_id: 'b1',
    excerpt: '',
    available: false,
  })
  expect(source.metadata?.unavailable_during_generation).toBe(true)
})

it('never lets a whole library and one of its files count twice', async () => {
  const result = await renderLibrary({ knowledge: [{ id: 'kb1', name: 'course' }] })
  vi.mocked(apiFetch).mockImplementation(async () =>
    new Response(JSON.stringify({ files: [{ name: 'a.pdf', type: 'file' }] }), { status: 200 })
  )
  const kb = result.current.library.knowledgeBases[0]
  await act(async () => {
    await result.current.loadChildren(kb)
  })
  const candidates = result.current.candidates
  const file = candidates.find(entry => entry.kind === 'file')!

  let selected = new Set<string>()
  selected = toggleSourceSelection(selected, kb.key, candidates)
  expect([...selected]).toEqual([kb.key])
  selected = toggleSourceSelection(selected, file.key, candidates)
  expect(new Set(selected)).toEqual(new Set([kb.key, file.key]))
  selected = toggleSourceSelection(selected, kb.key, candidates)
  expect([...selected]).toEqual([file.key])
  selected = toggleSourceSelection(selected, kb.key, candidates)
  expect([...selected]).toEqual([kb.key])
})
