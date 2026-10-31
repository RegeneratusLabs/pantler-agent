/**
 * Turning a persisted session back into turns.
 *
 * The live path builds `RunState` from the SSE stream; this builds the same shape from
 * `GET /api/sessions/{id}/messages`. Both end at `TurnView`, which is the point — a
 * resumed conversation renders through exactly the same components as a live one, so a
 * tool card cannot look different depending on when it was made.
 *
 * The transcript is coarser than the stream: an assistant turn arrives as one message with
 * its final text, and a tool's result arrives whole rather than capped at 500 characters.
 * That is a fidelity gain, not a loss.
 *
 * It is also the ONLY place thinking exists. The runs surface relays the assistant's own text
 * under `reasoning.available` rather than its reasoning (the front-end design §2), so a
 * thought is read from here — during the turn as well as after it (`withThoughts`).
 */

import type { SessionMessage } from '@shared/wire'
import { parseTurn } from '@shared/attachments'
import { createRunState, isTerminal, type Thought } from '../seam/reducer'
import type { Turn } from './useConversation'

/**
 * The arguments of every tool call in a message list, in the order the engine persisted them.
 *
 * A call's arguments live on the *assistant* message that requested it, and only its result
 * comes back on the `tool` message — joined by `tool_call_id`. The stream's own events carry
 * neither, so this ordering (`tool_calls` in order, then the tool messages in order) is what
 * lets a live turn be reconciled with the record of it. Tools run sequentially within a turn
 * — the same assumption `settleTool` already documents — so the two orders agree.
 */
export function toolArguments(messages: readonly SessionMessage[]): Array<{ name: string; arguments: string }> {
  const calls: Array<{ name: string; arguments: string }> = []
  for (const message of messages) {
    if (message.role !== 'assistant' || !message.tool_calls) continue
    for (const call of message.tool_calls) {
      calls.push({
        name: call.function?.name ?? '',
        arguments: call.function?.arguments ?? ''
      })
    }
  }
  return calls
}

/**
 * Fill in a turn's tool arguments from the transcript, without touching anything else.
 *
 * Deliberately additive and deliberately timid. It writes `args` and stops: no status, no
 * result, no text, so a failure the client saw and the transcript does not record cannot be
 * erased by asking. When the counts disagree — a fork, a compaction, a tool message the
 * gateway did not persist — nothing is merged at all, because guessing which call is which
 * would be worse than the card showing less.
 */
export function withToolArguments(turn: Turn, messages: readonly SessionMessage[]): Turn {
  const recorded = toolArguments(messages)
  const mine = turn.state.tools
  if (recorded.length !== mine.length || recorded.length === 0) return turn

  const tools = mine.map((call, index) => {
    const source = recorded[index]
    // Match on the name as well as the position: a position that lines up but names a
    // different tool is a coincidence, not a match.
    if (!source.arguments || source.name !== call.tool || call.args) return call
    return { ...call, args: source.arguments }
  })

  return { ...turn, state: { ...turn.state, tools } }
}

/**
 * One assistant step's thinking, if the engine recorded any.
 *
 * `seq` is the turn's own anchor: how many of its tool calls came before this thought. The
 * engine writes a step's reasoning and the calls it produced on the SAME assistant message
 * (`agent/AGENTS.md`: reasoning is stored on `assistant_msg["reasoning"]`), so a thought always
 * sits ahead of its own calls — and counting calls, rather than an index into the transcript,
 * keeps that true for a turn read back whole and a turn whose calls were streamed one by one.
 */
function thoughtFrom(message: SessionMessage, seq: number, status: Thought['status']): Thought | null {
  const text = (message.reasoning ?? message.reasoning_content ?? '').trim()
  if (!text) return null
  return { key: `hist-thought-${message.id}`, text, status, seq }
}

/**
 * The thinking a transcript records from `from` onwards, in step order.
 *
 * Tool MESSAGES are what `turnsFromMessages` turns into calls, so they are what the anchor
 * counts: the two readings agree by construction rather than by convention.
 */
export function recordedThoughts(messages: readonly SessionMessage[], from = 0): Thought[] {
  const thoughts: Thought[] = []
  let calls = 0

  for (let index = from; index < messages.length; index++) {
    const message = messages[index]
    if (message.role === 'tool') calls += 1
    if (message.role !== 'assistant') continue
    const thought = thoughtFrom(message, calls, 'settled')
    if (thought) thoughts.push(thought)
  }

  return thoughts
}

/**
 * The messages belonging to one turn: its own user message to the end of the transcript.
 *
 * The turn is identified by its words, parsed exactly as `openUserTurn` parses a persisted user
 * message, so a turn that carried attachments — whose stored text is the composed listing, not
 * what the operator typed — still matches. The NEWEST match wins, because the live turn is the
 * one being written now. With no match at all (a fork, a session the engine seeded), the tail
 * from the last user message is used rather than the whole list: a turn boundary is still a
 * boundary, and reading past one would put another turn's thinking on screen.
 */
function messagesOfTurn(
  messages: readonly SessionMessage[],
  input: string
): readonly SessionMessage[] {
  const words = input.trim()
  let lastUser = -1

  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.role !== 'user') continue
    if (lastUser === -1) lastUser = index
    const parsed = parseTurn(message.content ?? '')
    const spoke = parsed.recognised ? parsed.text : (message.content ?? '')
    if (spoke.trim() === words) return messages.slice(index)
  }

  return lastUser === -1 ? messages : messages.slice(lastUser)
}

/**
 * Merge the thinking the transcript has recorded for a live turn — and nothing else.
 *
 * Deliberately narrower than a refetch. It writes `thoughts` and stops: the streamed text, the
 * tool statuses, the approvals and the error on screen are the client's own record of the run,
 * and a transcript read landing mid-turn must not overwrite any of them. Thinking is the one
 * thing the stream cannot carry at all (§2 status note), so it is the one thing read from here
 * — which is also why this runs *while* the turn streams, where `hydrate` refuses to go.
 *
 * Idempotent by key, so polling the same transcript again adds nothing, and a merge that
 * changes nothing returns the same turn object so React re-renders nothing.
 */
export function withThoughts(turn: Turn, messages: readonly SessionMessage[]): Turn {
  const known = new Set(turn.state.thoughts.map(thought => thought.key))
  const added = recordedThoughts(messagesOfTurn(messages, turn.input)).filter(
    thought => !known.has(thought.key)
  )
  const merged =
    added.length === 0
      ? turn.state.thoughts
      : [...turn.state.thoughts, ...added].sort((a, b) => a.seq - b.seq)
  const thoughts = stampLive(merged, !isTerminal(turn.state.phase))

  return thoughts === turn.state.thoughts ? turn : { ...turn, state: { ...turn.state, thoughts } }
}

/**
 * Settle every thought in a turn that is no longer running.
 *
 * The one case the merge cannot see for itself. A turn the operator stopped — or one whose
 * stream threw before a terminal event arrived — never reaches a terminal phase, so nothing else
 * would ever stamp its last thought as read, and the screen would keep a pulsing, clamped
 * "still thinking" on a turn that has stopped. A claim about the present has to be withdrawn by
 * whoever knows it is over.
 */
export function settleThoughts(turn: Turn): Turn {
  const thoughts = stampLive(turn.state.thoughts, false)
  return thoughts === turn.state.thoughts ? turn : { ...turn, state: { ...turn.state, thoughts } }
}

/**
 * Mark the newest thought of an unfinished turn as the live one.
 *
 * The engine persists thinking a step at a time, so "streaming" here is not characters
 * arriving — it is *the step still being read*. The screen marks that step with the pulse and
 * the word `Think`; it does not open the body by itself. A body the operator opens follows the
 * end of the text while the step is live and stays open after this stamp moves on to the next
 * step (`components/thought.ts`, `thoughtOpen`). The end of the turn settles the last one.
 */
function stampLive(thoughts: Thought[], running: boolean): Thought[] {
  const last = thoughts.length - 1
  let changed = false

  const stamped = thoughts.map((thought, index) => {
    const status: Thought['status'] = running && index === last ? 'streaming' : 'settled'
    if (thought.status === status) return thought
    changed = true
    return { ...thought, status }
  })

  return changed ? stamped : thoughts
}

export function turnsFromMessages(messages: readonly SessionMessage[]): Turn[] {
  const turns: Turn[] = []
  let current: Turn | null = null
  let toolCount = 0

  const start = (
    input: string,
    id: string,
    extra: Pick<Turn, 'input' | 'attachments' | 'context'> = { input }
  ): Turn => {
    const turn: Turn = {
      id,
      ...extra,
      state: { ...createRunState('history'), phase: 'completed' },
      streaming: false
    }
    turns.push(turn)
    return turn
  }

  /**
   * A persisted user message is the *composed* turn when it carried attachments: the
   * operator's words, then the listing the BFF wrote (the attachment design §4). Parsing it
   * back is what lets a reloaded turn show the same chips a live one did.
   */
  const openUserTurn = (content: string, id: string): Turn => {
    const parsed = parseTurn(content)
    if (!parsed.recognised) return start(content, id)
    return start(parsed.text, id, {
      input: parsed.text,
      attachments: parsed.attachments,
      context: parsed.context
    })
  }

  for (const message of messages) {
    if (message.role === 'system') continue

    if (message.role === 'user') {
      current = openUserTurn(message.content ?? '', `hist-${message.id}`)
      continue
    }

    // A transcript that opens with an assistant or tool message (a fork, or a session the
    // engine seeded) still has to render, so open a turn for it rather than dropping it.
    if (!current) current = start('', `hist-${message.id}`)
    const state = current.state

    if (message.role === 'assistant') {
      const text = (message.content ?? '').trim()
      if (text) state.text = state.text ? `${state.text}\n\n${text}` : text

      // A turn read back is finished, so every thought in it has already been read: none of
      // them is live. `state.tools.length` at this point is how many calls came before this
      // step's thinking, which is the anchor `withThoughts` reads the same way.
      const thought = thoughtFrom(message, state.tools.length, 'settled')
      if (thought) state.thoughts.push(thought)
      continue
    }

    if (message.role === 'tool') {
      state.tools.push({
        key: `hist-tool-${toolCount++}`,
        seq: state.tools.length,
        tool: message.tool_name ?? 'tool',
        result: message.content ?? '',
        status: 'ok',
        startedAt: 0
      })
    }
  }

  // The persisted call's own arguments, joined to the tool messages by the order the engine
  // wrote them. Without this a reloaded turn could show *that* something was remembered and
  // never *what* — the arguments only ever exist on the message, not on the stream.
  const recorded = toolArguments(messages)
  const persisted = turns.flatMap(turn => turn.state.tools)
  persisted.forEach((call, index) => {
    const source = recorded[index]
    if (source && source.name === call.tool && source.arguments) call.args = source.arguments
  })

  // `displayText` prefers `output`, so promote the accumulated prose once, here, rather
  // than duplicating it in every render.
  for (const turn of turns) {
    if (turn.state.text) turn.state.output = turn.state.text
  }

  return turns
}
