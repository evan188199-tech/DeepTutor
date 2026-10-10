import React from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PersonasSection from '@/components/space/PersonasSection'
import * as personasApi from '@/lib/personas-api'
import type { PersonaDetail, PersonaInfo } from '@/lib/personas-api'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))
// The viewer body is lazy-loaded via next/dynamic; stub the loader so the
// rendered markdown shows up as plain text (same boundary stub as
// partner-chat-continuity.spec.tsx).
vi.mock('next/dynamic', () => ({
  default:
    () =>
    ({ content }: { content: string }) => <div>{content}</div>,
}))
vi.mock('@/lib/personas-api', () => ({
  listPersonas: vi.fn(),
  getPersona: vi.fn(),
  createPersona: vi.fn(),
  updatePersona: vi.fn(),
  deletePersona: vi.fn(),
}))

const listPersonas = vi.mocked(personasApi.listPersonas)
const getPersona = vi.mocked(personasApi.getPersona)
const createPersona = vi.mocked(personasApi.createPersona)
const updatePersona = vi.mocked(personasApi.updatePersona)
const deletePersona = vi.mocked(personasApi.deletePersona)

const userPersona: PersonaInfo = {
  name: 'patient-tutor',
  description: 'A patient tutor',
  source: 'user',
  read_only: false,
}

const presetPersona: PersonaInfo = {
  name: 'blunt-reviewer',
  description: '',
  source: 'admin',
  read_only: true,
}

const userDetail: PersonaDetail = {
  ...userPersona,
  content: 'body text',
}

beforeEach(() => {
  listPersonas.mockResolvedValue([userPersona, presetPersona])
})

it('loads personas with a forced refresh and hides edit/delete for read-only presets', async () => {
  render(<PersonasSection />)

  expect(await screen.findByText('patient-tutor')).toBeVisible()
  expect(screen.getByText('blunt-reviewer')).toBeVisible()
  expect(screen.getByText('A patient tutor')).toBeVisible()
  expect(screen.getByText('No description.')).toBeVisible()
  expect(screen.getByText('Preset')).toBeVisible()
  expect(screen.getByText(/2 personas\.count\.suffix/)).toBeVisible()
  expect(listPersonas).toHaveBeenCalledWith({ force: true })
  expect(screen.getAllByLabelText('Edit')).toHaveLength(1)
  expect(screen.getAllByLabelText('Delete')).toHaveLength(1)
})

it('shows a loading spinner while the list request is in flight', async () => {
  let resolveList: (items: PersonaInfo[]) => void = () => {}
  listPersonas.mockReturnValue(
    new Promise(resolve => {
      resolveList = resolve
    })
  )

  render(<PersonasSection />)

  expect(document.querySelector('.animate-spin')).not.toBeNull()
  await act(async () => {
    resolveList([userPersona])
  })
  expect(await screen.findByText('patient-tutor')).toBeVisible()
})

it('shows the empty state and opens the create dialog from it', async () => {
  listPersonas.mockResolvedValue([])

  render(<PersonasSection />)

  expect(await screen.findByText('No personas yet')).toBeVisible()
  fireEvent.click(screen.getByText('Create your first persona'))
  expect(await screen.findByRole('heading', { level: 3, name: 'New persona' })).toBeVisible()
  expect(screen.getByPlaceholderText('e.g. patient-tutor')).toHaveValue('')
})

it('surfaces list load failures in the error banner', async () => {
  listPersonas.mockRejectedValue(new Error('boom list'))

  render(<PersonasSection />)

  expect(await screen.findByText('boom list')).toBeVisible()
  expect(screen.queryByText('patient-tutor')).toBeNull()
})

it('slugifies the name as typed, creates the persona, closes the dialog, and reloads', async () => {
  createPersona.mockResolvedValue(userPersona)
  const { container } = render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByText('New persona'))
  const nameInput = screen.getByPlaceholderText('e.g. patient-tutor')
  fireEvent.change(nameInput, { target: { value: 'My Tutor!' } })
  expect(nameInput).toHaveValue('my-tutor')
  fireEvent.change(screen.getByPlaceholderText('Short summary shown in the picker'), {
    target: { value: 'Friendly helper' },
  })
  const textarea = container.querySelector('textarea')
  expect(textarea).not.toBeNull()
  fireEvent.change(textarea!, { target: { value: 'Hello body' } })

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() =>
    expect(createPersona).toHaveBeenCalledWith({
      name: 'my-tutor',
      description: 'Friendly helper',
      content: 'Hello body',
    })
  )
  await waitFor(() => expect(listPersonas).toHaveBeenCalledTimes(2))
  expect(screen.queryByPlaceholderText('e.g. patient-tutor')).toBeNull()
})

it('blocks saving when the name is empty', async () => {
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByText('New persona'))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByText('Name is required')).toBeVisible()
  expect(createPersona).not.toHaveBeenCalled()
})

it('blocks saving when the slugified name exceeds the length limit', async () => {
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByText('New persona'))
  fireEvent.change(screen.getByPlaceholderText('e.g. patient-tutor'), {
    target: { value: 'a'.repeat(70) },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(
    await screen.findByText(
      'Name must use only lowercase letters, digits, and hyphens, and must start with a letter or digit.'
    )
  ).toBeVisible()
  expect(createPersona).not.toHaveBeenCalled()
})

it('loads the persona into the edit dialog and renames it on save', async () => {
  getPersona.mockResolvedValue(userDetail)
  updatePersona.mockResolvedValue(userPersona)
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Edit'))
  const nameInput = await screen.findByPlaceholderText('e.g. patient-tutor')
  await waitFor(() => expect(nameInput).toHaveValue('patient-tutor'))
  fireEvent.change(nameInput, { target: { value: 'kind-tutor' } })

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() =>
    expect(updatePersona).toHaveBeenCalledWith('patient-tutor', {
      description: 'A patient tutor',
      content: 'body text',
      rename_to: 'kind-tutor',
    })
  )
  await waitFor(() => expect(listPersonas).toHaveBeenCalledTimes(2))
  expect(screen.queryByPlaceholderText('e.g. patient-tutor')).toBeNull()
})

it('omits rename_to when the edited name is unchanged', async () => {
  getPersona.mockResolvedValue(userDetail)
  updatePersona.mockResolvedValue(userPersona)
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Edit'))
  await screen.findByPlaceholderText('e.g. patient-tutor')
  fireEvent.change(screen.getByPlaceholderText('Short summary shown in the picker'), {
    target: { value: 'Updated desc' },
  })

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() =>
    expect(updatePersona).toHaveBeenCalledWith('patient-tutor', {
      description: 'Updated desc',
      content: 'body text',
      rename_to: undefined,
    })
  )
})

it('keeps the edit dialog open with the load error when getPersona fails', async () => {
  getPersona.mockRejectedValue(new Error('boom detail'))
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Edit'))

  expect(await screen.findByText('boom detail')).toBeVisible()
  expect(screen.getByRole('heading', { level: 3, name: 'Edit persona' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
})

it('opens the viewer with frontmatter-stripped content and can jump into the editor', async () => {
  getPersona.mockResolvedValue({
    ...userDetail,
    content: '---\nname: patient-tutor\n---\n\nPlaybook body',
  })
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByRole('button', { name: 'View persona: patient-tutor' }))

  const viewerDialog = await screen.findByRole('dialog')
  expect(within(viewerDialog).getByText('Playbook body')).toBeVisible()
  expect(within(viewerDialog).getByText('A patient tutor')).toBeVisible()
  expect(screen.queryByText(/name: patient-tutor/)).toBeNull()

  fireEvent.click(within(viewerDialog).getByRole('button', { name: 'Edit' }))
  expect(await screen.findByRole('heading', { level: 3, name: 'Edit persona' })).toBeVisible()
  expect(screen.queryByText('Playbook body')).toBeNull()
})

it('shows the viewer error box when loading the persona body fails', async () => {
  getPersona.mockRejectedValue(new Error('boom view'))
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByRole('button', { name: 'View persona: patient-tutor' }))

  expect(await screen.findByText('boom view')).toBeVisible()
  expect(screen.getByRole('dialog')).toBeVisible()
})

it('does not delete when the confirmation is canceled', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Delete'))

  expect(confirm).toHaveBeenCalledWith('Delete persona "{{name}}"?')
  expect(deletePersona).not.toHaveBeenCalled()
})

it('deletes the persona after confirmation and reloads the list', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  deletePersona.mockResolvedValue(undefined)
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Delete'))

  await waitFor(() => expect(deletePersona).toHaveBeenCalledWith('patient-tutor'))
  await waitFor(() => expect(listPersonas).toHaveBeenCalledTimes(2))
})

it('surfaces delete failures in the top-level error banner and clears the spinner', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  deletePersona.mockRejectedValue(new Error('boom delete'))
  render(<PersonasSection />)
  await screen.findByText('patient-tutor')

  fireEvent.click(screen.getByLabelText('Delete'))

  expect(await screen.findByText('boom delete')).toBeVisible()
  expect(screen.getByLabelText('Delete')).toBeEnabled()
})
