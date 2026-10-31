/**
 * The mascot's state machine, with no React in it.
 *
 * `brand/FOR-THE-AGENT.md` §2 names five states and says what each one means. This module maps
 * the app's own run state onto them; it deliberately knows nothing about the drawing.
 *
 * The transient states are the interesting part. A face that celebrated every historical turn
 * would turn a reloaded conversation into a standing ovation, so `done` and `can't` only exist
 * while the turn that just ended is fresh, and a turn read back from the engine has no
 * `endedAt` at all. A cancellation is the operator's decision, not a failure, so it idles.
 */

import type { Turn } from '../state/useConversation'

export type MascotState = 'idle' | 'listening' | 'working' | 'done' | 'cant'

/** What a screen reader hears on the mark's button. The visible face carries the state too. */
export const MASCOT_LABEL: Record<MascotState, string> = {
  idle: 'idle',
  listening: 'listening',
  working: 'working',
  done: 'done',
  cant: 'couldn’t finish'
}

/** How long a finished face stays before going back to rest, in milliseconds. */
export const MASCOT_HOLD_MS: Record<'done' | 'cant', number> = {
  done: 2000,
  cant: 2400
}

/**
 * The state to draw right now.
 *
 * `waitingCount` is the number of approvals parked on the operator, newest last, from
 * `useConversation().waiting`. It outranks a running turn: the assistant is not working, it is
 * waiting to be allowed to.
 *
 * A run that is still streaming is working, whether it is thinking or calling a tool — the brand
 * has one face for both, and the turn's own text says which. Only the newest turn can contribute
 * a transient face; the loop that finds a live turn is separate because at most one run streams
 * per session, but a stale array should not be able to hide it.
 */
export function mascotStateFor(
  turns: readonly Turn[],
  waitingCount: number,
  now: number = Date.now()
): MascotState {
  if (waitingCount > 0) return 'listening'

  let live = false
  for (const turn of turns) if (turn.streaming) live = true
  if (live) return 'working'

  const newest = turns[turns.length - 1]
  if (!newest?.endedAt) return 'idle'

  const age = now - newest.endedAt
  if (age < 0) return 'idle'
  if (newest.state.phase === 'completed' && age <= MASCOT_HOLD_MS.done) return 'done'
  if (newest.state.phase === 'failed' && age <= MASCOT_HOLD_MS.cant) return 'cant'
  return 'idle'
}
