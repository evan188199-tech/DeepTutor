import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import UsageSettingsSection from '@/features/settings/sections/UsageSettingsSection'
import UsageActivity from '@/features/settings/components/UsageActivity'
import { activityCalendar, type DailyUsage, type UsageStatistics } from '@/lib/usage-statistics'

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), push: vi.fn(), search: 'year=2024' }))
vi.mock('@/lib/usage-statistics', async original => ({
  ...await original<object>(),
  fetchUsageStatistics: mocks.fetch,
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}))
vi.mock('@/components/settings/shared', () => ({
  SettingsPageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) =>
      key.replace(/{{(.*?)}}/g, (_, k) => String(vars?.[k] ?? k)),
    i18n: { language: 'en' },
  }),
}))

const usageDay = (date: string, turns = 0, totalTokens = 0): DailyUsage => ({
  date,
  turns,
  total_calls: turns,
  total_tokens: totalTokens,
  tracked_turns: turns,
})
const totals = {
  total_tokens: 200,
  prompt_tokens: 180,
  completion_tokens: 20,
  total_calls: 5,
  cache_read_input_tokens: 90,
  cache_creation_input_tokens: 0,
  cache_input_tokens: 180,
  cache_reported_calls: 5,
  cache_hit_rate: 0.5,
  ttft_seconds: 1.2,
  tokens_per_second: 40,
  duration_seconds: 8,
  estimated_calls: 0,
}
const snapshot = (year: number, overrides: Partial<UsageStatistics> = {}): UsageStatistics => ({
  year,
  timezone: 'UTC',
  totals,
  days: activityCalendar([usageDay('2024-02-29', 3, 200)], year).dates,
  models: [{ ...totals, provider: 'zhipu', model: 'glm-test' }],
  active_days: 1,
  sessions: 1,
  turns: 3,
  tracked_turns: 3,
  updated_at: 1709164800,
  ...overrides,
})
const deferred = () => {
  let resolve!: (value: UsageStatistics) => void
  const promise = new Promise<UsageStatistics>(done => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  mocks.search = 'year=2024'
  mocks.fetch.mockReset()
  mocks.push.mockReset()
})

it('shows the loading placeholder and disables refresh until the first snapshot lands', async () => {
  const first = deferred()
  mocks.fetch.mockImplementationOnce(() => first.promise)
  render(<UsageSettingsSection />)
  expect(screen.getByRole('status')).toHaveTextContent('Loading usage…')
  expect(screen.getByRole('button', { name: 'Refresh usage' })).toBeDisabled()
  first.resolve(snapshot(2024))
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByRole('button', { name: 'Refresh usage' })).toBeEnabled()
})

it('refetches the same year from refresh and marks the panel busy while pending', async () => {
  mocks.fetch.mockResolvedValueOnce(snapshot(2024))
  const view = render(<UsageSettingsSection />)
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(mocks.fetch).toHaveBeenCalledTimes(1)
  const second = deferred()
  mocks.fetch.mockImplementationOnce(() => second.promise)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh usage' }))
  expect(screen.getByRole('button', { name: 'Refresh usage' })).toBeDisabled()
  expect(view.container.querySelector('[aria-busy="true"]')).not.toBeNull()
  second.resolve(snapshot(2024))
  await waitFor(() =>
    expect(view.container.querySelector('[aria-busy="true"]')).toBeNull()
  )
  expect(screen.getByText('glm-test')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Refresh usage' })).toBeEnabled()
  expect(mocks.fetch).toHaveBeenNthCalledWith(2, 2024, expect.any(AbortSignal))
})

it('keeps the failure alert across repeated retries and clears it once a retry succeeds', async () => {
  mocks.fetch
    .mockRejectedValueOnce(new Error('offline'))
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(snapshot(2024))
  render(<UsageSettingsSection />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to load usage statistics.'
  )
  expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to load usage statistics.'
  )
  expect(screen.queryByText('No recorded model usage for this year.')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('renders a zero-usage year as an explicit empty state with placeholder metrics', async () => {
  mocks.fetch.mockResolvedValue(
    snapshot(2024, {
      totals: { ...totals, total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, cache_hit_rate: null },
      days: activityCalendar([], 2024).dates,
      models: [],
      active_days: 0,
      sessions: 0,
      turns: 0,
      tracked_turns: 0,
    })
  )
  render(<UsageSettingsSection />)
  expect(await screen.findByText('No recorded model usage for this year.')).toBeVisible()
  expect(screen.queryByText('glm-test')).toBeNull()
  expect(screen.getAllByText('—')).toHaveLength(4)
  expect(screen.getByText('0 active days · 0 activities')).toBeVisible()
})

it('clamps year navigation at the current-year boundary', async () => {
  const currentYear = new Date().getFullYear()
  mocks.search = `year=${currentYear}`
  mocks.fetch.mockResolvedValue(snapshot(currentYear))
  render(<UsageSettingsSection />)
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(mocks.fetch).toHaveBeenCalledWith(currentYear, expect.any(AbortSignal))
  expect(screen.getByRole('button', { name: 'Next year' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Previous year' }))
  expect(mocks.push).toHaveBeenCalledWith(`/settings/usage?year=${currentYear - 1}`, {
    scroll: false,
  })
})

it('steps to the next year through the URL when below the boundary', async () => {
  mocks.fetch.mockResolvedValue(snapshot(2024))
  render(<UsageSettingsSection />)
  expect(await screen.findByText('glm-test')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Next year' }))
  expect(mocks.push).toHaveBeenCalledWith('/settings/usage?year=2025', { scroll: false })
})

it('renders dashes for unmeasured latency metrics and keeps provider subtitles', async () => {
  mocks.fetch.mockResolvedValue(
    snapshot(2024, {
      models: [
        { ...totals, provider: 'zhipu', model: 'glm-test', ttft_seconds: null, tokens_per_second: null, cache_hit_rate: null },
      ],
    })
  )
  render(<UsageSettingsSection />)
  const row = await screen.findByText('glm-test').then(node => node.closest('tr')!)
  expect(within(row).getByText('zhipu')).toBeVisible()
  expect(within(row).getAllByText('—')).toHaveLength(3)
})

it('shows the zero-activity summary and prompts for a year without usage', () => {
  render(<UsageActivity days={[]} year={2024} activeDays={0} turns={0} />)
  expect(screen.getByText('0 active days · 0 activities')).toBeVisible()
  expect(screen.getByText('Daily activity')).toBeVisible()
  const days = screen.getAllByRole('button')
  expect(days).toHaveLength(366)
  expect(days.every(button => !button.hasAttribute('disabled'))).toBe(true)
})

it('updates the live activity summary when a day is hovered', () => {
  const view = render(
    <UsageActivity days={[usageDay('2024-02-29', 3, 200)]} year={2024} activeDays={1} turns={3} />
  )
  const live = view.container.querySelector('[aria-live="polite"]')!
  expect(live).toHaveTextContent('Daily activity')
  const leap = screen.getByRole('button', { name: /2024-02-29 · 3 activities · 200 tokens/ })
  fireEvent.mouseEnter(leap)
  expect(leap).toHaveAttribute('aria-pressed', 'true')
  expect(live).toHaveTextContent('2024-02-29 · 3 activities · 200 tokens')
})

it('moves keyboard focus across weeks and clamps at the calendar start', () => {
  render(<UsageActivity days={[usageDay('2024-02-29', 3, 200)]} year={2024} activeDays={1} turns={3} />)
  const leap = screen.getByRole('button', { name: /2024-02-29/ })
  fireEvent.keyDown(leap, { key: 'ArrowLeft' })
  expect(screen.getByRole('button', { name: /2024-02-22/ })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('button', { name: /2024-02-22/ }), { key: 'ArrowUp' })
  expect(screen.getByRole('button', { name: /2024-02-21/ })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('button', { name: /2024-02-21/ }), { key: 'Home' })
  expect(screen.getByRole('button', { name: /2024-01-01/ })).toHaveFocus()
})

it('disables future days and keeps End-key focus in the past', () => {
  const year = new Date().getFullYear()
  const today = new Intl.DateTimeFormat('en-CA').format(new Date())
  render(<UsageActivity days={[]} year={year} activeDays={0} turns={0} />)
  const lastDay = screen.getByRole('button', { name: new RegExp(`${year}-12-31 · 0 activities`) })
  if (`${year}-12-31` > today) expect(lastDay).toBeDisabled()
  const todayButton = screen.getByRole('button', { name: new RegExp(`${today} · 0 activities`) })
  expect(todayButton).toBeEnabled()
  fireEvent.keyDown(todayButton, { key: 'End' })
  expect(todayButton).toHaveFocus()
})

it('labels calendar months and only the sparse weekday column', () => {
  render(<UsageActivity days={[]} year={2024} activeDays={0} turns={0} />)
  expect(screen.getByText('Jan')).toBeVisible()
  expect(screen.getByText('Feb')).toBeVisible()
  expect(screen.getByText('Dec')).toBeVisible()
  expect(screen.getByText('Mon')).toBeVisible()
  expect(screen.getByText('Wed')).toBeVisible()
  expect(screen.getByText('Fri')).toBeVisible()
  expect(screen.queryByText('Tue')).toBeNull()
})
