import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { CreateTopicWizard } from '@/components/space/learning/CreateTopicWizard'
import {
  hydrateTopicSource,
  useTopicSourceLibrary,
  type SourceCandidate,
  type SourceLibrary,
} from '@/hooks/useTopicSourceLibrary'
import { initI18n } from '@/i18n/init'
import { createMasteryTopic, type MasteryTopic } from '@/lib/learning-api'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({}),
  usePathname: () => '/learning',
}))

vi.mock('@/hooks/useTopicSourceLibrary', async importOriginal => {
  const actual =
    await importOriginal<typeof import('@/hooks/useTopicSourceLibrary')>()
  return {
    ...actual,
    useTopicSourceLibrary: vi.fn(),
    hydrateTopicSource: vi.fn(),
  }
})

vi.mock('@/lib/learning-api', () => ({
  createMasteryTopic: vi.fn(),
}))

initI18n('en')

const book: SourceCandidate = {
  key: JSON.stringify(['', 'book', 'b1']),
  kind: 'book',
  sourceId: 'b1',
  label: 'Linear Algebra Done Right',
  detail: '3 chapters',
  available: true,
  content_workspace_id: '',
  content_workspace_name: '',
}

const emptyLibrary: SourceLibrary = {
  books: [],
  notebooks: [],
  knowledgeBases: [],
  chats: [],
  questionSets: [],
  drafts: [],
  partners: [],
  failures: [],
}

const libraryWithBook: SourceLibrary = {
  ...emptyLibrary,
  books: [book],
}

const createdTopic = {
  path_id: 'p1',
  name: 'Vectors',
} as unknown as MasteryTopic

const hydratedBook = {
  kind: 'book',
  source_id: 'b1',
  label: 'Linear Algebra Done Right',
  excerpt: 'Chapter 1: vector spaces',
  available: true,
} as Awaited<ReturnType<typeof hydrateTopicSource>>

function libraryHookState(options?: {
  library?: SourceLibrary
  loading?: boolean
}) {
  const library = options?.library ?? libraryWithBook
  return {
    library,
    loading: options?.loading ?? false,
    candidates: [
      ...library.books,
      ...library.notebooks,
      ...library.knowledgeBases,
      ...library.chats,
      ...library.questionSets,
      ...library.drafts,
    ].filter(candidate => candidate.selectable !== false),
    childLists: {},
    loadChildren: vi.fn(),
  }
}

function renderWizard() {
  const onClose = vi.fn()
  const onCreated = vi.fn()
  render(
    <CreateTopicWizard
      onClose={onClose}
      onCreated={onCreated}
      returnFocusRef={{ current: null }}
    />,
  )
  return { onClose, onCreated }
}

function advanceToMaterials() {
  fireEvent.change(screen.getByLabelText(/Learning goal/), {
    target: { value: 'Master vector spaces' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Choose sources' }))
}

beforeEach(() => {
  vi.mocked(useTopicSourceLibrary).mockReturnValue(libraryHookState())
  vi.mocked(hydrateTopicSource).mockResolvedValue(hydratedBook)
  vi.mocked(createMasteryTopic).mockResolvedValue(createdTopic)
})

it('keeps the continue button disabled until the goal has non-blank text', () => {
  renderWizard()
  const next = screen.getByRole('button', { name: 'Choose sources' })
  expect(next).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Learning goal/), {
    target: { value: '   ' },
  })
  expect(next).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Learning goal/), {
    target: { value: 'Master vector spaces' },
  })
  expect(next).toBeEnabled()
})

it('moves to the materials step and back with the goal preserved', () => {
  renderWizard()
  advanceToMaterials()
  expect(
    screen.getByRole('heading', { level: 2, name: 'Choose materials' }),
  ).toBeInTheDocument()
  expect(screen.getByText('0 selected')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  expect(
    screen.getByRole('heading', {
      level: 2,
      name: 'What do you want to master?',
    }),
  ).toBeInTheDocument()
  expect(screen.getByLabelText(/Learning goal/)).toHaveValue(
    'Master vector spaces',
  )
})

it('shows the empty state when the source library has no materials', () => {
  vi.mocked(useTopicSourceLibrary).mockReturnValue(
    libraryHookState({ library: emptyLibrary }),
  )
  renderWizard()
  advanceToMaterials()
  expect(screen.getByText('No matching materials')).toBeInTheDocument()
})

it('toggles a material selection on the materials step', () => {
  renderWizard()
  advanceToMaterials()
  fireEvent.click(screen.getByRole('tab', { name: /Books/ }))
  const row = screen.getByRole('button', { name: /Linear Algebra Done Right/ })
  expect(row).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(row)
  expect(screen.getByText('1 selected')).toBeInTheDocument()
  expect(row).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(row)
  expect(screen.getByText('0 selected')).toBeInTheDocument()
})

it('submits the trimmed goal, chosen emblem, hydrated sources and no modules', async () => {
  const { onCreated } = renderWizard()
  fireEvent.change(screen.getByLabelText(/Learning goal/), {
    target: { value: '  Master vector spaces  ' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Choose goal emblem 🏔️' }))
  fireEvent.click(screen.getByRole('button', { name: 'Choose sources' }))
  fireEvent.click(screen.getByRole('tab', { name: /Books/ }))
  fireEvent.click(
    screen.getByRole('button', { name: /Linear Algebra Done Right/ }),
  )
  fireEvent.click(
    screen.getByRole('button', { name: 'Design the outline with the tutor' }),
  )
  await waitFor(() => expect(createMasteryTopic).toHaveBeenCalledTimes(1))
  expect(vi.mocked(createMasteryTopic).mock.calls[0][0]).toEqual({
    goal: 'Master vector spaces',
    emoji: '🏔️',
    sources: [
      {
        kind: 'goal',
        label: 'Learning goal',
        excerpt: 'Master vector spaces',
      },
      hydratedBook,
    ],
    modules: [],
  })
  expect(onCreated).toHaveBeenCalledWith(createdTopic)
})

it('locks the dialog while creation is pending', async () => {
  vi.mocked(createMasteryTopic).mockImplementation(
    () => new Promise<MasteryTopic>(() => {}),
  )
  const { onClose, onCreated } = renderWizard()
  advanceToMaterials()
  fireEvent.click(
    screen.getByRole('button', { name: 'Design the outline with the tutor' }),
  )
  expect(await screen.findByText('Creating…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled()
  fireEvent.keyDown(document.body, { key: 'Escape' })
  expect(onClose).not.toHaveBeenCalled()
  expect(onCreated).not.toHaveBeenCalled()
})

it('surfaces the server error message and recovers on retry', async () => {
  vi.mocked(createMasteryTopic)
    .mockRejectedValueOnce(new Error('Server exploded'))
    .mockResolvedValue(createdTopic)
  const { onCreated } = renderWizard()
  advanceToMaterials()
  const create = screen.getByRole('button', {
    name: 'Design the outline with the tutor',
  })
  fireEvent.click(create)
  expect(await screen.findByText('Server exploded')).toBeInTheDocument()
  expect(onCreated).not.toHaveBeenCalled()
  expect(create).toBeEnabled()
  fireEvent.click(create)
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(createdTopic))
  expect(screen.queryByText('Server exploded')).not.toBeInTheDocument()
})

it('falls back to the generic message for non-error rejections', async () => {
  vi.mocked(createMasteryTopic).mockRejectedValueOnce('network down')
  renderWizard()
  advanceToMaterials()
  fireEvent.click(
    screen.getByRole('button', { name: 'Design the outline with the tutor' }),
  )
  expect(
    await screen.findByText('Creation failed. Please retry.'),
  ).toBeInTheDocument()
})

it('closes from a backdrop press while idle', () => {
  const { onClose } = renderWizard()
  const overlay = screen.getByRole('dialog').parentElement!
  fireEvent.mouseDown(overlay)
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('closes from the close button while idle', () => {
  const { onClose } = renderWizard()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('closes on Escape while idle', () => {
  const { onClose } = renderWizard()
  fireEvent.keyDown(document.body, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
})
