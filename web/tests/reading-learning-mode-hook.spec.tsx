import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useReadingLearningMode } from '@/components/reading/workspace/useLearningMode'

const LEARNING_KEY = 'reading-learning'

function seedLearning(workspaceId: string, panels: Record<string, unknown>) {
  sessionStorage.setItem(LEARNING_KEY, JSON.stringify({ workspaceId, panels }))
}

function visibleDialog() {
  const dialog = document.createElement('div')
  dialog.setAttribute('role', 'dialog')
  dialog.getBoundingClientRect = () => ({ width: 100 }) as unknown as DOMRect
  document.body.appendChild(dialog)
  return dialog
}

function pressEscape() {
  act(() => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  })
}

describe('useReadingLearningMode', () => {
  it('starts outside learning mode with both panels at their defaults', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    expect(result.current.learning).toBe(false)
    expect(result.current.companionOpen).toBe(true)
    expect(result.current.navigatorOpen).toBe(false)
    expect(result.current.mainRef.current).toBeNull()
  })

  it('enters learning with the outline open, the companion closed, and persists the entry snapshot', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.setCompanionOpen(false))
    act(() => result.current.setNavigatorOpen(true))
    act(() => result.current.openLearning())
    expect(result.current.learning).toBe(true)
    expect(result.current.companionOpen).toBe(false)
    expect(result.current.navigatorOpen).toBe(true)
    expect(JSON.parse(sessionStorage.getItem(LEARNING_KEY) ?? 'null')).toEqual({
      panels: { companionOpen: false, navigatorOpen: true },
      workspaceId: 'ws-1',
    })
  })

  it('exiting restores the entry panels and clears the persisted snapshot', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.setCompanionOpen(false))
    act(() => result.current.setNavigatorOpen(true))
    act(() => result.current.openLearning())
    act(() => result.current.closeLearning())
    expect(result.current.learning).toBe(false)
    expect(result.current.companionOpen).toBe(false)
    expect(result.current.navigatorOpen).toBe(true)
    expect(sessionStorage.getItem(LEARNING_KEY)).toBeNull()
  })

  it('reopens straight into learning for the same workspace', () => {
    seedLearning('ws-1', { companionOpen: true, navigatorOpen: false })
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    expect(result.current.learning).toBe(true)
    expect(result.current.companionOpen).toBe(false)
    expect(result.current.navigatorOpen).toBe(true)
  })

  it('ignores a saved snapshot that belongs to another workspace', () => {
    seedLearning('ws-2', { companionOpen: true, navigatorOpen: true })
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    expect(result.current.learning).toBe(false)
    expect(result.current.companionOpen).toBe(true)
    expect(result.current.navigatorOpen).toBe(false)
  })

  it('normalizes the legacy collapsed-outline flag to the single panel state', () => {
    seedLearning('ws-1', { companionOpen: true, navigatorCollapsed: false })
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.closeLearning())
    expect(result.current.learning).toBe(false)
    expect(result.current.companionOpen).toBe(true)
    expect(result.current.navigatorOpen).toBe(true)
  })

  it('survives malformed persisted state', () => {
    sessionStorage.setItem(LEARNING_KEY, '{broken json')
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    expect(result.current.learning).toBe(false)
    expect(result.current.companionOpen).toBe(true)
  })

  it('Escape exits learning mode and clears the persisted snapshot', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.openLearning())
    pressEscape()
    expect(result.current.learning).toBe(false)
    expect(sessionStorage.getItem(LEARNING_KEY)).toBeNull()
  })

  it('keeps learning mode while the document is fullscreen', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.openLearning())
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: document.documentElement,
    })
    pressEscape()
    expect(result.current.learning).toBe(true)
    Reflect.deleteProperty(document as unknown as object, 'fullscreenElement')
  })

  it('does not steal Escape while a dialog is visible', () => {
    const dialog = visibleDialog()
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.openLearning())
    pressEscape()
    expect(result.current.learning).toBe(true)
    dialog.remove()
    pressEscape()
    expect(result.current.learning).toBe(false)
  })

  it('isolates the shell from siblings while learning and restores them on unmount', () => {
    const { result, unmount } = renderHook(() => useReadingLearningMode('ws-1'))
    const shell = document.createElement('div')
    const aside = document.createElement('aside')
    Object.defineProperty(aside, 'inert', {
      configurable: true,
      value: false,
      writable: true,
    })
    const banner = document.createElement('div')
    const main = document.createElement('main')
    shell.append(aside, banner, main)
    document.body.appendChild(shell)
    result.current.mainRef.current = main

    act(() => result.current.openLearning())
    expect(aside.inert).toBe(true)
    expect(banner.inert).toBe(true)

    unmount()
    expect(aside.inert).toBe(false)
    expect(banner.inert).toBeUndefined()
    shell.remove()
  })

  it('manual panel setters work while not learning', () => {
    const { result } = renderHook(() => useReadingLearningMode('ws-1'))
    act(() => result.current.setNavigatorOpen(true))
    expect(result.current.navigatorOpen).toBe(true)
    act(() => result.current.setCompanionOpen(false))
    expect(result.current.companionOpen).toBe(false)
    expect(result.current.learning).toBe(false)
  })
})
