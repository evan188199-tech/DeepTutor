import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AboutSettingsSection from '@/features/settings/sections/AboutSettingsSection'
import type { AppUpdateStatus, UpdateJob } from '@/lib/app-update'

const mocks = vi.hoisted(() => ({
  fetchStatus: vi.fn(),
  check: vi.fn(),
  request: vi.fn(),
  fetchJob: vi.fn(),
}))

vi.mock('@/lib/app-update', () => ({
  fetchAppUpdateStatus: mocks.fetchStatus,
  checkAppUpdate: mocks.check,
  requestAppUpdate: mocks.request,
  fetchAppUpdateJob: mocks.fetchJob,
  updateJobIsActive: (value: string) =>
    ['pending', 'handoff', 'running', 'restarting'].includes(value),
}))
vi.mock('react-i18next', () => {
  const t = (key: string, vars?: Record<string, unknown>) =>
    key.replace(/{{(.*?)}}/g, (_, k: string) => String(vars?.[k] ?? k))
  const value = { t, i18n: { language: 'en' } }
  return { useTranslation: () => value }
})
vi.mock('@/features/settings/store/SettingsStore', () => ({
  useSettings: () => ({ applying: false, draftRevision: 0 }),
}))
vi.mock('@/features/settings/store/useStagedSettings', () => ({
  useStagedSettings: (_key: string, live: unknown, setLive: unknown) => [live, setLive],
}))

const release = (version: string, over: Record<string, unknown> = {}) => ({
  version,
  name: `DeepTutor ${version}`,
  published_at: '2026-10-10T00:00:00Z',
  url: `https://github.com/HKUDS/DeepTutor/releases/tag/v${version}`,
  excerpt: '',
  migration_warning: false,
  ...over,
})

const status = (over: Partial<AppUpdateStatus> = {}): AppUpdateStatus => ({
  current_version: 'v1.6.14',
  check_enabled: true,
  checked_at: '2026-10-11T08:00:00Z',
  cached: true,
  check_error: '',
  update_available: false,
  release: release('v1.6.14'),
  installation: {
    mode: 'pypi',
    automatic_update: true,
    command: 'pip install -U deeptutor',
    reason: '',
  },
  launcher_managed: true,
  is_admin: true,
  job: null,
  ...over,
})

const job = (over: Partial<UpdateJob> = {}): UpdateJob => ({
  id: 'job-1',
  status: 'succeeded',
  current_version: 'v1.6.14',
  target_version: 'v1.7.0',
  created_at: '2026-10-11T08:00:00Z',
  started_at: null,
  finished_at: '2026-10-11T08:01:00Z',
  error: null,
  restart_count: 0,
  ...over,
})

const available = status({
  update_available: true,
  release: release('v1.7.0', { excerpt: 'Grounded research primitives.' }),
})

beforeEach(() => {
  mocks.fetchStatus.mockReset()
  mocks.check.mockReset()
  mocks.request.mockReset()
  mocks.fetchJob.mockReset()
  mocks.fetchStatus.mockResolvedValue(available)
})

it('shows the cached version result without checking or installing on its own', async () => {
  render(<AboutSettingsSection />)
  expect(await screen.findByText('v1.7.0')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Check now' })).toBeVisible()
  expect(mocks.fetchStatus).toHaveBeenCalledTimes(1)
  expect(mocks.check).not.toHaveBeenCalled()
  expect(mocks.request).not.toHaveBeenCalled()
})

it('reports an available release only after the manual check runs', async () => {
  mocks.fetchStatus.mockResolvedValue(status())
  mocks.check.mockResolvedValue(available)
  render(<AboutSettingsSection />)
  await screen.findByRole('button', { name: 'Check now' })
  expect(screen.queryByRole('button', { name: 'Update to v1.7.0' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Check now' }))
  expect(await screen.findByRole('button', { name: 'Update to v1.7.0' })).toBeVisible()
  expect(screen.getByText('Grounded research primitives.')).toBeVisible()
  expect(mocks.check).toHaveBeenCalledTimes(1)
  expect(mocks.request).not.toHaveBeenCalled()
  expect(mocks.fetchJob).not.toHaveBeenCalled()
})

it('returns to the up-to-date result when the check finds nothing newer', async () => {
  mocks.check.mockResolvedValue(status())
  render(<AboutSettingsSection />)
  expect(await screen.findByRole('button', { name: 'Update to v1.7.0' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Check now' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Update to v1.7.0' })).toBeNull())
  expect(await screen.findByRole('button', { name: 'Check now' })).toBeVisible()
  expect(screen.getAllByText('v1.6.14').length).toBeGreaterThan(1)
  expect(mocks.request).not.toHaveBeenCalled()
})

it('surfaces a failed check without touching the install endpoints', async () => {
  mocks.fetchStatus.mockResolvedValue(status())
  mocks.check.mockRejectedValue(new Error('GitHub rate limit reached'))
  render(<AboutSettingsSection />)
  fireEvent.click(await screen.findByRole('button', { name: 'Check now' }))
  expect(await screen.findByText('GitHub rate limit reached')).toBeVisible()
  expect(mocks.request).not.toHaveBeenCalled()
})

it('reports when the cached status itself cannot be loaded', async () => {
  mocks.fetchStatus.mockRejectedValue(new Error('offline'))
  render(<AboutSettingsSection />)
  expect(await screen.findByText('offline')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Check now' })).toBeNull()
  expect(mocks.check).not.toHaveBeenCalled()
})

it('requires explicit confirmation before requesting the update job', async () => {
  mocks.request.mockResolvedValue(job())
  render(<AboutSettingsSection />)
  fireEvent.click(await screen.findByRole('button', { name: 'Update to v1.7.0' }))
  const dialog = await screen.findByRole('alertdialog')
  expect(dialog).toHaveTextContent('Update and restart DeepTutor?')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  expect(mocks.request).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Update to v1.7.0' }))
  fireEvent.click(
    within(await screen.findByRole('alertdialog')).getByRole('button', {
      name: 'Update and restart',
    })
  )
  await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(1))
  expect(await screen.findByText('updateJob.succeeded')).toBeVisible()
  expect(mocks.fetchJob).not.toHaveBeenCalled()
})

it('keeps the manual check and update actions admin-only', async () => {
  mocks.fetchStatus.mockResolvedValue(
    status({ is_admin: false, update_available: true, release: release('v1.7.0') })
  )
  render(<AboutSettingsSection />)
  expect(await screen.findByText('v1.7.0')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Check now' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Update to v1.7.0' })).toBeNull()
  expect(screen.getByText('On')).toBeVisible()
})
