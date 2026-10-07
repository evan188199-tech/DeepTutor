import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import StarterSuggestions from '@/components/chat/home/StarterSuggestions'

const fetcher = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiFetch: fetcher, apiUrl: (path: string) => path }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))
vi.mock('@/lib/workspace-scope', () => ({
  activeWorkspaceId: () => '',
  scopedUrl: (path: string) => path,
}))

const forbidden = () => ({
  ok: false,
  status: 403,
  json: async () => ({ detail: 'Forbidden' }),
})

// Regression guard for the #1228 pattern on /chat home: the suggestions read
// bails out with null on any non-ok response, so the home slot must still
// keep its visible manual control and the explicit error note instead of
// vanishing into an empty state.
it(
  'keeps the visible error note instead of silently dropping the slot when suggestions are forbidden',
  async () => {
    fetcher.mockImplementation(async () => forbidden())
    render(<StarterSuggestions onPick={() => {}} />)
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        '/api/dashboard/suggestions',
        expect.objectContaining({ cache: 'no-store' }),
      ),
    )
    expect(
      await screen.findByText('Suggestions could not be generated. Please try again.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suggest something else' })).toBeNull()
  },
)
