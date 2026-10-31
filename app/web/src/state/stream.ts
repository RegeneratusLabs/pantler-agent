/**
 * Reading a run's stream to its end, once — or a few times, if it drops.
 *
 * `SeamClient.streamRun` takes a `lastSeq` and sends it as `Last-Event-ID`, so the engine can
 * resume from where the client got to. That machinery was unreachable: the hook called
 * `streamRun` exactly once per turn, always with the `lastSeq` of a state it had just created
 * (`null`), so a dropped connection lost the rest of the turn — and because the hook then
 * marked the turn failed, the stop button went with it and the run could not even be stopped
 * (the internal audit WEB-4).
 *
 * This is that loop. It is a plain async function rather than part of the hook for one reason:
 * the property worth having is "it reconnects from the last sequence it saw", and that is
 * testable without a DOM, a fake timer or a rendered component. The `sleep` is injected for
 * the same reason — a test of the backoff should not spend the backoff.
 */

import type { SeamClient } from '../seam/client'
import { applyFrame, isTerminal, type RunState } from '../seam/reducer'

/** How many times a dropped stream is reconnected before the turn is called failed. */
export const STREAM_ATTEMPTS = 3

/** How long to wait before the first reconnect; doubled for each attempt after it. */
export const STREAM_BACKOFF_MS = 500

export interface StreamOptions {
  /** Called with the state after every frame, for the caller to render. */
  onState: (state: RunState) => void
  /** How many connections to make in total (including the first). */
  attempts?: number
  /** Waits between attempts. */
  sleep?: (ms: number) => Promise<void>
}

const defaultSleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))

/**
 * Stream one run to its terminal frame, resuming after a drop.
 *
 * Returns the state it ended with, and whether the run actually reached a terminal phase —
 * `false` means the attempts ran out, and the caller has to decide what to say about a turn
 * that is still running on the engine.
 *
 * An abort is not a failure and is never retried: the operator asked for it.
 */
export async function streamRunWithResume(
  client: SeamClient,
  runId: string,
  state: RunState,
  signal: AbortSignal,
  options: StreamOptions
): Promise<{ state: RunState; terminal: boolean }> {
  const attempts = Math.max(1, options.attempts ?? STREAM_ATTEMPTS)
  const sleep = options.sleep ?? defaultSleep
  let current = state

  for (let attempt = 0; attempt < attempts; attempt++) {
    if (attempt > 0) await sleep(STREAM_BACKOFF_MS * 2 ** (attempt - 1))
    if (signal.aborted) return { state: current, terminal: false }

    try {
      for await (const frame of client.streamRun(runId, {
        lastSeq: current.lastSeq,
        signal
      })) {
        current = applyFrame(current, frame)
        options.onState(current)
        if (isTerminal(current.phase)) return { state: current, terminal: true }
      }
      // The stream ended without a terminal frame: the engine closed it, which for a run that
      // is still going is a drop rather than an end.
      if (isTerminal(current.phase)) return { state: current, terminal: true }
    } catch (error) {
      if (signal.aborted) return { state: current, terminal: false }
      // The last attempt's failure is the caller's to report.
      if (attempt === attempts - 1) throw error
    }
  }

  return { state: current, terminal: false }
}
