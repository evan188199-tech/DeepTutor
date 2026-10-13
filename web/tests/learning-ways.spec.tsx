import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LearningWays } from '@/components/learning/LearningWays'
import { initI18n } from '@/i18n/init'

/**
 * The card-to-panel morph is framer-motion's to render, and its exit animation
 * never settles under jsdom — the panel would stay mounted for good. What a
 * test can hold is the behaviour around the morph, so motion elements stand in
 * as plain ones here and `AnimatePresence` mounts and unmounts at once.
 */
vi.mock('framer-motion', async () => {
  const { createElement } = await import('react')
  const strip = (props: Record<string, unknown>) => {
    const plain: Record<string, unknown> = {}
    const motionOnly = new Set([
      'layoutId',
      'layout',
      'initial',
      'animate',
      'exit',
      'transition',
      'variants',
      'whileHover',
      'whileTap',
      'layoutRoot',
    ])
    for (const [name, value] of Object.entries(props))
      if (!motionOnly.has(name)) plain[name] = value
    return plain
  }
  const cache: Record<string, unknown> = {}
  // Both names, one proxy: the app renders inside a strict `LazyMotion`, so its
  // components import `m` rather than `motion` (#1549).
  const motion = new Proxy(cache, {
    get: (store, tag: string) =>
      (store[tag] ??= (props: Record<string, unknown>) => createElement(tag, strip(props))),
  })
  return {
    motion,
    m: motion,
    AnimatePresence: ({ children }: { children?: unknown }) => children,
    useReducedMotion: () => false,
  }
})
initI18n('en')

const tile = (label: string | RegExp) => screen.getByRole('button', { name: label })
const dialog = () => screen.queryByRole('dialog')

it('shows every way to learn as a closed card and no panel anywhere', () => {
  const { container } = render(<LearningWays />)
  expect(screen.getByText('Ways to learn')).toBeInTheDocument()
  for (const label of ['Books', 'Mastery Path', 'Practice', 'Immersive Reading']) {
    expect(tile(new RegExp(label))).toHaveAttribute('aria-haspopup', 'dialog')
    expect(tile(new RegExp(label))).toHaveAttribute('aria-expanded', 'false')
    expect(tile(new RegExp(label))).not.toHaveAttribute('aria-controls')
  }
  expect(container.querySelector('[role="dialog"]')).toBeNull()
  expect(dialog()).toBeNull()
})

it.each([
  ['Books', '/learning/books'],
  ['Mastery Path', '/learning/mastery'],
  ['Practice', '/learning/practice'],
  ['Immersive Reading', '/learning/reading'],
])('opening %s offers the whole library without pre-assigning a workspace', (label, route) => {
  render(<LearningWays />)
  fireEvent.click(tile(new RegExp(label)))
  const panel = screen.getByRole('dialog')
  expect(panel).toHaveAttribute('aria-modal', 'true')
  expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('href', route)
  expect(tile(new RegExp(label))).toHaveAttribute('aria-expanded', 'true')
  expect(tile(new RegExp(label))).toHaveAttribute('aria-controls', panel.id)
})

it('introduces the chosen way before asking for a commitment', () => {
  render(<LearningWays />)
  fireEvent.click(tile(/Books/))
  const panel = screen.getByRole('dialog')
  expect(panel).toHaveTextContent('Generate, browse and study your AI-authored books.')
  expect(panel).toHaveTextContent('Name a subject and DeepTutor writes you a book on it')
  expect(panel).toHaveTextContent('Edit the chapter spine before a word is written')
  expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Go back' })).toBeInTheDocument()
})

it('switching to another way swaps the introduction with it', async () => {
  render(<LearningWays />)
  fireEvent.click(tile(/Books/))
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  await waitFor(() => expect(dialog()).toBeNull())
  fireEvent.click(tile(/Mastery Path/))
  const panel = screen.getByRole('dialog')
  expect(panel).toHaveTextContent('You and the tutor settle the outline together')
  expect(panel).not.toHaveTextContent('writes you a book on it')
  expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('href', '/learning/mastery')
})

it('a click on the scrim closes the way and unlocks the page', async () => {
  const { container } = render(<LearningWays />)
  const books = tile(/Books/)
  fireEvent.click(books)
  const scrim = screen.getByRole('dialog').previousElementSibling as HTMLElement
  expect(scrim).toHaveAttribute('aria-hidden', 'true')
  fireEvent.click(scrim)
  await waitFor(() => expect(dialog()).toBeNull())
  expect(document.body.style.overflow).not.toBe('hidden')
  expect(container.inert).not.toBe(true)
  expect(books).toHaveFocus()
})

it('Escape closes the way and hands focus back to its tile', async () => {
  render(<LearningWays />)
  const practice = tile(/Practice/)
  fireEvent.click(practice)
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  await waitFor(() => expect(dialog()).toBeNull())
  expect(document.body.style.overflow).not.toBe('hidden')
  expect(practice).toHaveFocus()
})

it('keeps the rest of the page inert and cycles focus inside the open way', () => {
  const { container } = render(<LearningWays />)
  fireEvent.click(tile(/Immersive Reading/))
  const panel = screen.getByRole('dialog')
  expect(panel).toHaveFocus()
  expect(container.inert).toBe(true)
  expect(document.body.style.overflow).toBe('hidden')
  fireEvent.keyDown(panel, { key: 'Tab', shiftKey: true })
  expect(screen.getByRole('link', { name: 'Start' })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('link', { name: 'Start' }), { key: 'Tab' })
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
})

it('Go back returns to the grid with nothing left open', async () => {
  const { container } = render(<LearningWays />)
  const books = tile(/Books/)
  fireEvent.click(books)
  fireEvent.click(screen.getByRole('button', { name: 'Go back' }))
  await waitFor(() => expect(dialog()).toBeNull())
  expect(document.body.style.overflow).not.toBe('hidden')
  expect(container.inert).not.toBe(true)
  expect(books).toHaveFocus()
})
