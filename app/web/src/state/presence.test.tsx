// @vitest-environment jsdom
/**
 * The one piece of shared state between the chat and the rail.
 *
 * The interesting behaviour is time: a grin is not a status, it is a moment. The provider owns
 * the clock so two marks on screen cannot disagree about when it ended, and a new state cancels
 * the old hold rather than letting a stale timer put the face back to rest mid-run.
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MascotState } from '../brand/mascot'
import { PresenceProvider, useMascotState, usePresenceReport } from './presence'

function Probe({ next }: { next: MascotState }) {
  usePresenceReport(next)
  return null
}

function Face() {
  return <span data-testid="face">{useMascotState()}</span>
}

function view(next: MascotState | null) {
  return (
    <PresenceProvider>
      {next ? <Probe next={next} /> : null}
      <Face />
    </PresenceProvider>
  )
}

const face = () => screen.getByTestId('face').textContent

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('PresenceProvider', () => {
  it('shows a finished face for its hold, then rests', () => {
    render(view('done'))
    expect(face()).toBe('done')

    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(face()).toBe('done')

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(face()).toBe('idle')
  })

  it('holds a failure a little longer', () => {
    render(view('cant'))
    act(() => {
      vi.advanceTimersByTime(2399)
    })
    expect(face()).toBe('cant')
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(face()).toBe('idle')
  })

  it('lets a new run cancel the old hold', () => {
    const { rerender } = render(view('done'))
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    rerender(view('working'))
    expect(face()).toBe('working')

    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(face()).toBe('working')
  })

  it('returns to rest when the screen that reported it leaves', () => {
    const { rerender } = render(view('working'))
    expect(face()).toBe('working')

    rerender(view(null))
    expect(face()).toBe('idle')
  })
})
