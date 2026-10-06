import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import PartnersPage from '@/app/(workspace)/partners/page'

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

// Regression guard for the #1228 pattern: a 403 on the partner list must not
// be swallowed into the "No partners yet" empty state. The fix has not landed
// yet, so the expectation is inverted with it.fails; when the fix arrives this
// body passes and the run goes red, at which point the wrapper is dropped.
it.fails(
  'renders a visible error instead of the empty roster when the partner list is forbidden',
  async () => {
    fetcher.mockImplementation(async () => forbidden())
    render(<PartnersPage />)
    await waitFor(() => expect(document.querySelector('.animate-spin')).toBeNull())
    expect(screen.queryByText('No partners yet')).toBeNull()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  },
)
