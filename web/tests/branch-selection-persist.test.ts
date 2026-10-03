import test from 'node:test'
import assert from 'node:assert/strict'
import { reconcileTurnIds, selectionsToPersistAfterReconcile } from '../lib/turn-reconcile'
import { buildVisiblePath, selectChildBranch, tipMessageId } from '../lib/message-branches'

type TreeMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  parentMessageId: number | null
  events?: Array<{ turn_id?: string }>
}

function longConversationWithEditedFork(): TreeMessage[] {
  const messages: TreeMessage[] = [
    { id: 1, role: 'user', content: 'question 1', parentMessageId: null },
    { id: 2, role: 'assistant', content: 'answer 1', parentMessageId: 1 },
  ]
  for (let round = 2; round <= 20; round++) {
    messages.push({
      id: round * 2 - 1,
      role: 'user' as const,
      content: `question ${round}`,
      parentMessageId: round * 2 - 2,
    })
    messages.push({
      id: round * 2,
      role: 'assistant' as const,
      content: `answer ${round}`,
      parentMessageId: round * 2 - 1,
    })
  }
  // The user edits the round-6 question (node 11), creating a fork with an
  // optimistic user row (-20) and its streaming assistant reply (-21).
  messages.push(
    { id: -20, role: 'user', content: 'edited question 6', parentMessageId: 11 },
    {
      id: -21,
      role: 'assistant',
      content: 'edited answer 6',
      parentMessageId: -20,
      events: [{ turn_id: 'turn_edit' }],
    }
  )
  return messages
}

function reconciledEditTurn(messages: TreeMessage[], selectedBranches: Record<string, number>) {
  return reconcileTurnIds(messages, selectedBranches, {
    turnId: 'turn_edit',
    userMessageId: 9001,
    assistantMessageId: 9002,
  })
}

test('a reconciled branch selection produces a persistable payload', () => {
  const messages = longConversationWithEditedFork()
  // ADD_USER_MSG recorded the fork selection optimistically.
  const selectedBranches = selectChildBranch({ '19': 20 }, 11, -20)
  const result = reconciledEditTurn(messages, selectedBranches)

  assert.equal(result.changed, true)
  assert.equal(result.selectedBranches['11'], 9001)

  const payload = selectionsToPersistAfterReconcile(selectedBranches, result)
  // The whole positive-id map is PUT (the server replaces the stored map),
  // so the pre-existing persisted entry must survive alongside the repair.
  assert.deepEqual(payload, { '19': 20, '11': 9001 })
})

test('a persisted reconciled selection keeps the edited branch visible after reload', () => {
  const messages = longConversationWithEditedFork()
  const selectedBranches = selectChildBranch({}, 11, -20)
  const result = reconciledEditTurn(messages, selectedBranches)
  const payload = selectionsToPersistAfterReconcile(selectedBranches, result)
  assert.ok(payload)

  // Reload: the client rehydrates selections from the server map that the
  // done handler PUT, and the default path must keep following the edit.
  const rehydrated = buildVisiblePath(result.messages, payload).messages
  assert.equal(rehydrated.at(-1)?.id, 9002)
  assert.equal(rehydrated.at(-1)?.content, 'edited answer 6')
  // The next send attaches to the edited branch's reply, not the old tip.
  assert.equal(tipMessageId(rehydrated), 9002)

  // Without the PUT the reload rehydrates an empty map and the
  // longest-continuation default hides the user's edited branch — the
  // wrong-parent attach #1614 describes.
  const stale = buildVisiblePath(result.messages, {}).messages
  assert.equal(stale.at(-1)?.id, 40)
  assert.equal(tipMessageId(stale), 40)
})

test('nothing is persisted when the reconcile leaves selections untouched', () => {
  const messages: TreeMessage[] = [
    { id: 1, role: 'user', content: 'q1', parentMessageId: null },
    {
      id: -21,
      role: 'assistant',
      content: 'a1',
      parentMessageId: 1,
      events: [{ turn_id: 'turn_tip' }],
    },
  ]
  const selectedBranches: Record<string, number> = {}
  const result = reconcileTurnIds(messages, selectedBranches, {
    turnId: 'turn_tip',
    userMessageId: 2,
    assistantMessageId: 3,
  })

  assert.equal(result.changed, true)
  assert.equal(selectionsToPersistAfterReconcile(selectedBranches, result), null)
})

test('an unchanged reconcile result persists nothing', () => {
  const messages: TreeMessage[] = [
    { id: 1, role: 'user', content: 'q1', parentMessageId: null },
    { id: 2, role: 'assistant', content: 'a1', parentMessageId: 1 },
  ]
  const selectedBranches = { '1': 2 }
  const result = reconcileTurnIds(messages, selectedBranches, {
    turnId: 'turn_done',
    userMessageId: 4,
    assistantMessageId: 5,
  })

  assert.equal(result.changed, false)
  assert.equal(selectionsToPersistAfterReconcile(selectedBranches, result), null)
})
