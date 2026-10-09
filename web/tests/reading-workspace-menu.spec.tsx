import { render, renderHook } from '@testing-library/react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import {
  WorkspaceMenuContext,
  useWorkspaceMenuSection,
  type WorkspaceMenuItem,
  type WorkspaceMenuSection,
} from '@/components/reading/workspace-menu-context'

const Icon = (() => null) as unknown as LucideIcon

const exportItem: WorkspaceMenuItem = {
  key: 'export',
  icon: Icon,
  label: 'Export',
  onSelect: () => {},
}

interface Registration {
  section: WorkspaceMenuSection
  items: WorkspaceMenuItem[] | null
}

function makeHost(registry: Registration[]) {
  return {
    register: (
      section: WorkspaceMenuSection,
      items: WorkspaceMenuItem[] | null,
    ) => {
      registry.push({ section, items })
    },
  }
}

function wrapperFor(host: ReturnType<typeof makeHost>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <WorkspaceMenuContext.Provider value={host}>
        {children}
      </WorkspaceMenuContext.Provider>
    )
  }
}

function last<T>(values: T[]): T {
  return values[values.length - 1]
}

describe('useWorkspaceMenuSection', () => {
  it('reports no workspace host and never registers outside a provider', () => {
    const registry: Registration[] = []
    const { result } = renderHook(() =>
      useWorkspaceMenuSection('material', [exportItem]),
    )
    expect(result.current).toBe(false)
    expect(registry).toEqual([])
  })

  it('registers its items with the workspace host under its section', () => {
    const registry: Registration[] = []
    const { result } = renderHook(
      () => useWorkspaceMenuSection('material', [exportItem]),
      { wrapper: wrapperFor(makeHost(registry)) },
    )
    expect(result.current).toBe(true)
    expect(registry).toEqual([{ section: 'material', items: [exportItem] }])
  })

  it('publishes replacement items when the panel changes its offering', () => {
    const registry: Registration[] = []
    const printItem: WorkspaceMenuItem = {
      key: 'print',
      icon: Icon,
      label: 'Print',
      onSelect: () => {},
    }
    const { rerender } = renderHook(
      ({ items }: { items: WorkspaceMenuItem[] | null }) =>
        useWorkspaceMenuSection('material', items),
      {
        initialProps: { items: [exportItem] },
        wrapper: wrapperFor(makeHost(registry)),
      },
    )
    rerender({ items: [printItem] })
    expect(last(registry)).toEqual({ section: 'material', items: [printItem] })
  })

  it('clears its section as soon as the panel stops offering items', () => {
    const registry: Registration[] = []
    const { rerender } = renderHook(
      ({ items }: { items: WorkspaceMenuItem[] | null }) =>
        useWorkspaceMenuSection('material', items),
      {
        initialProps: { items: [exportItem] as WorkspaceMenuItem[] | null },
        wrapper: wrapperFor(makeHost(registry)),
      },
    )
    rerender({ items: null })
    expect(last(registry)).toEqual({ section: 'material', items: null })
  })

  it('unregisters from the menu on unmount', () => {
    const registry: Registration[] = []
    const { unmount } = renderHook(
      () => useWorkspaceMenuSection('conversation', [exportItem]),
      { wrapper: wrapperFor(makeHost(registry)) },
    )
    expect(registry).toHaveLength(1)
    unmount()
    expect(last(registry)).toEqual({ section: 'conversation', items: null })
    expect(registry).toHaveLength(2)
  })

  it('clears the old section before claiming a new one when the section changes', () => {
    const registry: Registration[] = []
    const { rerender } = renderHook(
      ({
        section,
        items,
      }: {
        section: WorkspaceMenuSection
        items: WorkspaceMenuItem[]
      }) => useWorkspaceMenuSection(section, items),
      {
        initialProps: { section: 'material' as WorkspaceMenuSection, items: [exportItem] },
        wrapper: wrapperFor(makeHost(registry)),
      },
    )
    rerender({ section: 'conversation', items: [exportItem] })
    expect(registry.slice(-2)).toEqual([
      { section: 'material', items: null },
      { section: 'conversation', items: [exportItem] },
    ])
  })

  it('does not re-register while the items identity is stable', () => {
    const registry: Registration[] = []
    const items: WorkspaceMenuItem[] = [exportItem]
    const { rerender } = renderHook(() => useWorkspaceMenuSection('material', items), {
      wrapper: wrapperFor(makeHost(registry)),
    })
    expect(registry).toHaveLength(1)
    rerender()
    rerender()
    expect(registry).toHaveLength(1)
  })

  it('converges both sections onto one host', () => {
    const registry: Registration[] = []
    const clearItem: WorkspaceMenuItem = {
      key: 'clear',
      icon: Icon,
      label: 'Clear conversation',
      onSelect: () => {},
    }
    function BothPanels() {
      const materialHosted = useWorkspaceMenuSection('material', [exportItem])
      const conversationHosted = useWorkspaceMenuSection('conversation', [clearItem])
      return (
        <div data-hosted={`${materialHosted ? 'material' : ''}${conversationHosted ? 'conversation' : ''}`} />
      )
    }
    render(
      <WorkspaceMenuContext.Provider value={makeHost(registry)}>
        <BothPanels />
      </WorkspaceMenuContext.Provider>,
    )
    expect(registry).toEqual([
      { section: 'material', items: [exportItem] },
      { section: 'conversation', items: [clearItem] },
    ])
  })
})
