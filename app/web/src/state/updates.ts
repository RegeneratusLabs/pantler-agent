/**
 * The updater's state, as the page sees it.
 *
 * The host owns the updater and broadcasts its state; this is a thin subscription over
 * `window.pantler.updates`. In the browser build there is no bridge, so the hook reports
 * `disabled` and About says updates are not available there.
 */

import { useCallback, useEffect, useState } from 'react'
import type { UpdateResult, UpdateState } from '../pantler'

const DISABLED: UpdateState = {
  status: 'disabled',
  currentVersion: __PANTLER_VERSION__,
  version: null,
  percent: null,
  error: null,
  checkedAt: null
}

export interface UpdateController {
  /** False in the browser build, or when the host did not expose a bridge. */
  supported: boolean
  state: UpdateState
  /** A check or an install is being asked for right now. */
  busy: boolean
  check: () => Promise<void>
  install: () => Promise<UpdateResult>
}

export function useUpdateState(): UpdateController {
  // Captured once: re-reading `window.pantler.updates` could hand back a new proxy each render
  // and resubscribe the effect on every state update.
  const [bridge] = useState(() =>
    typeof window === 'undefined' ? undefined : window.pantler?.updates
  )
  const [state, setState] = useState<UpdateState>(() =>
    bridge ? { ...DISABLED, status: 'idle' } : DISABLED
  )
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!bridge) return
    let alive = true

    void bridge
      .state()
      .then(next => {
        if (alive) setState(next)
      })
      .catch(() => {
        // The host answers `disabled` rather than throwing; a rejection here is the bridge
        // disappearing, which the initial state already covers.
      })

    const off = bridge.subscribe(next => {
      if (alive) setState(next)
    })

    return () => {
      alive = false
      off()
    }
  }, [bridge])

  const check = useCallback(async () => {
    if (!bridge) return
    setBusy(true)
    try {
      setState(await bridge.check())
    } catch {
      // A failed check is reported by the host's state; do not invent a second error path.
    } finally {
      setBusy(false)
    }
  }, [bridge])

  const install = useCallback(async (): Promise<UpdateResult> => {
    if (!bridge) return { ok: false, error: 'Updates are not available in this build.' }
    setBusy(true)
    try {
      return await bridge.install()
    } finally {
      setBusy(false)
    }
  }, [bridge])

  return { supported: Boolean(bridge), state, busy, check, install }
}
