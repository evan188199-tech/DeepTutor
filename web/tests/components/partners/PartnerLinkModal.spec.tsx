import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PartnerLinkModal from '@/components/partners/PartnerLinkModal'
import type { PartnerLink } from '@/lib/partners-api'

const fixture = vi.hoisted(() => ({
  createCode: vi.fn(),
  listLinks: vi.fn(),
  removeLink: vi.fn(),
}))
vi.mock('@/lib/partners-api', () => ({
  createPartnerLinkCode: fixture.createCode,
  listPartnerLinks: fixture.listLinks,
  removePartnerLink: fixture.removeLink,
}))
const t = (key: string, options?: Record<string, unknown>): string =>
  key.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    typeof options?.[name] === 'string' ? (options[name] as string) : `{{${name}}}`
  )
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t, i18n: { language: 'en' } }),
}))

afterEach(cleanup)

const link = (overrides: Partial<PartnerLink> = {}): PartnerLink => ({
  key: 'key-1',
  channel: 'qq',
  sender_id: '10001',
  linked_at: '2026-10-12T00:00:00Z',
  ...overrides,
})

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })
  return writeText
}

it('lists the chat accounts already connected to the partner', async () => {
  fixture.listLinks.mockResolvedValue([
    link(),
    link({ key: 'key-2', channel: 'telegram', sender_id: '@someone' }),
  ])
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  expect(await screen.findByText('qq · 10001')).toBeInTheDocument()
  expect(screen.getByText('telegram · @someone')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Disconnect' })).toHaveLength(2)
})

it('shows the empty state before any chat account is connected', async () => {
  fixture.listLinks.mockResolvedValue([])
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  expect(await screen.findByText('No chat accounts connected yet.')).toBeInTheDocument()
})

it('falls back to the empty list when loading the links fails', async () => {
  fixture.listLinks.mockRejectedValue(new Error('Network unavailable'))
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  expect(await screen.findByText('No chat accounts connected yet.')).toBeInTheDocument()
})

it('issues a single-use link code and surfaces the command to send', async () => {
  fixture.listLinks.mockResolvedValue([])
  fixture.createCode.mockResolvedValue({
    code: 'A1B2C3',
    expires_at: '2026-10-12T00:15:00Z',
    command: '/link A1B2C3',
  })
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  await screen.findByText('No chat accounts connected yet.')
  fireEvent.click(screen.getByRole('button', { name: /Get a link code/ }))
  expect(fixture.createCode).toHaveBeenCalledWith('p1')
  expect(await screen.findByText('/link A1B2C3')).toBeInTheDocument()
  expect(screen.getByText('Valid for 15 minutes, and usable once.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Get a link code/ })).not.toBeInTheDocument()
})

it('reports the failure and recovers when issuing a code fails', async () => {
  fixture.listLinks.mockResolvedValue([])
  fixture.createCode.mockRejectedValueOnce(new Error('Rate limited')).mockResolvedValueOnce({
    code: 'A1B2C3',
    expires_at: '2026-10-12T00:15:00Z',
    command: '/link A1B2C3',
  })
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  const issueButton = screen.getByRole('button', { name: /Get a link code/ })
  fireEvent.click(issueButton)
  expect(await screen.findByText("Couldn't create a code. Try again.")).toBeInTheDocument()
  await waitFor(() => expect(issueButton).not.toBeDisabled())
  fireEvent.click(issueButton)
  expect(await screen.findByText('/link A1B2C3')).toBeInTheDocument()
  expect(screen.queryByText("Couldn't create a code. Try again.")).not.toBeInTheDocument()
})

it('disables issuing only while a code request is in flight', async () => {
  fixture.listLinks.mockResolvedValue([])
  let resolveIssue: (value: { command: string }) => void = () => {}
  fixture.createCode.mockReturnValue(
    new Promise(resolve => {
      resolveIssue = resolve
    })
  )
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  const issueButton = await screen.findByRole('button', { name: /Get a link code/ })
  fireEvent.click(issueButton)
  expect(issueButton).toBeDisabled()
  await act(async () => {
    resolveIssue({ command: '/link A1B2C3' })
  })
  expect(await screen.findByText('/link A1B2C3')).toBeInTheDocument()
})

it('copies the issued command to the clipboard', async () => {
  const writeText = stubClipboard()
  fixture.listLinks.mockResolvedValue([])
  fixture.createCode.mockResolvedValue({
    code: 'A1B2C3',
    expires_at: '2026-10-12T00:15:00Z',
    command: '/link A1B2C3',
  })
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: /Get a link code/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Copy' }))
  await screen.findByText('Copied')
  expect(writeText).toHaveBeenCalledWith('/link A1B2C3')
})

it('disconnects an account and refreshes the list', async () => {
  fixture.listLinks
    .mockResolvedValueOnce([link()])
    .mockResolvedValueOnce([link({ key: 'key-2', channel: 'spam', sender_id: '20002' })])
  fixture.removeLink.mockResolvedValue(undefined)
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
  expect(fixture.removeLink).toHaveBeenCalledWith('p1', 'key-1')
  expect(await screen.findByText('spam · 20002')).toBeInTheDocument()
  expect(screen.queryByText('qq · 10001')).not.toBeInTheDocument()
})

it('reports when disconnecting an account fails', async () => {
  fixture.listLinks.mockResolvedValue([link()])
  fixture.removeLink.mockRejectedValue(new Error('Offline'))
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
  expect(
    await screen.findByText("Couldn't disconnect that account. Try again.")
  ).toBeInTheDocument()
  expect(screen.getByText('qq · 10001')).toBeInTheDocument()
})

it('closes from the close button', async () => {
  fixture.listLinks.mockResolvedValue([])
  const onClose = vi.fn()
  render(<PartnerLinkModal partnerId="p1" partnerName="Tutor" onClose={onClose} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('mentions the partner by name in the intro copy', async () => {
  fixture.listLinks.mockResolvedValue([])
  render(<PartnerLinkModal partnerId="p1" partnerName="Professor X" onClose={vi.fn()} />)
  expect(await screen.findByText(/message Professor X from/)).toBeInTheDocument()
  expect(screen.getByText('Link a chat account')).toBeInTheDocument()
})
