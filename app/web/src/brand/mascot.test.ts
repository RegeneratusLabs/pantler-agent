/**
 * The mapping from a run to a face, without a browser.
 *
 * The behaviour worth pinning is the transient part: a finished run is a grin for a moment, not
 * a property of the conversation. A turn read back from the engine has no `endedAt`, so a
 * reloaded session must idle rather than celebrate. A cancellation is the operator's own act,
 * not a failure.
 */

import { describe, expect, it } from 'vitest'
import { MASCOT_HOLD_MS, mascotStateFor } from './mascot'
import { createRunState } from '../seam/reducer'
import type { Turn } from '../state/useConversation'

const turn = (patch: Partial<Turn> = {}): Turn => ({
  id: 'turn-1',
  input: 'Say hello',
  state: createRunState('run-1'),
  streaming: false,
  ...patch
})

const withPhase = (phase: Turn['state']['phase'], patch: Partial<Turn> = {}): Turn =>
  turn({ state: { ...createRunState('run-1'), phase }, ...patch })

describe('mascotStateFor', () => {
  it('rests with no conversation', () => {
    expect(mascotStateFor([], 0, 1000)).toBe('idle')
  })

  it('works while a run is live, whether it is thinking or using a tool', () => {
    expect(mascotStateFor([turn({ streaming: true })], 0, 1000)).toBe('working')
  })

  it('listens when an approval is parked, even while the run streams', () => {
    expect(mascotStateFor([turn({ streaming: true })], 1, 1000)).toBe('listening')
  })

  it('grins for a moment after a completed run, then rests', () => {
    const done = withPhase('completed', { endedAt: 10_000 })
    expect(mascotStateFor([done], 0, 10_000)).toBe('done')
    expect(mascotStateFor([done], 0, 10_000 + MASCOT_HOLD_MS.done)).toBe('done')
    expect(mascotStateFor([done], 0, 10_001 + MASCOT_HOLD_MS.done)).toBe('idle')
  })

  it('frowns for a moment after a failed run, then rests', () => {
    const failed = withPhase('failed', { endedAt: 10_000 })
    expect(mascotStateFor([failed], 0, 10_000)).toBe('cant')
    expect(mascotStateFor([failed], 0, 10_001 + MASCOT_HOLD_MS.cant)).toBe('idle')
  })

  it('does not frown at an operator stop', () => {
    expect(mascotStateFor([withPhase('cancelled', { endedAt: 10_000 })], 0, 10_000)).toBe('idle')
    expect(mascotStateFor([withPhase('interrupted', { endedAt: 10_000 })], 0, 10_000)).toBe('idle')
  })

  it('idles for a turn read back from the transcript', () => {
    // No `endedAt`: the run ended before this page existed, so there is no moment to celebrate.
    expect(mascotStateFor([withPhase('completed')], 0, 10_000)).toBe('idle')
    expect(mascotStateFor([withPhase('failed')], 0, 10_000)).toBe('idle')
  })

  it('uses the newest turn for a finished face and any live turn for work', () => {
    const older = withPhase('failed', { id: 'turn-old', endedAt: 10_000 })
    const newest = withPhase('completed', { id: 'turn-new', endedAt: 10_000 })
    expect(mascotStateFor([older, newest], 0, 10_000)).toBe('done')
    expect(mascotStateFor([older, turn({ streaming: true })], 0, 10_000)).toBe('working')
  })

  it('treats a clock that has not arrived as rest, not as a celebration', () => {
    expect(mascotStateFor([withPhase('completed', { endedAt: 10_000 })], 0, 9_000)).toBe('idle')
  })
})
