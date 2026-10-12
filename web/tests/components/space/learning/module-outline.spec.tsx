import { useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ModuleOutline } from '@/components/space/learning/ModuleOutline'
import { initI18n } from '@/i18n/init'
import type {
  MapKnowledgePoint,
  MapModule,
  MasteryTopic,
  ObjectiveReport,
} from '@/lib/learning-api'

initI18n('en')

const mocks = vi.hoisted(() => ({
  fetchReport: vi.fn(),
}))

vi.mock('@/lib/learning-api', () => ({
  fetchObjectiveReport: mocks.fetchReport,
}))

function mapPoint(id: string, name: string, overrides: Partial<MapKnowledgePoint> = {}) {
  return {
    id,
    name,
    type: 'concept',
    prerequisite_ids: [],
    topic_source_ids: [],
    status: 'new',
    mastery: 0,
    mastery_source: '',
    override_note: '',
    ...overrides,
  } as MapKnowledgePoint
}

function mapModule(
  id: string,
  name: string,
  points: MapKnowledgePoint[],
  overrides: Partial<MapModule> = {}
) {
  return {
    id,
    name,
    objective: '',
    order: 0,
    mastered: points.filter(point => point.status === 'mastered').length,
    total: points.length,
    knowledge_points: points,
    ...overrides,
  } as MapModule
}

const NEXT_STEP = {
  action: 'study',
  knowledge_point_id: 'kp2',
  knowledge_point_name: 'Reading the map',
  knowledge_point_type: 'concept',
  status: 'learning',
  gate: 'qualitative',
  mastery: 0,
  threshold: 1,
  reason: '',
  forgetting_risk: 0,
  pending_prompt: '',
  session_id: '',
}

function topic(overrides: Partial<MasteryTopic> = {}) {
  return {
    path_id: 'path_1',
    name: 'Linear algebra, gently',
    metadata: {
      path_id: 'path_1',
      goal: 'Read the map',
      description: '',
      emoji: '',
      map_seed: 1,
      status: 'active',
      created_at: 1_700_000_000,
      updated_at: 1_700_000_000,
    },
    sources: [],
    path_revision: 1,
    next: NEXT_STEP,
    map: {
      name: 'Linear algebra, gently',
      counts: { mastered: 1, learning: 1, new: 1, total: 3 },
      due_reviews: 0,
      complete: false,
      modules: [
        mapModule('mod1', 'Vectors', [
          mapPoint('kp1', 'What a vector is', { status: 'mastered' }),
          mapPoint('kp2', 'Reading the map', { status: 'learning' }),
          mapPoint('kp3', 'Learner-flagged entry', {
            status: 'mastered',
            mastery_source: 'learner',
          }),
        ]),
        mapModule('mod2', 'Linear algebra, gently', [mapPoint('kp4', 'Never started entry')], {
          objective: 'See combinations as movements.',
          order: 1,
        }),
      ],
    },
    reviews: [],
    learner_profile: null,
    session_count: 0,
    updated_at: 1_700_000_000,
  } as unknown as MasteryTopic
}

function objectiveReport(overrides: Partial<ObjectiveReport> = {}): ObjectiveReport {
  return {
    id: 'kp2',
    name: 'Reading the map',
    type: 'concept',
    module_name: 'Vectors',
    status: 'learning',
    gate: 'quantitative',
    mastered: false,
    assessed_mastered: false,
    mastery_source: '',
    override_note: '',
    mastery: 0.4,
    threshold: 0.9,
    attempts: [],
    correct_count: 0,
    explanation: '',
    review: null,
    errors: [],
    ...overrides,
  }
}

type OverrideFn = (objectiveId: string, mastered: boolean, note: string) => Promise<void>

function Harness({ value, onOverride }: { value: MasteryTopic; onOverride: OverrideFn }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  return (
    <ModuleOutline
      topic={value}
      revision={1}
      selectedId={selectedId}
      zh={false}
      onSelect={setSelectedId}
      onOverride={onOverride}
    />
  )
}

beforeEach(() => {
  mocks.fetchReport.mockReset()
})

/** The header renders `{mastered}/{total}` as split text nodes. */
function moduleCount(value: string) {
  return screen.getByText(
    (_, element) => element?.tagName === 'SPAN' && element.textContent === value
  )
}

describe('ModuleOutline render', () => {
  it('renders module cards with numbering, counts, objective and points', () => {
    render(<Harness value={topic()} onOverride={vi.fn()} />)

    expect(screen.getByRole('region', { name: 'Topic outline' })).toBeTruthy()
    expect(screen.getByText('Module 1')).toBeTruthy()
    expect(screen.getByText('Module 2')).toBeTruthy()
    expect(moduleCount('2/3')).toBeTruthy()
    expect(moduleCount('0/1')).toBeTruthy()
    expect(screen.getByText('See combinations as movements.')).toBeTruthy()
    expect(screen.getByText('What a vector is')).toBeTruthy()
    expect(screen.getByText('Never started entry')).toBeTruthy()
  })

  it('hides the module heading when it just repeats the topic name', () => {
    render(<Harness value={topic()} onOverride={vi.fn()} />)

    const heading = screen.queryByRole('heading', {
      name: 'Linear algebra, gently',
    })
    expect(heading).toBeNull()
    expect(screen.getByRole('heading', { name: 'Vectors' })).toBeTruthy()
  })

  it('labels every status including learner-marked mastery, and flags next', () => {
    render(<Harness value={topic()} onOverride={vi.fn()} />)

    const nextRow = screen
      .getAllByRole('listitem')
      .find(row => within(row).queryByText('Reading the map'))
    expect(nextRow).toBeTruthy()
    expect(within(nextRow!).getByText('Next')).toBeTruthy()
    expect(within(nextRow!).getByText('In progress')).toBeTruthy()

    expect(screen.getByText('Mastered')).toBeTruthy()
    expect(screen.getByText('Marked as known')).toBeTruthy()
    expect(screen.getByText('Not started')).toBeTruthy()
  })

  it('renders an empty outline and skips blank objectives', () => {
    const bare = topic()
    bare.map.modules = [mapModule('mod1', 'Vectors', [mapPoint('kp1', 'Solo')])]
    render(<Harness value={bare} onOverride={vi.fn()} />)

    expect(screen.queryByText('See combinations as movements.')).toBeNull()
    expect(screen.getByText('Solo')).toBeTruthy()

    const empty = topic()
    empty.map.modules = []
    render(<Harness value={empty} onOverride={vi.fn()} />)
    const section = screen.getAllByRole('region', { name: 'Topic outline' })[1]
    expect(within(section).queryAllByRole('listitem')).toHaveLength(0)
  })
})

describe('ModuleOutline selection', () => {
  it('selects a point, opens its drawer, then collapses back to null', async () => {
    mocks.fetchReport.mockResolvedValue(objectiveReport())
    const { unmount } = render(<Harness value={topic()} onOverride={vi.fn()} />)

    const row = screen.getByRole('button', { name: /Reading the map/ })
    expect(row).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(row)
    expect(screen.getByRole('button', { name: /Reading the map/ })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(mocks.fetchReport).toHaveBeenCalledWith(
      'path_1',
      'kp2',
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Collapse' })).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }))
    expect(screen.queryByRole('button', { name: 'Collapse' })).toBeNull()
    expect(screen.getByRole('button', { name: /Reading the map/ })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
    unmount()
  })

  it('shows the evidence failure message when the report cannot load', async () => {
    mocks.fetchReport.mockRejectedValue(new Error('offline'))
    render(<Harness value={topic()} onOverride={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /Reading the map/ }))
    await waitFor(() => expect(screen.getByText('Evidence could not be loaded')).toBeTruthy())
  })
})

describe('ModuleOutline override', () => {
  async function openDrawer(onOverride: OverrideFn) {
    mocks.fetchReport.mockResolvedValue(objectiveReport())
    render(<Harness value={topic()} onOverride={onOverride} />)
    fireEvent.click(screen.getByRole('button', { name: /Reading the map/ }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /I already know this — advance/ })).toBeTruthy()
    )
  }

  it('confirms mastery with the optional note and closes the form', async () => {
    const onOverride = vi.fn().mockResolvedValue(undefined)
    await openDrawer(onOverride)

    fireEvent.click(screen.getByRole('button', { name: /I already know this — advance/ }))
    const note = await screen.findByLabelText(/Optional: why are you skipping this?/)
    fireEvent.change(note, { target: { value: 'Covered it in class.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm mastery' }))

    await waitFor(() =>
      expect(onOverride).toHaveBeenCalledWith('kp2', true, 'Covered it in class.')
    )
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Confirm mastery' })).toBeNull()
    )
  })

  it('cancels the note form without overriding', async () => {
    const onOverride = vi.fn().mockResolvedValue(undefined)
    await openDrawer(onOverride)

    fireEvent.click(screen.getByRole('button', { name: /I already know this — advance/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(onOverride).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /I already know this — advance/ })).toBeTruthy()
  })

  it('keeps the form open and shows the reason when overriding fails', async () => {
    const onOverride = vi.fn().mockRejectedValue(new Error('Ledger write failed'))
    await openDrawer(onOverride)

    fireEvent.click(screen.getByRole('button', { name: /I already know this — advance/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm mastery' }))

    await waitFor(() => expect(screen.getByText('Ledger write failed')).toBeTruthy())
    expect(screen.getByRole('button', { name: 'Confirm mastery' })).toBeTruthy()
  })

  it('returns a learner-marked objective to assessment', async () => {
    const onOverride = vi.fn().mockResolvedValue(undefined)
    mocks.fetchReport.mockResolvedValue(
      objectiveReport({
        id: 'kp3',
        name: 'Learner-flagged entry',
        status: 'mastered',
        mastered: true,
        mastery_source: 'learner',
      })
    )
    render(<Harness value={topic()} onOverride={onOverride} />)

    fireEvent.click(screen.getByRole('button', { name: /Learner-flagged entry/ }))
    const revert = await screen.findByRole('button', {
      name: 'Return to assessment',
    })
    expect(screen.getByText('Confirmed by you')).toBeTruthy()

    fireEvent.click(revert)
    await waitFor(() => expect(onOverride).toHaveBeenCalledWith('kp3', false, ''))
  })
})
