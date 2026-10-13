import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LevelUpCelebration } from '@/components/space/learning/LevelUpCelebration'

type Ctx2D = ReturnType<typeof make2dContext>

function make2dContext() {
  return {
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    scale: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    setTransform: vi.fn(),
  }
}

const asCtx = (ctx: Ctx2D) => ctx as unknown as CanvasRenderingContext2D
const stubCtx = () => {
  const ctx = make2dContext()
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue(asCtx(ctx))
  return ctx
}

const setReducedMotion = (matches: boolean) => {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: query.includes('prefers-reduced-motion') ? matches : false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(() => false),
      }) as unknown as MediaQueryList,
  )
}

let rafCallbacks: FrameRequestCallback[]
let rafSpy: ReturnType<typeof vi.fn>
let cancelSpy: ReturnType<typeof vi.fn>
let originalWidth: number
let originalHeight: number

beforeEach(() => {
  rafCallbacks = []
  rafSpy = vi.fn((cb: FrameRequestCallback) => {
    rafCallbacks.push(cb)
    return rafCallbacks.length
  })
  cancelSpy = vi.fn()
  vi.stubGlobal('requestAnimationFrame', rafSpy)
  vi.stubGlobal('cancelAnimationFrame', cancelSpy)
  originalWidth = window.innerWidth
  originalHeight = window.innerHeight
})

afterEach(() => {
  // Unmount while the frame stubs are still live: the shared cleanup runs
  // later and would otherwise hit a bare `cancelAnimationFrame` with the
  // globals already gone.
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight })
})

/** Steps the hand-driven frame loop forward; each call is one animation frame. */
const driveFrames = (maxFrames: number, stepMs = 120) => {
  act(() => {
    let now = performance.now()
    for (let i = 0; i < maxFrames; i++) {
      const tick = rafCallbacks[rafCallbacks.length - 1]
      if (!tick) break
      rafCallbacks = []
      now += stepMs
      tick(now)
    }
  })
}

it('a reduced-motion visitor sees no canvas at all and the celebration skips itself', () => {
  setReducedMotion(true)
  vi.useFakeTimers()
  const onDone = vi.fn()
  render(<LevelUpCelebration onDone={onDone} />)
  expect(document.querySelector('canvas')).toBeNull()
  expect(rafSpy).not.toHaveBeenCalled()
  act(() => {
    vi.advanceTimersByTime(400)
  })
  expect(onDone).toHaveBeenCalledTimes(1)
  act(() => {
    vi.advanceTimersByTime(5000)
  })
  expect(onDone).toHaveBeenCalledTimes(1)
})

it('without a drawable canvas it ends immediately instead of looping forever', () => {
  setReducedMotion(false)
  vi.useFakeTimers()
  const onDone = vi.fn()
  render(<LevelUpCelebration onDone={onDone} />)
  expect(document.querySelector('canvas')).not.toBeNull()
  act(() => {
    vi.advanceTimersByTime(0)
  })
  expect(onDone).toHaveBeenCalledTimes(1)
  expect(rafSpy).not.toHaveBeenCalled()
})

it('the burst is portalled to the document body, outside the component tree', () => {
  setReducedMotion(false)
  stubCtx()
  const onDone = vi.fn()
  const { container, unmount } = render(<LevelUpCelebration onDone={onDone} />)
  expect(container.querySelector('canvas')).toBeNull()
  const canvas = document.body.querySelector('canvas')
  expect(canvas).not.toBeNull()
  expect(canvas).toHaveAttribute('aria-hidden', 'true')
  expect(canvas?.className).toContain('pointer-events-none')
  unmount()
  expect(document.body.querySelector('canvas')).toBeNull()
})

it('fires the cannons onto the canvas and settles with a single onDone', () => {
  setReducedMotion(false)
  const ctx = stubCtx()
  const onDone = vi.fn()
  render(<LevelUpCelebration onDone={onDone} />)
  expect(rafSpy).toHaveBeenCalledTimes(1)
  driveFrames(40)
  expect(onDone).toHaveBeenCalledTimes(1)
  expect(ctx.fillRect.mock.calls.length + ctx.arc.mock.calls.length).toBeGreaterThan(0)
  expect(ctx.clearRect).toHaveBeenCalled()
  expect(rafCallbacks).toHaveLength(0)
})

it('canvas drawing picks up the delayed third cannon as frames advance', () => {
  setReducedMotion(false)
  const ctx = stubCtx()
  const onDone = vi.fn()
  render(<LevelUpCelebration onDone={onDone} />)
  driveFrames(1)
  const afterFirstFrame = ctx.fillRect.mock.calls.length + ctx.arc.mock.calls.length
  expect(afterFirstFrame).toBeGreaterThan(0)
  driveFrames(3)
  const afterWarmUp = ctx.fillRect.mock.calls.length + ctx.arc.mock.calls.length
  expect(afterWarmUp).toBeGreaterThan(afterFirstFrame)
})

it('resizes the canvas backing store when the window changes', () => {
  setReducedMotion(false)
  const ctx = stubCtx()
  render(<LevelUpCelebration onDone={vi.fn()} />)
  const canvas = document.body.querySelector('canvas')!
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 600 })
  act(() => {
    window.dispatchEvent(new Event('resize'))
  })
  expect(canvas.width).toBe(800)
  expect(canvas.height).toBe(600)
  expect(canvas.style.width).toBe('800px')
  expect(canvas.style.height).toBe('600px')
  expect(ctx.setTransform).toHaveBeenCalledWith(1, 0, 0, 1, 0, 0)
})

it('unmounting mid-flight cancels the pending frame and releases the window', () => {
  setReducedMotion(false)
  stubCtx()
  const removeSpy = vi.spyOn(window, 'removeEventListener')
  const onDone = vi.fn()
  const { unmount } = render(<LevelUpCelebration onDone={onDone} />)
  driveFrames(1)
  unmount()
  expect(cancelSpy).toHaveBeenCalled()
  expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function))
  expect(onDone).not.toHaveBeenCalled()
  expect(document.body.querySelector('canvas')).toBeNull()
})
