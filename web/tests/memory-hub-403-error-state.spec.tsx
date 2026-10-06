import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import MemoryHub from '@/components/memory/MemoryHub'

const fetcher = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiFetch: fetcher, apiUrl: (path: string) => path }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

const forbidden = () => ({
  ok: false,
  status: 403,
  json: async () => ({ detail: 'Forbidden' }),
})

// Regression guard for the #1228 pattern: the memory overview response was
// parsed without an ok check, so a 403 body rendered as zeroed layer stats.
// The fix has not landed yet, so the expectation is inverted with it.fails;
// when the fix arrives this body passes and the run goes red, at which point
// the wrapper is dropped.
it.fails(
  'renders a visible error instead of zeroed layer stats when the memory overview is forbidden',
  async () => {
    fetcher.mockImplementation(async () => forbidden())
    render(<MemoryHub />)
    await waitFor(() => expect(document.querySelector('.animate-spin')).toBeNull())
    expect(screen.queryByText('0')).toBeNull()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  },
)
