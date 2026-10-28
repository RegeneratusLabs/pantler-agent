/**
 * What the assistant is doing, for the mark in the rail.
 *
 * The chat owns the run state; the rail is outside it. This is the one small piece of shared
 * state between them: `ChatSession` reports the mascot state, the rail and the mobile header
 * read it. It is deliberately not the app's data context — nothing here is fetched, and a
 * navigation that unmounts the chat resets the mark to idle.
 *
 * `done` and `cant` are transient, so the hold lives here rather than in each mark. Two marks on
 * screen then agree about when the grin is over, and a new run cancels the old timer, because a
 * face is a claim about *now*.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import { MASCOT_HOLD_MS, type MascotState } from '../brand/mascot'

interface PresenceValue {
  state: MascotState
  report: (state: MascotState) => void
}

const PresenceContext = createContext<PresenceValue | null>(null)

export function PresenceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MascotState>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  const report = useCallback(
    (next: MascotState) => {
      clearTimer()
      setState(next)
      if (next === 'done' || next === 'cant') {
        timer.current = setTimeout(() => {
          setState('idle')
          timer.current = null
        }, MASCOT_HOLD_MS[next])
      }
    },
    [clearTimer]
  )

  useEffect(() => clearTimer, [clearTimer])

  const value = useMemo(() => ({ state, report }), [state, report])
  return <PresenceContext.Provider value={value}>{children}</PresenceContext.Provider>
}

function usePresence(): PresenceValue {
  const value = useContext(PresenceContext)
  if (!value) throw new Error('useMascotState must be used inside <PresenceProvider>')
  return value
}

/** The face to draw right now. */
export function useMascotState(): MascotState {
  return usePresence().state
}

/**
 * Publish a state from the screen that knows it, and go back to idle when that screen leaves.
 *
 * Two effects on purpose: the first follows state changes, the second is the unmount cleanup.
 * Calling `report('idle')` in the same effect would reset the mark on every change before
 * applying the new state, which React can paint as a flicker.
 */
export function usePresenceReport(state: MascotState): void {
  const { report } = usePresence()
  useEffect(() => {
    report(state)
  }, [report, state])
  useEffect(() => () => report('idle'), [report])
}
