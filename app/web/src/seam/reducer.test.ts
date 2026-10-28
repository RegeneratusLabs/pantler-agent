/**
 * The reducer is the piece of the front end that can silently be wrong. These tests are
 * the front end's half of the golden-conversation suite: the golden suite asserts on the
 * tool calls the engine made, this asserts on what the operator would have seen.
 *
 * The first test is the important one — it walks the whole vocabulary from `wire.ts`, so
 * an event added upstream cannot reach the screen untested.
 */

import { describe, expect, it } from 'vitest'
import { RUN_EVENT_TYPES, type RunEvent } from '@shared/wire'
import {
  waitingApprovals,
  waitingClarifies,
  settleClarifies,
  applyFrame,
  createRunState,
  displayText,
  isTerminal,
  reduce,
  type RunState
} from './reducer'

function ev(event: string, fields: Record<string, unknown> = {}): RunEvent {
  return { event, run_id: 'run-1', timestamp: 1_700_000_000, ...fields } as unknown as RunEvent
}

/** Fold a list of events through the reducer. */
function fold(events: RunEvent[], from: RunState = createRunState('run-1')): RunState {
  return events.reduce(reduce, from)
}

describe('the whole event vocabulary', () => {
  it.each(RUN_EVENT_TYPES)('handles %s without throwing or blanking state', type => {
    const before = createRunState('run-1')
    const after = reduce(before, ev(type, { tool: 'invoice_create', delta: 'x', text: 'x' }))

    expect(after.eventCount).toBe(before.eventCount + 1)
    // An event must never lose the run identity or reset accumulated work.
    expect(after.runId).toBe('run-1')
    expect(after.tools.length).toBeGreaterThanOrEqual(before.tools.length)
    expect(after.approvals.length).toBeGreaterThanOrEqual(before.approvals.length)
  })

  it('covers every type declared in the wire contract', () => {
    // Guards against the vocabulary array drifting away from the union it satisfies.
    expect(new Set(RUN_EVENT_TYPES).size).toBe(RUN_EVENT_TYPES.length)
    expect(RUN_EVENT_TYPES).toContain('approval.request')
    expect(RUN_EVENT_TYPES).toContain('replay.truncated')
  })

  it('ignores an event it has never seen, without throwing', () => {
    const after = reduce(createRunState('run-1'), ev('something.brand.new', { surprise: true }))
    expect(after.eventCount).toBe(1)
    expect(after.phase).toBe('queued')
  })
})

describe('lifecycle', () => {
  it('walks queued → running → completed and keeps the final reply', () => {
    const state = fold([
      ev('run.queued'),
      ev('run.started'),
      ev('message.delta', { delta: 'Draft ' }),
      ev('message.delta', { delta: 'INV-0001.' }),
      ev('run.completed', { output: 'Draft INV-0001 is ready.', completed: true })
    ])

    expect(state.phase).toBe('completed')
    expect(isTerminal(state.phase)).toBe(true)
    expect(state.text).toBe('Draft INV-0001.')
    expect(state.output).toBe('Draft INV-0001 is ready.')
  })

  it('prefers the authoritative output over the streamed text', () => {
    const state = fold([ev('message.delta', { delta: 'partial' }), ev('run.completed', { output: 'final' })])
    expect(displayText(state)).toBe('final')
  })

  it('falls back to the streamed text when the run never reported output', () => {
    const state = fold([ev('message.delta', { delta: 'streamed only' }), ev('run.cancelled')])
    expect(state.phase).toBe('cancelled')
    expect(displayText(state)).toBe('streamed only')
  })

  it.each([
    ['run.failed', 'failed'],
    ['run.cancelled', 'cancelled'],
    ['run.interrupted', 'interrupted']
  ])('%s is terminal', (type, phase) => {
    const state = reduce(createRunState('run-1'), ev(type, { error: 'boom' }))
    expect(state.phase).toBe(phase)
    expect(isTerminal(state.phase)).toBe(true)
  })

  it('records a stopping run without treating it as terminal', () => {
    const state = fold([ev('run.started'), ev('run.stopping')])
    expect(state.phase).toBe('stopping')
    expect(isTerminal(state.phase)).toBe(false)
  })

  it('does not treat a steer as a state change', () => {
    const state = fold([ev('run.started'), ev('run.steered', { text: 'actually, make it 6 kilos' })])
    expect(state.phase).toBe('running')
  })
})

describe('assistant text', () => {
  it('accumulates deltas from both names the engine uses', () => {
    const state = fold([
      ev('message.delta', { delta: 'a' }),
      ev('assistant.delta', { delta: 'b' }),
      ev('message.delta', { delta: 'c' })
    ])
    expect(state.text).toBe('abc')
  })

  it('treats interim commentary as a snapshot, not a delta', () => {
    // Appending here would duplicate the text on screen.
    const state = fold([
      ev('message.interim', { text: 'Checking the price book…' }),
      ev('message.interim', { text: 'Checking the price book… done.' })
    ])
    expect(state.interim).toBe('Checking the price book… done.')
  })

  it('does not repeat commentary the engine already streamed', () => {
    // `already_streamed: true` means the same text also arrived as deltas, so storing the
    // snapshot as well rendered the paragraph twice — once in italics over the composer and
    // once in the answer (the internal audit CON-3).
    const state = fold([
      ev('message.delta', { delta: 'Checking the price book…' }),
      ev('message.interim', { text: 'Checking the price book…', already_streamed: true })
    ])
    expect(state.text).toBe('Checking the price book…')
    expect(state.interim).toBe('')
  })

  it('still shows commentary that was not streamed', () => {
    const state = fold([ev('message.interim', { text: 'One moment.' })])
    expect(state.interim).toBe('One moment.')
  })

  it('clears interim commentary when a new message starts', () => {
    const state = fold([ev('message.interim', { text: 'thinking' }), ev('message.started')])
    expect(state.interim).toBe('')
  })

  it('does not make a thought out of reasoning.available', () => {
    // The event is a decoy on this surface: `_relay_thinking` sends the assistant's own message
    // content — tags stripped, capped at 500 characters (`turn_response_intake.py:103-116`) —
    // and the runs surface maps it to `{text}` (`api_server_runs.py:97`). Probing a live turn
    // caught exactly that: one event for the whole turn, carrying the ANSWER, after
    // `message.delta`. Real thinking is read per step from the durable transcript, so this must
    // change nothing at all — and must not throw, because an unknown future is not a blank screen.
    const state = fold([ev('reasoning.available', { text: 'noted' })])
    expect(state.thoughts).toEqual([])
    expect(state.text).toBe('')

    const withAnswer = fold([ev('reasoning.available', { text: 'noted' }), ev('message.delta', { delta: 'Here you go.' })])
    expect(displayText(withAnswer)).toBe('Here you go.')
    expect(withAnswer.thoughts).toEqual([])
  })
})

describe('tool calls', () => {
  it('carries the tool result — the source of truth, not the prose', () => {
    const result = 'Draft INV-0001 for Bellview CSA:\n  • 12 kg Green Beans @ $12.00 = $144.00'
    const state = fold([
      ev('tool.started', { tool: 'invoice_create', preview: '{"customer":"Bellview CSA"}' }),
      ev('tool.completed', { tool: 'invoice_create', preview: result, duration: 0.42, error: false })
    ])

    expect(state.tools).toHaveLength(1)
    expect(state.tools[0].status).toBe('ok')
    expect(state.tools[0].result).toBe(result)
    expect(state.tools[0].duration).toBe(0.42)
  })

  it('marks a completed call with error=true as an error', () => {
    const state = fold([
      ev('tool.started', { tool: 'invoice_create' }),
      ev('tool.completed', { tool: 'invoice_create', error: true })
    ])
    expect(state.tools[0].status).toBe('error')
  })

  it('records a completion whose start it never saw', () => {
    // The client can attach mid-run; dropping the result would hide it from the operator.
    const state = reduce(createRunState('run-1'), ev('tool.completed', { tool: 'invoice_show', preview: 'INV-0001' }))
    expect(state.tools).toHaveLength(1)
    expect(state.tools[0].result).toBe('INV-0001')
  })

  it('keys repeat calls separately and settles them in order', () => {
    const state = fold([
      ev('tool.started', { tool: 'invoice_create' }),
      ev('tool.started', { tool: 'invoice_create' }),
      ev('tool.completed', { tool: 'invoice_create', preview: 'first' }),
      ev('tool.completed', { tool: 'invoice_create', preview: 'second' })
    ])

    expect(state.tools).toHaveLength(2)
    expect(state.tools[0].key).not.toBe(state.tools[1].key)
    expect(state.tools[0].result).toBe('first')
    expect(state.tools[0].status).toBe('ok')
    expect(state.tools[1].result).toBe('second')
    expect(state.tools[1].status).toBe('ok')
  })

  it('records a tool failure with its message', () => {
    const state = fold([
      ev('tool.started', { tool: 'invoice_send' }),
      ev('tool.failed', { tool: 'invoice_send', error: 'no such invoice' })
    ])
    expect(state.tools[0].status).toBe('error')
    expect(state.tools[0].result).toBe('no such invoice')
  })

  it('keeps the arguments preview from tool.started', () => {
    const state = reduce(createRunState('run-1'), ev('tool.started', { tool: 'invoice_create', preview: 'args' }))
    expect(state.tools[0].argsPreview).toBe('args')
  })

  it('numbers calls in the order they started', () => {
    // The wire has no call id and no sequence number, so this order is the only one there is —
    // and it is what a thought is anchored against (`thought.ts`).
    const state = fold([
      ev('tool.started', { tool: 'web_search' }),
      ev('tool.started', { tool: 'read_file' }),
      ev('tool.completed', { tool: 'web_search', preview: 'x' })
    ])

    expect(state.tools.map(call => call.seq)).toEqual([0, 1])
  })

  it('numbers a completion whose start it never saw, rather than leaving it unanchored', () => {
    const state = fold([
      ev('tool.started', { tool: 'web_search' }),
      ev('tool.completed', { tool: 'read_file', preview: 'x' })
    ])

    expect(state.tools.map(call => call.seq)).toEqual([0, 1])
  })
})

describe('the money gate', () => {
  const approval = (fields: Record<string, unknown> = {}) =>
    ev('approval.request', {
      request_id: 'req-1',
      description: 'Send invoice INV-0001 to the customer. This leaves the business and cannot be unsent — approve sending it?',
      choices: ['once', 'session', 'always', 'deny'],
      pattern_key: 'pantler.money_gate:invoice_send',
      ...fields
    })

  it('parks the run and surfaces the gate’s own sentence', () => {
    const state = fold([ev('run.started'), approval()])

    expect(state.phase).toBe('awaiting_approval')
    expect(isTerminal(state.phase)).toBe(false)
    const pending = waitingApprovals(state)[0]
    expect(pending?.requestId).toBe('req-1')
    expect(pending?.description).toContain('cannot be unsent')
    expect(pending?.choices).toEqual(['once', 'session', 'always', 'deny'])
    expect(pending?.patternKey).toBe('pantler.money_gate:invoice_send')
  })

  it('resumes the run when approved', () => {
    const state = fold([
      ev('run.started'),
      approval(),
      ev('approval.responded', { choice: 'once', request_id: 'req-1', resolved: 1 })
    ])

    expect(state.phase).toBe('running')
    expect(waitingApprovals(state)).toHaveLength(0)
    expect(state.approvals.filter(a => a.resolution?.choice === 'deny')).toHaveLength(0)
  })

  it('treats a denial as a decision, not a failure', () => {
    // The whole point of the gate: the run continues, the tool never ran, and the screen
    // says nothing happened rather than showing an error.
    const state = fold([
      ev('run.started'),
      approval(),
      ev('approval.responded', { choice: 'deny', request_id: 'req-1', resolved: 1 }),
      ev('message.delta', { delta: 'No problem — it stays a draft.' }),
      ev('run.completed', { output: 'No problem — it stays a draft.' })
    ])

    expect(state.phase).toBe('completed')
    expect(isTerminal(state.phase)).toBe(true)
    expect(state.approvals.filter(a => a.resolution?.choice === 'deny')).toHaveLength(1)
    expect(state.approvals[0].resolution?.choice).toBe('deny')
    // Nothing claimed the send happened.
    expect(state.tools.some(t => t.tool === 'invoice_send' && t.status === 'ok')).toBe(false)
  })

  it('matches the response to the exact request when several are pending', () => {
    const state = fold([
      ev('run.started'),
      approval({ request_id: 'req-1' }),
      approval({ request_id: 'req-2' }),
      ev('approval.responded', { choice: 'deny', request_id: 'req-1', resolved: 1 })
    ])

    expect(state.approvals[0].resolution?.choice).toBe('deny')
    expect(state.approvals[1].resolution).toBeUndefined()
    expect(waitingApprovals(state)[0]?.requestId).toBe('req-2')
  })

  it('resolves the oldest pending request when none is named', () => {
    const state = fold([
      ev('run.started'),
      approval({ request_id: 'req-1' }),
      ev('approval.responded', { choice: 'session' })
    ])
    expect(state.approvals[0].resolution?.choice).toBe('session')
  })

  it('tolerates an approval event with no choices, defaulting to once/deny', () => {
    const state = reduce(createRunState('run-1'), ev('approval.request', { description: 'Approve?' }))
    expect(state.approvals[0].choices).toEqual(['once', 'deny'])
    expect(state.approvals[0].requestId).toBeNull()
    expect(state.approvals[0].executionGeneration).toBeNull()
  })

  it('reads the host-multiplex approval shape: prompt_id and execution_generation', () => {
    // The authority run emits `prompt_id` + `execution_generation`, not `request_id`. Answering
    // it without the generation is a 400 (`invalid_params`), which is what this field fixes.
    const state = reduce(
      createRunState('run-1'),
      ev('approval.request', {
        prompt_id: 'prompt-1',
        execution_generation: 3,
        description: 'Connected app change: GMAIL_CREATE_EMAIL_DRAFT',
        command: '<connector_use> (plugin approval rule)'
      })
    )
    expect(state.approvals[0].requestId).toBe('prompt-1')
    expect(state.approvals[0].executionGeneration).toBe(3)
  })

  it('keeps the command and the guardian’s refusal, which the card needs to say anything true', () => {
    // Verified against the wire: the engine redacts the command before egress
    // (api_server.py:113) and derives `choices` from smart_denied/allow_session/allow_permanent
    // (api_server.py:108) — so those two flags need no separate field.
    const state = reduce(
      createRunState('run-1'),
      ev('approval.request', {
        request_id: 'req-1',
        description: 'script execution via -e/-c flag',
        command: 'python -c "print(1)"',
        smart_denied: true,
        choices: ['once', 'deny'],
        allow_session: false,
        allow_permanent: false
      })
    )

    const request = state.approvals[0]
    expect(request.command).toBe('python -c "print(1)"')
    expect(request.smartDenied).toBe(true)
    expect(request.choices).toEqual(['once', 'deny'])
  })

  it('does not invent a command or an override that the engine never sent', () => {
    const state = reduce(
      createRunState('run-1'),
      ev('approval.request', { description: 'recursive delete', command: '   ' })
    )
    expect(state.approvals[0].command).toBeUndefined()
    expect(state.approvals[0].smartDenied).toBe(false)
  })

  it('expires an unanswered approval when the run ends', () => {
    // The engine blocks the action on timeout and emits NO approval.responded, so the run
    // reaching a terminal state is the only signal that this will never be answered. Left
    // pending, the card would read "waiting on you" forever and disable the composer.
    const state = fold([
      ev('run.started'),
      approval(),
      ev('run.completed', { output: 'The action was blocked.' })
    ])

    expect(state.approvals[0].expired).toBe(true)
    expect(waitingApprovals(state)).toHaveLength(0)
    expect(state.approvals.filter(a => a.expired)).toHaveLength(1)
    // It is not a denial — the operator never decided anything.
    expect(state.approvals.filter(a => a.resolution?.choice === 'deny')).toHaveLength(0)
  })

  it('does not expire an approval the operator actually answered', () => {
    const state = fold([
      ev('run.started'),
      approval(),
      ev('approval.responded', { choice: 'deny', request_id: 'req-1', resolved: 1 }),
      ev('run.completed')
    ])

    expect(state.approvals[0].expired).toBeUndefined()
    expect(state.approvals.filter(a => a.expired)).toHaveLength(0)
    expect(state.approvals.filter(a => a.resolution?.choice === 'deny')).toHaveLength(1)
  })
})

describe('clarifying questions', () => {
  const question = (fields: Record<string, unknown> = {}) =>
    ev('clarify.request', {
      prompt_id: 'prompt-1',
      execution_generation: 2,
      question: 'Which do you want?',
      choices: ['Apples (Recommended)', 'Pears'],
      multi_select: false,
      ...fields
    })

  it('parks the run on a question, with the engine’s own choices', () => {
    const state = fold([ev('run.started'), question()])

    expect(state.phase).toBe('awaiting_clarify')
    expect(state.clarifies).toHaveLength(1)
    expect(state.clarifies[0]).toMatchObject({
      promptId: 'prompt-1',
      executionGeneration: 2,
      question: 'Which do you want?',
      choices: ['Apples (Recommended)', 'Pears'],
      multiSelect: false
    })
    expect(waitingClarifies(state)).toHaveLength(1)
  })

  it('closes the named question and resumes the run when the engine settles it', () => {
    const state = fold([
      ev('run.started'),
      question(),
      ev('clarify.settled', { prompt_id: 'prompt-1', execution_generation: 2 })
    ])

    expect(state.clarifies[0].settled).toBe(true)
    expect(waitingClarifies(state)).toHaveLength(0)
    expect(state.phase).toBe('running')
  })

  it('settles the oldest question when the event does not name one', () => {
    const state = fold([
      ev('run.started'),
      question({ prompt_id: 'prompt-1' }),
      question({ prompt_id: 'prompt-2' }),
      ev('clarify.settled')
    ])

    expect(state.clarifies[0].settled).toBe(true)
    expect(state.clarifies[1].settled).toBeUndefined()
    expect(waitingClarifies(state)).toHaveLength(1)
  })

  it('expires an unanswered question when the run ends', () => {
    const state = fold([
      ev('run.started'),
      question(),
      ev('run.completed', { output: 'Moved on.' })
    ])

    expect(state.clarifies[0].expired).toBe(true)
    expect(waitingClarifies(state)).toHaveLength(0)
  })

  it('settles an open question when the stream drops or the operator stops', () => {
    const state = settleClarifies(fold([ev('run.started'), question()]))
    expect(state.clarifies[0].expired).toBe(true)
    expect(state.phase).toBe('awaiting_clarify')
  })

  it('tolerates a question with no id or choices, which the card cannot answer', () => {
    const state = reduce(createRunState('run-1'), ev('clarify.request', { question: 'Well?' }))

    expect(state.clarifies[0].promptId).toBeNull()
    expect(state.clarifies[0].executionGeneration).toBeNull()
    expect(state.clarifies[0].choices).toEqual([])
  })
})

describe('delegation', () => {  it('tracks a subagent from start to complete', () => {
    const state = fold([
      ev('subagent.start', { subagent_id: 'sub-1', goal: 'read the price book' }),
      ev('subagent.complete', { subagent_id: 'sub-1', summary: 'done' })
    ])

    expect(state.subagents).toHaveLength(1)
    expect(state.subagents[0].status).toBe('complete')
    expect(state.subagents[0].summary).toBe('done')
  })
})

describe('the resume cursor', () => {
  it('advances the cursor from the SSE frame id, not the payload', () => {
    const state = applyFrame(createRunState('run-1'), { id: 7, data: ev('message.delta', { delta: 'x' }) })
    expect(state.lastSeq).toBe(7)
    expect(state.text).toBe('x')
  })

  it('leaves the cursor alone when the frame has no id', () => {
    const state = applyFrame(createRunState('run-1'), { id: null, data: ev('message.delta', { delta: 'x' }) })
    expect(state.lastSeq).toBeNull()
  })

  it('flags a truncated replay so the UI refetches instead of trusting its state', () => {
    const state = reduce(createRunState('run-1'), ev('replay.truncated', { oldest_retained_seq: 900, requested_seq: 3 }))
    expect(state.truncated).toBe(true)
  })
})
