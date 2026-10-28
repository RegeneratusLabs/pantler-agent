// @vitest-environment jsdom
/**
 * The streaming hook, with a stubbed seam.
 *
 * This is the file WEB-16 said could not exist: `environment: 'node'` and `include: [….test.ts]`
 * meant no DOM and no `.tsx` tests, so the four behaviours the audit's WEB-1…WEB-4 findings were
 * about — a run that outlives its screen, a dropped stream, an approval nobody answers, a
 * decision that does not land — were only ever checked by hand. `renderHook` runs the effects
 * that `renderToStaticMarkup` cannot.
 *
 * The stub is deliberately dumb: it yields the frames a scenario needs and nothing else. What is
 * asserted is what the hook does with them.
 */

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunEvent, SessionMessage } from '@shared/wire'
import { createRunState } from '../seam/reducer'
import { keepTurnIdentity, useConversation, type Turn } from './useConversation'
import type { SeamClient } from '../seam/client'
import type { BffClient } from '../seam/bff'

afterEach(cleanup)

const frame = (event: RunEvent): { id: number; data: RunEvent } => ({ id: 0, data: event })

const event = (kind: string, fields: Record<string, unknown> = {}): RunEvent =>
  ({ event: kind, run_id: 'run-1', timestamp: 0, ...fields }) as RunEvent

interface Stub {
  client: SeamClient
  bff: BffClient
  /** Resolves once the stream has started, so a test can act on a run that is genuinely live. */
  started: Promise<void>
  /** Deliver one more frame on a held-open stream — a delta arriving after a poll, say. */
  emit: (event: RunEvent) => void
  aborted: () => boolean
  stopCalls: () => number
}

/**
 * A client whose stream yields `frames` and then ends, or throws `failure` first.
 *
 * `hold` keeps the stream open until `stopRun` is called — the state a turn is in while the
 * operator is looking at it. Frames are yielded on the *first* attempt only: a real reconnect
 * resumes from the last sequence it saw, and a stub that replayed them would append the same
 * text three times through `streamRunWithResume`'s retries.
 *
 * `emit` is for the one scenario a fixed list cannot express: a frame that arrives *after* a
 * poll has merged something, which is the order that used to drop it.
 */
function stub(frames: RunEvent[], failure?: Error, hold = false): Stub {
  let release: () => void = () => undefined
  let stopped = false
  const gate = new Promise<void>(resolve => {
    release = () => {
      stopped = true
      resolve()
    }
  })
  let markStarted: () => void = () => undefined
  const started = new Promise<void>(resolve => {
    markStarted = resolve
  })
  const queued: RunEvent[] = []
  let wake: (() => void) | null = null
  const emit = (event: RunEvent) => {
    queued.push(event)
    wake?.()
    wake = null
  }
  let signal: AbortSignal | undefined
  let stops = 0
  let attempts = 0

  const client = {
    startRun: vi.fn(async () => ({ run_id: 'run-1', status: 'running', replayed: false })),
    sessionMessages: vi.fn(async () => ({ object: 'list', session_id: 'web-1', data: [] })),
    stopRun: vi.fn(async () => {
      stops += 1
      release()
      return { status: 'cancelled' }
    }),
    respondToApproval: vi.fn(async () => ({ ok: true })),
    respondToClarify: vi.fn(async () => ({
      run_id: 'run-1',
      status: 'resolved',
      prompt_id: 'prompt-1'
    })),
    async *streamRun(_runId: string, options: { signal?: AbortSignal } = {}) {
      signal = options.signal
      attempts += 1
      if (attempts === 1) {
        for (const event of frames) {
          if (options.signal?.aborted) return
          yield frame(event)
        }
      }
      markStarted()
      if (failure) throw failure
      while (hold && !stopped) {
        while (queued.length > 0) yield frame(queued.shift() as RunEvent)
        if (stopped) return
        const woken = new Promise<void>(resolve => {
          wake = resolve
        })
        await Promise.race([gate, woken])
      }
    }
  } as unknown as SeamClient

  const bff = { composeTurn: vi.fn(async () => ({ input: 'hi' })) } as unknown as BffClient
  return {
    client,
    bff,
    started,
    emit,
    aborted: () => Boolean(signal?.aborted),
    stopCalls: () => stops
  }
}

describe('useConversation', () => {
  it('sends a turn and shows it streaming', async () => {
    const { client, bff } = stub([event('run.completed', { output: 'done' })])
    const { result } = renderHook(() => useConversation(client, bff, 'web-1'))

    await act(async () => {
      await result.current.submit('hello')
    })

    expect(client.startRun).toHaveBeenCalledOnce()
    expect(result.current.turns).toHaveLength(1)
    expect(result.current.turns[0].input).toBe('hello')
    expect(result.current.turns[0].streaming).toBe(false)
  })

  it('empties `waiting` when a run is stopped with an approval still open', async () => {
    // The audit's WEB-2: the engine never answers an approval after the client aborts, so the
    // composer stayed disabled for the rest of the session ("Answer the approval above first").
    const { client, bff, started } = stub(
      [
        event('approval.request', {
          request_id: 'req-1',
          description: 'Run the command',
          choices: ['once', 'deny']
        })
      ],
      undefined,
      true
    )
    const { result } = renderHook(() => useConversation(client, bff, 'web-1'))

    let submitted: Promise<void> | undefined
    await act(async () => {
      submitted = result.current.submit('do it')
      // The stream is held open after its frames, so `started` means "the approval is in state".
      await started
    })
    expect(result.current.waiting).toHaveLength(1)

    await act(async () => {
      await result.current.stop(result.current.turns[0].id)
      await submitted
    })

    expect(result.current.waiting).toHaveLength(0)
    expect(result.current.turns[0].streaming).toBe(false)
    // The approval is expired rather than answered: nothing said yes.
    expect(result.current.turns[0].state.approvals[0].expired).toBe(true)
  })

  it('surfaces a clarifying question, answers it through the client, and settles it on stop', async () => {
    const { client, bff, started } = stub(
      [
        event('clarify.request', {
          prompt_id: 'prompt-1',
          execution_generation: 2,
          question: 'Which do you want?',
          choices: ['Apples', 'Pears']
        })
      ],
      undefined,
      true
    )
    const { result } = renderHook(() => useConversation(client, bff, 'web-1'))

    let submitted: Promise<void> | undefined
    await act(async () => {
      submitted = result.current.submit('ask me')
      await started
    })

    expect(result.current.questions).toHaveLength(1)
    expect(result.current.questions[0].prompt.question).toBe('Which do you want?')

    let delivered = false
    await act(async () => {
      delivered = await result.current.answerClarify(
        result.current.turns[0].id,
        'Pears',
        'prompt-1',
        2
      )
    })
    expect(delivered).toBe(true)
    expect(client.respondToClarify).toHaveBeenCalledWith('run-1', 'Pears', 'prompt-1', 2)

    await act(async () => {
      await result.current.stop(result.current.turns[0].id)
      await submitted
    })

    expect(result.current.questions).toHaveLength(0)
    expect(result.current.turns[0].state.clarifies[0].expired).toBe(true)
  })

  it('reports a stream that throws, and asks for a refetch', async () => {
    const { client, bff, started } = stub(
      [event('message.delta', { delta: 'half' })],
      new Error('socket died')
    )
    const { result } = renderHook(() => useConversation(client, bff, 'web-1'))

    await act(async () => {
      const submitted = result.current.submit('hello')
      await started
      await submitted
    })

    const turn = result.current.turns[0]
    expect(turn.streaming).toBe(false)
    expect(turn.needsRefetch).toBe(true)
    expect(turn.error).toBeTruthy()
    // What did arrive is kept: half a reply is better than none, and the refetch will settle it.
    expect(turn.state.text).toBe('half')
  })

  it('aborts every run when the screen goes away', async () => {
    // The audit's WEB-1: `ChatPage` remounts the hook per session, so a run whose screen was
    // replaced kept streaming into a component that was gone.
    const { client, bff, aborted, started } = stub(
      [event('message.delta', { delta: 'x' })],
      undefined,
      true
    )
    const { result, unmount } = renderHook(() => useConversation(client, bff, 'web-1'))

    await act(async () => {
      void result.current.submit('hello')
      await started
    })
    expect(result.current.turns).toHaveLength(1)
    expect(aborted()).toBe(false)

    unmount()
    expect(aborted()).toBe(true)
  })

  it('keeps a thought the poll merged when the next stream frame arrives', async () => {
    // The engine's run stream carries no thinking at all (the front-end design §2), so a
    // thought is the poll's. Replacing the turn's state with the stream's snapshot dropped it on
    // every frame: the body appeared on a poll, vanished on the next delta and came back two
    // seconds later — the expansion and contraction a live turn used to be, and the reason the
    // screen seemed to argue with itself while thinking.
    vi.useFakeTimers()
    try {
      const { client, bff, started, emit } = stub(
        [event('message.delta', { delta: 'working' })],
        undefined,
        true
      )
      vi.mocked(client.sessionMessages).mockResolvedValue({
        object: 'list',
        session_id: 'web-1',
        data: [
          { id: 1, session_id: 'web-1', role: 'user', content: 'hello' },
          { id: 2, session_id: 'web-1', role: 'assistant', content: '', reasoning: 'Weigh it up.' },
          { id: 3, session_id: 'web-1', role: 'tool', content: '{}', tool_name: 'web_search' }
        ] as SessionMessage[]
      })

      const { result } = renderHook(() => useConversation(client, bff, 'web-1'))
      await act(async () => {
        void result.current.submit('hello')
        await started
        // The poll's first read is one interval in (`THOUGHT_POLL_MS`, in the hook).
        await vi.advanceTimersByTimeAsync(2_100)
      })

      expect(result.current.turns[0].state.thoughts.map(thought => thought.text)).toEqual([
        'Weigh it up.'
      ])

      await act(async () => {
        emit(event('message.delta', { delta: ' more' }))
        await vi.advanceTimersByTimeAsync(50)
      })

      // Still there, still the live one, with the frame's own text beside it.
      expect(result.current.turns[0].state.thoughts.map(thought => thought.text)).toEqual([
        'Weigh it up.'
      ])
      expect(result.current.turns[0].state.thoughts[0].status).toBe('streaming')
      expect(result.current.turns[0].state.text).toBe('working more')
    } finally {
      vi.useRealTimers()
    }
  })

  it('marks a turn for refetch when the engine says our state is truncated', async () => {
    const { client, bff } = stub([
      event('message.delta', { delta: 'x' }),
      event('replay.truncated', { oldest_retained_seq: 5, requested_seq: 1 }),
      event('run.completed', { output: 'x' })
    ])
    const { result } = renderHook(() => useConversation(client, bff, 'web-1'))

    await act(async () => {
      await result.current.submit('hello')
    })

    expect(result.current.turns[0].needsRefetch).toBe(true)
  })
})

/** A turn as the screen addresses it: an id, the operator's words, and a state. */
const turn = (id: string, input: string): Turn => ({
  id,
  input,
  state: createRunState('run-1'),
  streaming: false
})

describe('keepTurnIdentity', () => {
  it('gives the persisted reading of a turn the identity already on screen', () => {
    // `TurnView` is keyed on the id, so this is what stops a refetch from remounting the turn and
    // closing a thought's body that had been shown (`useConversation.hydrate`).
    const shown = [turn('turn-1', 'hello'), turn('turn-2', 'and again')]
    const fresh = [turn('hist-9', 'hello'), turn('hist-10', 'and again')]

    expect(keepTurnIdentity(fresh, shown).map(t => t.id)).toEqual(['turn-1', 'turn-2'])
  })

  it('carries the moment the live turn ended across a refetch', () => {
    // The transcript has no `endedAt` by design; the live turn's moment has to survive the
    // refetch that lands within a second of the run ending, or the grin is never seen.
    const shown = [{ ...turn('turn-1', 'hello'), endedAt: 1234 }]
    const fresh = [turn('hist-1', 'hello')]

    expect(keepTurnIdentity(fresh, shown)[0]?.endedAt).toBe(1234)
  })

  it('pairs two turns that say the same thing in the order they happened', () => {
    const shown = [turn('turn-1', 'hi'), turn('turn-2', 'hi')]
    const fresh = [turn('hist-1', 'hi'), turn('hist-2', 'hi')]

    expect(keepTurnIdentity(fresh, shown).map(t => t.id)).toEqual(['turn-1', 'turn-2'])
  })

  it('adopts nothing past the first turn that disagrees', () => {
    // Pagination or a fork: the two readings have diverged, and guessing which turn is which
    // would put one turn's state under another's address. A remount is the honest failure.
    const shown = [turn('turn-1', 'hello'), turn('turn-2', 'second')]
    const fresh = [turn('hist-8', 'older'), turn('hist-9', 'hello')]

    expect(keepTurnIdentity(fresh, shown).map(t => t.id)).toEqual(['hist-8', 'hist-9'])
  })

  it('leaves a first reading alone', () => {
    expect(keepTurnIdentity([turn('hist-1', 'hi')], []).map(t => t.id)).toEqual(['hist-1'])
  })
})
