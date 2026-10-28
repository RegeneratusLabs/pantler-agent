/**
 * Ties the seam client to the reducer and gives the screens one thing to render.
 *
 * The session id comes from the route, not from this hook. `/chat` is a redirect into a
 * freshly minted `/chat/<id>`, so a conversation always has a stable name before its first
 * run — which is what makes "New session", the rail, and a page reload all agree.
 *
 * The only other interesting decision: a turn's state lives in React state, but the run
 * stream is a long-lived subscription that outlives any single render. Updates therefore
 * always go through a functional setState keyed by turn id, so a delta that arrives
 * between renders cannot be applied to a stale copy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ApprovalChoice, SessionMessage } from '@shared/wire'
import { parseTurn, type AttachmentRef } from '@shared/attachments'
import { currentVoiceInstructions } from '../onboarding/profile'
import { BffClient } from '../seam/bff'
import { SeamClient, SeamError, SeamUnreachable } from '../seam/client'
import { createRunState, settleApprovals, settleClarifies, waitingApprovals, waitingClarifies, type RunState } from '../seam/reducer'
import { streamRunWithResume } from './stream'
import { settleThoughts, turnsFromMessages, withThoughts, withToolArguments } from './transcript'

export interface Turn {
  id: string
  /** What the operator typed. With attachments, the listing lives in `context`. */
  input: string
  /** What the turn carried, whether it was just composed or parsed back out of history. */
  attachments?: AttachmentRef[]
  /** The listing's tail — the hint and any inlined file contents. */
  context?: string
  runId?: string
  state: RunState
  error?: string
  streaming: boolean
  /**
   * When this turn stopped running, for the mascot's short-lived done/can't faces.
   *
   * UI-only and deliberately absent on turns read back from the transcript: a conversation
   * reopened tomorrow must not celebrate a run that ended then. It is set by the two places a
   * live turn ends — the terminal stream patch and `endTurn`.
   */
  endedAt?: number
  /** Set when the engine told us our state is incomplete (replay.truncated). */
  needsRefetch?: boolean
}

/** A fresh, engine-safe session name. The engine accepts `api_…`, `web-…`, anything sane. */
export function makeSessionId(): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(16).slice(2, 14)
  return `web-${random}`
}

/**
 * How often a running turn re-reads the transcript for thinking.
 *
 * Modest on purpose. This is a poll against a local engine, thinking lands a step at a time
 * rather than a character at a time, and the work it describes takes seconds. Two seconds is
 * quick enough to read a thought while the call it produced is still running, and slow enough
 * that a long turn does not become a request loop.
 */
const THOUGHT_POLL_MS = 2000

/**
 * Read the durable transcript on a timer, handing every answer to `onRead`.
 *
 * The run stream is the authority for everything the operator watches live; thinking is the one
 * thing it does not carry at all (the front-end design §2), so a running turn has to ask the
 * transcript for it. Two properties matter and both are here rather than in the caller: a read
 * still in flight is never overtaken by the next tick, and a read that fails changes nothing —
 * the turn is already on screen without the thought, so there is nothing to report.
 *
 * @returns the disposer that stops the timer.
 */
function pollThoughts(
  client: SeamClient,
  sessionId: string,
  signal: AbortSignal,
  onRead: (messages: readonly SessionMessage[]) => void
): () => void {
  let reading = false

  const read = async () => {
    if (reading || signal.aborted) return
    reading = true
    try {
      const recorded = await client.sessionMessages(sessionId, signal)
      if (!signal.aborted) onRead(recorded.data ?? [])
    } catch {
      // Nothing to say: the live turn renders exactly as it did without the thought.
    } finally {
      reading = false
    }
  }

  const timer = setInterval(() => void read(), THOUGHT_POLL_MS)
  return () => clearInterval(timer)
}

/**
 * Give the turns read back from the transcript the identity of the turns already on screen.
 *
 * A live turn is minted with an id of its own (`turn-…`); the same turn read from the persisted
 * transcript is addressed by its message ids (`hist-…`). The rows are the same rows, and only
 * their address changed — but `TurnView` is keyed on that address, so every turn that changed it
 * was unmounted and rebuilt. Everything a turn had latched went with it: a thought's body that
 * had been shown closed, a tool run the operator had opened folded back up, and the whole turn
 * re-entered as though it had just arrived. This is the second half of "a live turn must not
 * contract"; the first half is the stream callback in `submit` below, where every frame was
 * dropping the thoughts the poll had merged.
 *
 * Matching is by the operator's own words, walked from the end of both lists, and it stops at the
 * first turn that does not agree: the newest turns are the ones a refetch is about, and an
 * earlier mismatch means the two readings have diverged in a way that guessing would make worse
 * (pagination, a fork). Two turns with the same words are still paired in order, so a session
 * where the same sentence was sent twice keeps both identities where they belong.
 *
 * It also carries the moment the live turn ended. The transcript reading has no `endedAt` — a
 * reloaded conversation must not celebrate yesterday's work — but the refetch that follows a run
 * lands within a second of that run ending, and without this the mascot would lose the grin
 * before the operator saw it. The live turn's value wins; the fresh reading has none.
 */
export function keepTurnIdentity(fresh: Turn[], shown: readonly Turn[]): Turn[] {
  const kept = [...fresh]
  let f = kept.length - 1
  let s = shown.length - 1

  while (f >= 0 && s >= 0 && kept[f].input === shown[s].input) {
    kept[f] = {
      ...kept[f],
      id: shown[s].id,
      endedAt: kept[f].endedAt ?? shown[s].endedAt
    }
    f -= 1
    s -= 1
  }

  return kept
}

export function useConversation(
  client: SeamClient | null,
  bff: BffClient | null,
  sessionId: string
) {
  const [turns, setTurns] = useState<Turn[]>([])
  const controllers = useRef(new Map<string, AbortController>())

  /**
   * Leaving a conversation ends its runs.
   *
   * `ChatPage` renders `<ChatSession key={sessionId}>`, so switching sessions — or navigating
   * away — unmounts this hook while its `for await` loop, its two-second poll and every later
   * `patchTurn` keep running against a component that is gone. The stream stayed open for the
   * life of the page, the poll never stopped, and the turn's stop button went with the
   * component, so the run could not even be cancelled from the UI
   * (the internal audit WEB-1).
   */
  useEffect(() => {
    const live = controllers.current
    return () => {
      for (const controller of live.values()) controller.abort()
      live.clear()
    }
  }, [])

  const patchTurn = useCallback((id: string, patch: Partial<Turn>) => {
    setTurns(previous => previous.map(turn => (turn.id === id ? { ...turn, ...patch } : turn)))
  }, [])

  const patchState = useCallback((id: string, update: (state: RunState) => RunState) => {
    setTurns(previous =>
      previous.map(turn => (turn.id === id ? { ...turn, state: update(turn.state) } : turn))
    )
  }, [])

  /**
   * Replace the transcript with the persisted one — but never under a live run. A refetch
   * that lands mid-turn would otherwise wipe the answer as it streams in.
   *
   * The turns it produces keep the identity of the turns already on screen (`keepTurnIdentity`),
   * because `TurnView` is keyed on that identity and a turn that changed its key was remounted —
   * losing every latch inside it, including the one that holds a thought's body open once it has
   * been shown. Re-reading the transcript is not a reason for the screen to forget what it just
   * showed.
   */
  const hydrate = useCallback((messages: readonly SessionMessage[]) => {
    setTurns(current => {
      if (current.some(turn => turn.streaming)) return current
      return keepTurnIdentity(turnsFromMessages(messages), current)
    })
  }, [])

  const submit = useCallback(
    async (
      input: string,
      options: { attachmentIds?: string[]; onStarted?: (runId: string) => void } = {}
    ) => {
      if (!client || !input.trim()) return

      const id = `turn-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
      const controller = new AbortController()
      const attachmentIds = options.attachmentIds ?? []

      // The turn the engine is given is the operator's words *plus* a listing of what they
      // attached — composed by the BFF, which is where the paths and the caps live. The
      // composed text is then parsed back into the shape the transcript renders, so a live
      // turn and a reloaded one go through exactly one code path (`parseTurn`).
      let runInput = input.trim()
      let shown: Pick<Turn, 'input' | 'attachments' | 'context'> = { input: input.trim() }
      if (attachmentIds.length > 0) {
        if (!bff) return
        try {
          const composed = await bff.composeTurn(sessionId, input, attachmentIds)
          runInput = composed.input
          const parsed = parseTurn(composed.input)
          shown = parsed.recognised
            ? { input: parsed.text, attachments: parsed.attachments, context: parsed.context }
            : { input: input.trim(), attachments: [], context: composed.input }
        } catch (error) {
          // Nothing was sent, so the turn is an error and the files stay where they are.
          setTurns(previous => [
            ...previous,
            {
              id,
              input: input.trim(),
              state: createRunState('pending'),
              streaming: false,
              error: describe(error)
            }
          ])
          return
        }
      }

      controllers.current.set(id, controller)

      setTurns(previous => [
        ...previous,
        { id, ...shown, state: createRunState('pending'), streaming: true }
      ])

      try {
        // Read at send time, not at render time: a voice changed in Settings applies to the turn
        // after it, which is what that screen promises. The voice may be empty, but the chat
        // surface's formatting instruction is always present (`currentVoiceInstructions`).
        const started = await client.startRun(
          runInput,
          sessionId,
          controller.signal,
          currentVoiceInstructions()
        )
        patchTurn(id, { runId: started.run_id })
        patchState(id, state => ({ ...state, runId: started.run_id, phase: 'running' }))
        // The engine has a session row now, so the rail can show it before the turn ends.
        options.onStarted?.(started.run_id)

        let state = createRunState(started.run_id)
        let terminal = false

        // Thinking only exists in the durable transcript, so a running turn reads it there on a
        // timer (the front-end design §2). It merges thoughts and nothing else: the text and
        // tool state below are the stream's, and the transcript must not be allowed to overwrite
        // a run in progress — which is exactly why `hydrate` refuses to touch a streaming turn.
        const stopPolling = pollThoughts(client, sessionId, controller.signal, messages => {
          setTurns(previous =>
            previous.map(turn => (turn.id === id ? withThoughts(turn, messages) : turn))
          )
        })

        try {
          // `streamRunWithResume` reconnects from the last sequence it saw, so a dropped
          // connection no longer loses the rest of the turn (the internal audit WEB-4).
          const streamed = await streamRunWithResume(
            client,
            started.run_id,
            state,
            controller.signal,
            {
              onState: snapshot => {
                state = snapshot
                // The stream is authoritative for everything it carries — and it carries no
                // thinking at all (the front-end design §2). Replacing the turn's state
                // wholesale therefore dropped the thoughts the poll had just merged, and the
                // next frame did it again: a step's body appeared on a poll, vanished on the
                // next delta, and came back two seconds later. That blink *is* the expansion
                // and contraction a live turn used to be. The thoughts the poll owns survive
                // every frame; everything else is the stream's.
                patchState(id, current => ({ ...snapshot, thoughts: current.thoughts }))
                if (snapshot.truncated) {
                  // The client fell behind: the state is no longer trustworthy. Say so rather
                  // than pretending the transcript is complete.
                  patchTurn(id, { needsRefetch: true })
                }
              }
            }
          )
          state = streamed.state
          terminal = streamed.terminal
        } finally {
          // Terminal phase, a thrown stream or an abort all land here, and all three mean the
          // turn is no longer running: nothing left to poll for.
          stopPolling()
        }

        if (!terminal) {
          // The attempts ran out, or the operator stopped it: the turn is over as far as this
          // client is concerned, and two things have to be closed out or they wedge the screen.
          // An unanswered approval left open keeps the composer disabled for ever ("Answer the
          // approval above first") because nothing will ever answer it now, and a thought left
          // running spins beside a turn that is not running (the internal audit WEB-2).
          endTurn(setTurns, id, { needsRefetch: true })
          return
        }

        patchTurn(id, { streaming: false, endedAt: Date.now() })

        // One last read of the transcript, for the two things the stream cannot carry: a tool
        // call's arguments (`tool.started` sends a display preview) and the thinking of the final
        // step, which the engine persists as the step ends — possibly after the last poll. Both
        // merges are additive, best-effort and silent: a turn that fails to reconcile renders
        // exactly as it did before.
        try {
          const recorded = await client.sessionMessages(sessionId, controller.signal)
          const messages = recorded.data ?? []
          setTurns(previous =>
            previous.map(turn =>
              turn.id === id ? withToolArguments(withThoughts(turn, messages), messages) : turn
            )
          )
        } catch {
          // Nothing to say: the live turn is already on screen and complete.
        }
      } catch (error) {
        // A turn that never reached a terminal phase — stopped by the operator, or a stream that
        // threw on its last attempt — still has to withdraw its last thought and close its open
        // approvals: nothing else will ever settle either.
        const failure = controller.signal.aborted
          ? { needsRefetch: true }
          : { error: describe(error), needsRefetch: true }
        endTurn(setTurns, id, failure)
      } finally {
        controllers.current.delete(id)
      }
    },
    [bff, client, sessionId, patchState, patchTurn]
  )

  const answer = useCallback(
    async (
      turnId: string,
      choice: ApprovalChoice,
      requestId: string | null,
      executionGeneration: number | null
    ): Promise<boolean> => {
      if (!client) return false
      const turn = turns.find(t => t.id === turnId)
      if (!turn?.runId) return false

      try {
        await client.respondToApproval(turn.runId, choice, requestId, executionGeneration)
        // The engine emits `approval.responded` on the run stream, which is what actually
        // moves the reducer. This call only delivers the decision.
        return true
      } catch (error) {
        // The card has to learn that the decision did not land, or its buttons stay disabled
        // for ever with no way to try again (the internal audit WEB-3). The turn's error
        // is still the operator-facing half.
        patchTurn(turnId, { error: describe(error) })
        return false
      }
    },
    [client, turns, patchTurn]
  )

  const answerClarify = useCallback(
    async (
      turnId: string,
      answer: string,
      promptId: string | null,
      executionGeneration: number | null
    ): Promise<boolean> => {
      if (!client) return false
      const turn = turns.find(t => t.id === turnId)
      if (!turn?.runId || !promptId || executionGeneration === null) return false

      try {
        await client.respondToClarify(turn.runId, answer, promptId, executionGeneration)
        // The engine emits `clarify.settled` on the run stream, which is what closes the card.
        return true
      } catch (error) {
        patchTurn(turnId, { error: describe(error) })
        return false
      }
    },
    [client, turns, patchTurn]
  )

  const stop = useCallback(
    async (turnId: string) => {
      const turn = turns.find(t => t.id === turnId)
      if (client && turn?.runId) {
        try {
          await client.stopRun(turn.runId)
        } catch {
          // A stop that fails is not worth an error banner; the stream will report it.
        }
      }
      controllers.current.get(turnId)?.abort()
    },
    [client, turns]
  )

  /**
   * Every approval still waiting on the operator, newest last.
   *
   * Expired ones are excluded deliberately: an unanswered approval whose run has ended can
   * never be answered, and counting it here would disable the composer for the rest of the
   * session.
   */
  const waiting = useMemo(
    () =>
      turns.flatMap(turn =>
        waitingApprovals(turn.state).map(approval => ({ turnId: turn.id, approval }))
      ),
    [turns]
  )

  /** Every clarifying question still waiting on the operator, newest last. */
  const questions = useMemo(
    () =>
      turns.flatMap(turn =>
        waitingClarifies(turn.state).map(prompt => ({ turnId: turn.id, prompt }))
      ),
    [turns]
  )

  return { turns, sessionId, waiting, questions, submit, answer, answerClarify, stop, hydrate }
}

function describe(error: unknown): string {
  if (error instanceof SeamUnreachable) return error.message
  if (error instanceof SeamError) return error.message
  if (error instanceof Error) {
    // A raw `TypeError` out of the read loop is a defect here, not something the operator can
    // act on: it used to reach the screen verbatim ("Cannot read properties of undefined…"),
    // which reads as their mistake (the internal audit WEB-17). Say what it means and
    // keep the message for a bug report.
    return (
      `The reply could not be read (${error.name}: ${error.message}). The conversation is in ` +
      'the engine — reopen it, and report this if it happens again.'
    )
  }
  return String(error)
}

/**
 * Finish a turn on this side of the seam, closing everything that would otherwise wait for ever.
 *
 * Three things outlive a run that ends without a terminal event — a stop, a dropped stream, a
 * stream that threw on its last attempt: an unanswered approval or clarifying question, either of
 * which keeps the composer disabled, and a live thought, which spins beside a turn that is not
 * running. All are settled here, in one place, because every one of those endings needs all
 * (the internal audit WEB-2).
 */
function endTurn(
  setTurns: (update: (previous: Turn[]) => Turn[]) => void,
  id: string,
  patch: Partial<Turn> = {}
): void {
  setTurns(previous =>
    previous.map(turn =>
      turn.id === id
        ? settleThoughts({
            ...turn,
            ...patch,
            streaming: false,
            endedAt: patch.endedAt ?? Date.now(),
            state: settleClarifies(settleApprovals(turn.state))
          })
        : turn
    )
  )
}
