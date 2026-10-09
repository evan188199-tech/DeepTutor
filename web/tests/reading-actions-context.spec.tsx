import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import {
  ReadingActionsContext,
  focusReadingComposer,
  useReadingActions,
  type ReadingActionsValue,
} from '@/components/reading/reading-actions-context'

const sharedValue: ReadingActionsValue = {
  ageMode: 'default',
  actions: [],
  cards: [],
  speaking: false,
  busyKey: '',
  run: async () => {},
  stopSpeaking: () => {},
  dismiss: () => {},
}

function provider({ children }: { children: ReactNode }) {
  return (
    <ReadingActionsContext.Provider value={sharedValue}>
      {children}
    </ReadingActionsContext.Provider>
  )
}

describe('useReadingActions', () => {
  it('returns null outside a reading workspace', () => {
    const { result } = renderHook(() => useReadingActions())
    expect(result.current).toBeNull()
  })

  it('exposes the workspace shared actions inside the provider', () => {
    const { result } = renderHook(() => useReadingActions(), { wrapper: provider })
    expect(result.current).toBe(sharedValue)
    expect(result.current?.actions).toEqual([])
    expect(result.current?.busyKey).toBe('')
  })
})

describe('focusReadingComposer', () => {
  it('focuses the companion composer without touching its draft', () => {
    const host = document.createElement('div')
    host.setAttribute('data-reading-composer', '')
    const textarea = document.createElement('textarea')
    textarea.value = 'half-typed draft'
    host.appendChild(textarea)
    document.body.appendChild(host)

    focusReadingComposer()

    expect(document.activeElement).toBe(textarea)
    expect(textarea.value).toBe('half-typed draft')
    host.remove()
  })

  it('is a no-op when no composer is mounted', () => {
    focusReadingComposer()
    expect(document.activeElement).toBe(document.body)
  })
})
