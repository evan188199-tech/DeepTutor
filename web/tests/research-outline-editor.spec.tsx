import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import ResearchOutlineEditor from '@/components/research/ResearchOutlineEditor'
import { initI18n } from '@/i18n/init'
import type { OutlineItem } from '@/lib/research-types'

initI18n('en')

const outline = (...items: OutlineItem[]) => items

function titleInputs() {
  return screen.getAllByPlaceholderText('Sub-topic title...')
}

function rowOf(element: HTMLElement) {
  return element.closest('.group')!
}

function removeButtons() {
  return titleInputs()
    .map(input => rowOf(input).querySelector('button'))
    .filter(Boolean) as HTMLButtonElement[]
}

function renderEditor(
  items: OutlineItem[],
  status?: 'researching' | 'done' | 'failed',
) {
  const onConfirm = vi.fn()
  render(
    <ResearchOutlineEditor
      outline={items}
      topic="vector spaces"
      onConfirm={onConfirm}
      status={status}
    />,
  )
  return { onConfirm }
}

it('renders the outline editable with the review hint', () => {
  renderEditor(outline({ title: 'Alpha', overview: 'a' }, { title: 'Beta', overview: '' }))
  expect(
    screen.getByText(/Review and edit the sub-topics below/),
  ).toBeInTheDocument()
  const inputs = titleInputs()
  expect(inputs).toHaveLength(2)
  expect(inputs[0]).toHaveValue('Alpha')
  expect(screen.getByDisplayValue('a')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start Research' })).toBeEnabled()
  // While editing the summary header is not a control.
  expect(screen.getByRole('button', { name: /Research Outline/ })).toBeDisabled()
})

it('edits titles and overviews in place', () => {
  renderEditor(outline({ title: 'Alpha', overview: 'a' }))
  fireEvent.change(titleInputs()[0], { target: { value: 'Alpha revised' } })
  fireEvent.change(screen.getByPlaceholderText('Research direction and focus...'), {
    target: { value: 'a revised' },
  })
  expect(titleInputs()[0]).toHaveValue('Alpha revised')
  expect(screen.getByDisplayValue('a revised')).toBeInTheDocument()
})

it('adds a sub-topic and removes rows down to the last one', () => {
  renderEditor(outline({ title: 'Alpha', overview: '' }, { title: 'Beta', overview: '' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add sub-topic' }))
  expect(titleInputs()).toHaveLength(3)
  fireEvent.click(removeButtons()[0])
  const inputs = titleInputs()
  expect(inputs).toHaveLength(2)
  expect(inputs.map(input => (input as HTMLInputElement).value)).toEqual(['Beta', ''])
  // The last remaining row cannot be deleted.
  fireEvent.click(removeButtons()[0])
  expect(titleInputs()).toHaveLength(1)
  expect(removeButtons()).toHaveLength(0)
})

it('confirms only the sub-topics with a title and collapses as researching', () => {
  const { onConfirm } = renderEditor(
    outline({ title: 'Alpha', overview: 'a' }, { title: '   ', overview: 'b' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Start Research' }))
  expect(onConfirm).toHaveBeenCalledTimes(1)
  expect(onConfirm).toHaveBeenCalledWith([{ title: 'Alpha', overview: 'a' }])
  expect(screen.getByText('Researching')).toBeInTheDocument()
  expect(screen.getByText('· 1 sub-topics')).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Sub-topic title...')).not.toBeInTheDocument()
})

it('passes the edited outline to onConfirm', () => {
  const { onConfirm } = renderEditor(
    outline({ title: 'Alpha', overview: 'a' }, { title: 'Beta', overview: 'b' }),
  )
  fireEvent.change(titleInputs()[0], { target: { value: 'Alpha revised' } })
  const overviews = screen.getAllByPlaceholderText('Research direction and focus...')
  fireEvent.change(overviews[1], { target: { value: 'b revised' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start Research' }))
  expect(onConfirm).toHaveBeenCalledWith([
    { title: 'Alpha revised', overview: 'a' },
    { title: 'Beta', overview: 'b revised' },
  ])
})

it('keeps start disabled until a sub-topic has a non-blank title', () => {
  renderEditor(outline({ title: '   ', overview: '' }))
  const start = screen.getByRole('button', { name: 'Start Research' })
  expect(start).toBeDisabled()
  fireEvent.change(titleInputs()[0], { target: { value: 'Alpha' } })
  expect(start).toBeEnabled()
})

it('locks an in-progress outline collapsed and lets the header re-open it', () => {
  renderEditor(
    outline({ title: 'Alpha', overview: 'a' }, { title: 'Beta', overview: '' }),
    'researching',
  )
  expect(screen.getByText('Researching')).toBeInTheDocument()
  expect(screen.getByText('· 2 sub-topics')).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Sub-topic title...')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Research Outline/ }))
  expect(screen.getByText('Alpha')).toBeInTheDocument()
  expect(screen.getByText('Beta')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add sub-topic' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Research Outline/ }))
  expect(screen.queryByText('Alpha')).not.toBeInTheDocument()
  expect(screen.getByText('· 2 sub-topics')).toBeInTheDocument()
})

it('shows a completed outline read-only', () => {
  renderEditor(outline({ title: 'Alpha', overview: 'a' }), 'done')
  expect(screen.getByText('Research Complete')).toBeInTheDocument()
  expect(screen.getByText('· 1 sub-topics')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Research Outline/ }))
  expect(screen.getByText('Alpha')).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Sub-topic title...')).not.toBeInTheDocument()
})

it('returns a failed outline to editing with a retry affordance', () => {
  const { onConfirm } = renderEditor(
    outline({ title: 'Alpha', overview: 'a' }, { title: '  ', overview: '' }),
    'failed',
  )
  expect(screen.getByText('Research failed. You can retry.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Start Research' })).not.toBeInTheDocument()
  const retry = screen.getByRole('button', { name: 'Retry Research' })
  expect(retry).toBeEnabled()
  expect(titleInputs()).toHaveLength(2)
  fireEvent.click(retry)
  expect(onConfirm).toHaveBeenCalledWith([{ title: 'Alpha', overview: 'a' }])
  // Still failed, so the outline stays editable for the next attempt.
  expect(titleInputs()[0]).toHaveValue('Alpha')
})

it('renders an empty outline with only the add affordance', () => {
  const { onConfirm } = renderEditor([])
  expect(screen.queryByPlaceholderText('Sub-topic title...')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start Research' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Add sub-topic' }))
  expect(titleInputs()).toHaveLength(1)
  expect(onConfirm).not.toHaveBeenCalled()
})
