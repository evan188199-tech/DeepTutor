import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RouteDraftEditor } from '@/components/space/learning/RouteDraftEditor'
import { initI18n } from '@/i18n/init'
import type { ModuleInit, TopicDraft } from '@/lib/learning-api'

initI18n('en')

type WaypointInit = ModuleInit['knowledge_points'][number]

function point(id: string, name: string, type = 'concept'): WaypointInit {
  return { id, name, type, module_id: 'm1' }
}

function module(id: string, name: string, knowledgePoints: WaypointInit[], order = 0): ModuleInit {
  return {
    id,
    name,
    order,
    knowledge_points: knowledgePoints.map((waypoint, index) => ({
      ...waypoint,
      module_id: id,
      id: waypoint.id || `${id}_p${index + 1}`,
    })),
  }
}

function draft(modules: ModuleInit[], description = 'A route description.'): TopicDraft {
  return { description, modules }
}

function oneModuleDraft(): TopicDraft {
  return draft([
    module('m1', 'Foundations', [point('m1_p1', 'Variables'), point('m1_p2', 'Spans')]),
  ])
}

function view(overrides: Partial<TopicDraft> = {}, moduleLimit?: number) {
  const onChange = vi.fn()
  const value = { ...oneModuleDraft(), ...overrides }
  return {
    onChange,
    ...render(<RouteDraftEditor draft={value} onChange={onChange} moduleLimit={moduleLimit} />),
  }
}

function emitted(onChange: ReturnType<typeof vi.fn>): TopicDraft {
  const call = onChange.mock.calls.at(-1)
  if (!call) throw new Error('onChange was not called')
  return call[0] as TopicDraft
}

describe('RouteDraftEditor render', () => {
  it('shows the intro, map description and module rows by default', () => {
    render(<RouteDraftEditor draft={oneModuleDraft()} onChange={vi.fn()} />)

    expect(screen.getByText('Review and adjust the modules')).toBeTruthy()
    const description = screen.getByLabelText('Map description')
    expect(description).toHaveValue('A route description.')
    expect(screen.getByLabelText('Module 1 name')).toHaveValue('Foundations')
    expect(screen.getByLabelText('Knowledge point 1 name in module 1')).toHaveValue('Variables')
    expect(screen.getByLabelText('Knowledge point 2 name in module 1')).toHaveValue('Spans')
    expect(screen.getByRole('button', { name: 'Add module' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Add knowledge point' })).toBeTruthy()
  })

  it('hides the intro in compact mode and the textarea when description is off', () => {
    const compact = render(<RouteDraftEditor draft={oneModuleDraft()} onChange={vi.fn()} compact />)
    expect(compact.queryByText('Review and adjust the modules')).toBeNull()
    expect(compact.getByLabelText('Map description')).toBeTruthy()
    compact.unmount()

    const hidden = render(
      <RouteDraftEditor
        draft={oneModuleDraft()}
        onChange={vi.fn()}
        compact
        showDescription={false}
      />
    )
    expect(hidden.queryByLabelText('Map description')).toBeNull()
    expect(hidden.getByLabelText('Module 1 name')).toBeTruthy()
  })

  it('keeps every module editable when the draft holds several', () => {
    const twoModules = draft([
      module('m1', 'Foundations', [point('m1_p1', 'Variables')]),
      module('m2', 'Spans', [point('m2_p1', 'Basis')], 1),
    ])
    render(<RouteDraftEditor draft={twoModules} onChange={vi.fn()} />)

    expect(screen.getByLabelText('Module 1 name')).toHaveValue('Foundations')
    expect(screen.getByLabelText('Module 2 name')).toHaveValue('Spans')
    expect(screen.getByLabelText('Knowledge point 1 name in module 2')).toHaveValue('Basis')
  })
})

describe('RouteDraftEditor edits flow through onChange', () => {
  it('emits a description-only change when the textarea is edited', () => {
    const { onChange } = view()

    fireEvent.change(screen.getByLabelText('Map description'), {
      target: { value: 'Rewritten.' },
    })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(emitted(onChange)).toMatchObject({
      description: 'Rewritten.',
      modules: oneModuleDraft().modules,
    })
  })

  it('emits a renamed module with waypoint ids kept stable', () => {
    const { onChange } = view()

    fireEvent.change(screen.getByLabelText('Module 1 name'), {
      target: { value: 'Vectors' },
    })

    const next = emitted(onChange)
    expect(next.modules).toHaveLength(1)
    expect(next.modules[0].name).toBe('Vectors')
    expect(next.modules[0].id).toBe('m1')
    expect(next.modules[0].knowledge_points.map(waypoint => waypoint.id)).toEqual([
      'm1_p1',
      'm1_p2',
    ])
  })

  it('emits a renamed waypoint and a switched waypoint type', () => {
    const { onChange } = view()

    fireEvent.change(screen.getByLabelText('Knowledge point 1 name in module 1'), {
      target: { value: 'Scalars' },
    })
    expect(emitted(onChange).modules[0].knowledge_points[0]).toMatchObject({
      name: 'Scalars',
      type: 'concept',
    })

    fireEvent.change(screen.getByLabelText('Type for “Variables”'), {
      target: { value: 'procedure' },
    })
    expect(emitted(onChange).modules[0].knowledge_points[0]).toMatchObject({
      name: 'Variables',
      type: 'procedure',
      module_id: 'm1',
    })
  })
})

describe('RouteDraftEditor flags draft issues', () => {
  it('marks a blank module name and its waypoint', () => {
    const invalid = draft([module('m1', '   ', [point('m1_p1', '  '), point('m1_p2', 'Spans')])])
    render(<RouteDraftEditor draft={invalid} onChange={vi.fn()} />)

    expect(screen.getByText('Module name cannot be blank.')).toBeTruthy()
    expect(screen.getByText('Knowledge point name cannot be blank.')).toBeTruthy()
    expect(screen.getByLabelText('Module 1 name')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Knowledge point 1 name in module 1')).toHaveAttribute(
      'aria-invalid',
      'true'
    )
    expect(screen.getByLabelText('Knowledge point 2 name in module 1')).toHaveAttribute(
      'aria-invalid',
      'false'
    )
  })

  it('asks for a waypoint when a module has none', () => {
    const invalid = draft([module('m1', 'Foundations', [])])
    render(<RouteDraftEditor draft={invalid} onChange={vi.fn()} />)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Every module needs at least one knowledge point.')
  })

  it('keeps the last module and warns when the draft holds none', () => {
    const single = view()
    expect(single.getByRole('button', { name: 'Remove module “Foundations”' })).toBeDisabled()
    single.unmount()

    const empty = view({ modules: [] })
    expect(empty.getByText('Keep at least one module.')).toBeTruthy()
    expect(empty.queryByLabelText('Module 1 name')).toBeNull()
  })
})

describe('RouteDraftEditor structural edits', () => {
  it('removes a module once a second one exists', () => {
    const twoModules = draft([
      module('m1', 'Foundations', [point('m1_p1', 'Variables')]),
      module('m2', 'Spans', [point('m2_p1', 'Basis')], 1),
    ])
    const onChange = vi.fn()
    render(<RouteDraftEditor draft={twoModules} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Remove module “Foundations”' }))

    const next = emitted(onChange)
    expect(next.modules).toHaveLength(1)
    expect(next.modules[0]).toMatchObject({ id: 'm2', order: 0 })
    expect(next.modules[0].knowledge_points[0].module_id).toBe('m2')
  })

  it('adds a module seeded with one knowledge point', () => {
    const { onChange } = view()

    fireEvent.click(screen.getByRole('button', { name: 'Add module' }))

    const next = emitted(onChange)
    expect(next.modules).toHaveLength(2)
    expect(next.modules[1]).toMatchObject({
      name: 'New module 2',
      order: 1,
    })
    expect(next.modules[1].knowledge_points).toHaveLength(1)
    expect(next.modules[1].knowledge_points[0]).toMatchObject({
      name: 'New knowledge point',
      type: 'concept',
      module_id: next.modules[1].id,
    })
  })

  it('adds a knowledge point to the module it belongs to', () => {
    const { onChange } = view()

    fireEvent.click(screen.getByRole('button', { name: 'Add knowledge point' }))

    const next = emitted(onChange)
    expect(next.modules).toHaveLength(1)
    expect(next.modules[0].knowledge_points.map(waypoint => waypoint.name)).toEqual([
      'Variables',
      'Spans',
      'New knowledge point',
    ])
  })

  it('reorders modules through the order controls', () => {
    const twoModules = draft([
      module('m1', 'Foundations', [point('m1_p1', 'Variables')]),
      module('m2', 'Spans', [point('m2_p1', 'Basis')], 1),
    ])
    const onChange = vi.fn()
    render(<RouteDraftEditor draft={twoModules} onChange={onChange} />)

    const up = screen.getByRole('button', { name: 'Move module “Foundations” up' })
    const down = screen.getByRole('button', { name: 'Move module “Foundations” down' })
    expect(up).toBeDisabled()
    expect(down).toBeEnabled()

    fireEvent.click(down)
    const next = emitted(onChange)
    expect(next.modules.map(entry => entry.id)).toEqual(['m2', 'm1'])
    expect(next.modules.map(entry => entry.order)).toEqual([0, 1])
  })

  it('reorders and removes waypoints inside a module', () => {
    const { onChange } = view()

    expect(screen.getByRole('button', { name: 'Move “Variables” up' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Move “Variables” down' }))
    let next = emitted(onChange)
    expect(next.modules[0].knowledge_points.map(waypoint => waypoint.name)).toEqual([
      'Spans',
      'Variables',
    ])

    const remove = screen.getByRole('button', { name: 'Remove “Spans”' })
    expect(screen.getByRole('button', { name: 'Remove “Variables”' })).toBeEnabled()
    fireEvent.click(remove)
    next = emitted(onChange)
    expect(next.modules[0].knowledge_points).toHaveLength(1)
    expect(next.modules[0].knowledge_points[0].name).toBe('Variables')
  })
})

describe('RouteDraftEditor module cap', () => {
  function nineModules(): ModuleInit[] {
    return Array.from({ length: 9 }, (_, index) =>
      module(`m${index + 1}`, `Module ${index + 1}`, [point('', 'Waypoint')], index)
    )
  }

  it('hides add-module at the default cap but honors a larger server limit', () => {
    const onChange = vi.fn()
    const capped = render(<RouteDraftEditor draft={draft(nineModules())} onChange={onChange} />)
    expect(capped.queryByRole('button', { name: 'Add module' })).toBeNull()

    const raised = render(
      <RouteDraftEditor draft={draft(nineModules())} onChange={onChange} moduleLimit={14} />
    )
    expect(raised.getByRole('button', { name: 'Add module' })).toBeTruthy()
  })
})
