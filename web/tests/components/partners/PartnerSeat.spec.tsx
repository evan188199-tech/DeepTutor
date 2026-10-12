import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PartnerSeat from '@/components/partners/group/PartnerSeat'
import type { PartnerGroupMember } from '@/lib/partner-groups-api'
import type { PartnerGroupMessage } from '@/lib/partner-groups-api'
import type { Seat } from '@/components/partners/group/useGroupSession'

vi.mock('next/dynamic', () => ({
  default:
    () =>
    ({ content }: { content: string }) => <span>{content}</span>,
}))
const t = (key: string) => key
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t, i18n: { language: 'en' } }),
}))

afterEach(cleanup)

const member = (overrides: Partial<PartnerGroupMember> = {}): PartnerGroupMember => ({
  partner_id: 'p1',
  name: 'Ada',
  description: '',
  emoji: '🧠',
  color: '#4f7a5b',
  running: false,
  ...overrides,
})

const message = (overrides: Partial<PartnerGroupMessage> = {}): PartnerGroupMessage => ({
  event_id: 'e1',
  turn_id: 't1',
  session_key: 'g1:s',
  role: 'partner',
  content: '',
  author_id: 'p1',
  author_name: 'Ada',
  created_at: '2026-10-12T00:00:00Z',
  mentions: [],
  error: false,
  kind: 'message',
  events: [],
  invocation_id: '',
  invocation: null,
  ...overrides,
})

const seat = (overrides: Partial<Seat> = {}): Seat => ({
  partnerId: 'p1',
  status: 'done',
  events: [],
  streamed: '',
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

it('renders an answered seat with speaker name, body and copy affordance', () => {
  render(
    <PartnerSeat
      seat={seat({
        message: message({ author_name: 'Ada', content: 'The gradient flows downhill.' }),
      })}
    />
  )
  expect(document.querySelector('[data-seat="p1"]')).toHaveAttribute('data-seat-status', 'done')
  expect(screen.getByText('Ada')).toBeInTheDocument()
  expect(screen.getByText('The gradient flows downhill.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
})

it('labels follow-up question seats without repeating the word on the seat', () => {
  render(
    <PartnerSeat
      seat={seat({
        message: message({ kind: 'invocation_question', content: 'Any objections?' }),
      })}
    />
  )
  expect(screen.getByText('Any objections?')).toBeInTheDocument()
  expect(screen.queryByText('Rebuttal')).not.toBeInTheDocument()
  expect(screen.queryByText('Follow-up')).not.toBeInTheDocument()
})

it('marks a debate rebuttal with the shared kind badge', () => {
  render(
    <PartnerSeat
      seat={seat({
        message: message({ kind: 'debate_rebuttal', content: 'I disagree with Ada.' }),
      })}
    />
  )
  expect(screen.getByText('Rebuttal')).toBeInTheDocument()
})

it('shows waiting and thinking status while a seat is in flight and withholds actions', () => {
  const { rerender } = render(<PartnerSeat seat={seat({ status: 'waiting' })} />)
  expect(screen.getByText('Waiting…')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument()

  rerender(<PartnerSeat seat={seat({ status: 'working', streamed: 'Partial answer so far…' })} />)
  expect(screen.getByText('Thinking…')).toBeInTheDocument()
  expect(screen.getByText('Partial answer so far…')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument()
})

it('falls back to a friendly line when an error seat carries no body', () => {
  render(<PartnerSeat seat={seat({ status: 'error' })} />)
  expect(screen.getByText('This Partner could not answer.')).toBeInTheDocument()
  expect(document.querySelector('[data-seat-body]')).toBeNull()
})

it('shows the failure body verbatim when an error seat carries content', () => {
  render(
    <PartnerSeat
      seat={seat({
        status: 'error',
        message: message({ content: 'Upstream provider timed out.', error: true }),
      })}
    />
  )
  expect(screen.getByText('Upstream provider timed out.')).toBeInTheDocument()
  expect(screen.queryByText('This Partner could not answer.')).not.toBeInTheDocument()
})

it('leaves the body slot empty for a settled seat with no content', () => {
  render(<PartnerSeat seat={seat({ status: 'done' })} />)
  expect(document.querySelector('[data-seat-body]')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument()
})

it('copies an answered body to the clipboard and flips the button to Copied', async () => {
  const writeText = stubClipboard()
  render(<PartnerSeat seat={seat({ message: message({ content: 'Copy me, please.' }) })} />)
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
  await screen.findByText('Copied')
  expect(writeText).toHaveBeenCalledWith('Copy me, please.')
})

it('quotes an answered body back into the composer with its member', () => {
  const onQuote = vi.fn()
  const ada = member()
  render(
    <PartnerSeat
      seat={seat({ message: message({ content: 'Quote me.' }) })}
      member={ada}
      onQuote={onQuote}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Follow up' }))
  expect(onQuote).toHaveBeenCalledTimes(1)
  expect(onQuote).toHaveBeenCalledWith(ada, 'Quote me.')
})

it('asks a peer to engage from the seat menu and closes it after the pick', () => {
  const onAskPeer = vi.fn()
  render(
    <PartnerSeat
      seat={seat({ message: message({ content: 'An answer.' }) })}
      onAskPeer={onAskPeer}
      peers={[member({ partner_id: 'p2', name: 'Grace' })]}
    />
  )
  expect(screen.queryByText(/Who should respond to/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Ask a peer' }))
  expect(screen.getByText(/Who should respond to/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Grace' }))
  expect(onAskPeer).toHaveBeenCalledWith('p2')
  expect(screen.queryByText(/Who should respond to/)).not.toBeInTheDocument()
})

it('reveals reasoning steps only when the seat carries private events', () => {
  const onOpenTrace = vi.fn()
  const { rerender } = render(
    <PartnerSeat
      seat={seat({ events: [{ type: 'thinking' }] as unknown as Seat['events'] })}
      onOpenTrace={onOpenTrace}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Reasoning steps' }))
  expect(onOpenTrace).toHaveBeenCalledTimes(1)

  rerender(<PartnerSeat seat={seat({ events: [] })} onOpenTrace={onOpenTrace} />)
  expect(screen.queryByRole('button', { name: 'Reasoning steps' })).not.toBeInTheDocument()
})

it('resolves the speaker name from message, then member, then partner id', () => {
  const { rerender } = render(
    <PartnerSeat
      seat={seat({ message: message({ author_name: 'Authored Name' }) })}
      member={member({ name: 'Member Name' })}
    />
  )
  expect(screen.getByText('Authored Name')).toBeInTheDocument()

  rerender(
    <PartnerSeat
      seat={seat({ streamed: 'still streaming' })}
      member={member({ name: 'Member Name' })}
    />
  )
  expect(screen.getByText('Member Name')).toBeInTheDocument()

  rerender(<PartnerSeat seat={seat({ partnerId: 'fallback-id' })} />)
  expect(screen.getByText('fallback-id')).toBeInTheDocument()
})
