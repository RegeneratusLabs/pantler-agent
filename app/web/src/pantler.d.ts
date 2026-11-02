/**
 * The desktop host's bridge, present only in the packaged app.
 *
 * The browser build has no preload, so every caller must treat `window.pantler` as optional:
 * `restartEngine` is how Settings applies a newly written `.env`, and its absence is why the
 * form falls back to "restart the engine to apply"; `updates` is the host's updater, and its
 * absence is why About says updates are not available in this build.
 */

export type UpdateStatus =
  | 'disabled'
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'downloaded'
  | 'error'

export interface UpdateState {
  status: UpdateStatus
  /** The version this app is running. */
  currentVersion: string
  /** The version that was offered, once there is one. */
  version: string | null
  percent: number | null
  error: string | null
  /** When the last check finished, so "idle" can mean "up to date" rather than "not asked". */
  checkedAt: number | null
}

export interface UpdateResult {
  ok: boolean
  error?: string
}

export interface PantlerUpdates {
  state: () => Promise<UpdateState>
  check: () => Promise<UpdateState>
  install: () => Promise<UpdateResult>
  subscribe: (listener: (state: UpdateState) => void) => () => void
}

declare global {
  interface Window {
    pantler?: {
      platform?: string
      versions?: {
        electron?: string
        chrome?: string
        node?: string
      }
      /** Restart the engine child; resolves once it answers again. */
      restartEngine?: () => Promise<{ ok: boolean; error?: string }>
      updates?: PantlerUpdates
    }
  }
}
