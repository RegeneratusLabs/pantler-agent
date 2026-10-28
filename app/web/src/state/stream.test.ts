/**
 * The resumable run stream (the internal audit WEB-4).
 *
 * The property worth having is "a dropped connection continues from the last sequence it saw",
 * and it used to be unreachable: the hook called `streamRun` once per turn with the `lastSeq` of
 * a state it had just created, so `Last-Event-ID` was never sent. These tests drive the loop with
 * a fake client whose connections can drop on demand, which is a thing no rendered component can
 * ask for.
 */

import { describe, expect, it } from 'vitest'
import type { RunEvent, SseFrame } from '@shared/wire'
import type { SeamClient } from '../seam/client'
import { createRunState, settleApprovals, type RunState } from '../seam/reducer'
import { STREAM_BACKOFF_MS, STREAM_ATTEMPTS, streamRunWithResume } from './stream'

/**
 * A client whose every connection is scripted: frames to yield, or an error to throw.
 *
 * Sequence ids run 1, 2, 3… across the whole run, as the engine's do — which is what makes the
 * resume assertion readable: the second connection must ask for the last id the first one saw.
 */
function fakeClient(script: Array<RunEvent[] | Error>) {
  const calls: Array<{ runId: string; lastSeq?: number | null }> = []
  let connection = 0
  let sequence = 0

  const client = {
    // eslint-disable-next-line require-yield
    async *streamRun(runId: string, options: { lastSeq?: number | null } = {}) {
      calls.push({ runId, lastSeq: options.lastSeq })
      const step = script[Math.min(connection, script.length - 1)]
      connection += 1
      if (step instanceof Error) throw step
      for (const event of step) {
        sequence += 1
        yield { id: sequence, data: event } as SseFrame
      }
    }
  } as unknown as SeamClient

  return { client, calls }
}
const started: RunEvent = { event: 'run.started', run_id: 'run-1', timestamp: 0 } as RunEvent
const delta = (text: string): RunEvent =>
  ({ event: 'message.delta', run_id: 'run-1', timestamp: 0, delta: text }) as RunEvent
const completed: RunEvent = {
  event: 'run.completed',
  run_id: 'run-1',
  timestamp: 0,
  output: 'done'
} as RunEvent

const noSleep = async () => {}

async function drain(
  script: Array<RunEvent[] | Error>,
  signal = new AbortController().signal,
  attempts?: number
) {
  const { client, calls } = fakeClient(script)
  let state: RunState = createRunState('run-1')
  const seen: RunState[] = []
  const result = await streamRunWithResume(client, 'run-1', state, signal, {
    onState: next => {
      state = next
      seen.push(next)
    },
    sleep: noSleep,
    attempts
  })
  return { result, calls, seen }
}

describe('streamRunWithResume', () => {
  it('reads a stream to its terminal frame in one connection', async () => {
    const { result, calls } = await drain([[started, delta('hi'), completed]])
    expect(calls).toHaveLength(1)
    expect(result.terminal).toBe(true)
    expect(result.state.phase).toBe('completed')
    expect(result.state.text).toBe('hi')
  })

  it('reconnects from the last sequence it saw', async () => {
    // The first connection drops after two frames; the second must not start from the top.
    const { result, calls } = await drain([
      [started, delta('one')],
      [delta(' two'), completed]
    ])
    expect(calls).toHaveLength(2)
    expect(calls[0].lastSeq).toBeNull()
    expect(calls[1].lastSeq).toBe(2) // the id the fake client gave the second delta
    expect(result.terminal).toBe(true)
    expect(result.state.text).toBe('one two')
  })

  it('retries a stream that ends without a terminal frame', async () => {
    const { result, calls } = await drain([[started], [completed]])
    expect(calls).toHaveLength(2)
    expect(result.terminal).toBe(true)
  })

  it('gives up after the attempts and reports that it did', async () => {
    const { result, calls } = await drain([[started], [delta('x')], [delta('y')]], undefined, 3)
    expect(calls).toHaveLength(STREAM_ATTEMPTS)
    expect(result.terminal).toBe(false)
  })

  it('throws the last failure, so the caller can report it', async () => {
    const last = new Error('the engine went away')
    await expect(drain([[started], last], undefined, 2)).rejects.toThrow('the engine went away')
  })

  it('does not retry an abort: the operator asked for it', async () => {
    const controller = new AbortController()
    const { client, calls } = fakeClient([[]])
    const promise = streamRunWithResume(client, 'run-1', createRunState('run-1'), controller.signal, {
      onState: () => {},
      sleep: noSleep
    })
    controller.abort()
    const result = await promise
    expect(calls).toHaveLength(1)
    expect(result.terminal).toBe(false)
  })

  it('waits longer between each attempt', async () => {
    const waits: number[] = []
    const { client } = fakeClient([[], [], [completed]])
    await streamRunWithResume(client, 'run-1', createRunState('run-1'), new AbortController().signal, {
      onState: () => {},
      sleep: async ms => {
        waits.push(ms)
      }
    })
    expect(waits).toEqual([STREAM_BACKOFF_MS, STREAM_BACKOFF_MS * 2])
  })
})

describe('settleApprovals', () => {
  const approval = {
    key: 'a1',
    requestId: 'r1',
    description: 'send the newsletter',
    choices: [],
    command: '',
    patternKey: '',
    smartDenied: false,
    allowSession: false,
    allowPermanent: false,
    at: 0
  }

  it('expires an approval the run moved past without an answer', () => {
    const state: RunState = { ...createRunState('run-1'), approvals: [approval] as never }
    const settled = settleApprovals(state)
    expect(settled.approvals[0].expired).toBe(true)
  })

  it('leaves an answered approval alone', () => {
    const answered = { ...approval, resolution: { choice: 'once', at: 1 } }
    const state: RunState = { ...createRunState('run-1'), approvals: [answered] as never }
    expect(settleApprovals(state)).toBe(state)
  })
})
