import type { SessionMessage } from '@shared/wire'
import { describe, expect, it } from 'vitest'
import { createRunState, displayText } from '../seam/reducer'
import { settleThoughts, turnsFromMessages, withThoughts, withToolArguments } from './transcript'
import type { Turn } from './useConversation'

const message = (over: Partial<SessionMessage> & { id: number; role: string }): SessionMessage =>
  ({ session_id: 'web-1', content: '', ...over }) as SessionMessage

describe('turnsFromMessages', () => {
  it('opens a turn at each user message', () => {
    const turns = turnsFromMessages([
      message({ id: 1, role: 'user', content: 'Invoice Bellview' }),
      message({ id: 2, role: 'assistant', content: 'Drafted.' }),
      message({ id: 3, role: 'user', content: 'And send it' }),
      message({ id: 4, role: 'assistant', content: 'Nothing was sent.' })
    ])

    expect(turns).toHaveLength(2)
    expect(turns.map(t => t.input)).toEqual(['Invoice Bellview', 'And send it'])
    expect(turns.map(t => displayText(t.state))).toEqual(['Drafted.', 'Nothing was sent.'])
  })

  it('attaches tool results to the turn that asked for them', () => {
    const turns = turnsFromMessages([
      message({ id: 1, role: 'user', content: 'Invoice Bellview' }),
      message({ id: 2, role: 'assistant', content: '', reasoning: 'Look it up.' }),
      message({ id: 3, role: 'tool', tool_name: 'ledger_price', content: '12kg beans = $180' }),
      message({ id: 4, role: 'assistant', content: 'Drafted.' })
    ])

    expect(turns).toHaveLength(1)
    expect(turns[0].state.tools).toHaveLength(1)
    expect(turns[0].state.tools[0].tool).toBe('ledger_price')
    expect(turns[0].state.tools[0].result).toBe('12kg beans = $180')
    expect(turns[0].state.tools[0].status).toBe('ok')
  })

  it('joins prose the engine split across messages, and keeps each step’s thinking', () => {
    const turns = turnsFromMessages([
      message({ id: 1, role: 'user', content: 'What does Bellview owe?' }),
      message({ id: 2, role: 'assistant', content: 'Two invoices.', reasoning: 'Sum the ledger.' }),
      message({ id: 3, role: 'assistant', content: 'Total $396.' })
    ])

    expect(displayText(turns[0].state)).toBe('Two invoices.\n\nTotal $396.')
    expect(turns[0].state.thoughts).toHaveLength(1)
    expect(turns[0].state.thoughts[0].text).toBe('Sum the ledger.')
    expect(turns[0].state.thoughts[0].key).toBe('hist-thought-2')
  })

  it('ignores system messages and does not let them open a turn', () => {
    const turns = turnsFromMessages([
      message({ id: 1, role: 'system', content: 'You are a business agent.' }),
      message({ id: 2, role: 'user', content: 'Hi' })
    ])
    expect(turns).toHaveLength(1)
    expect(turns[0].input).toBe('Hi')
  })

  it('still renders a transcript that opens mid-conversation', () => {
    // A fork, or a session the engine seeded, can begin with an assistant message.
    const turns = turnsFromMessages([message({ id: 1, role: 'assistant', content: 'Resuming.' })])
    expect(turns).toHaveLength(1)
    expect(turns[0].input).toBe('')
    expect(displayText(turns[0].state)).toBe('Resuming.')
  })

  it('marks every historical turn complete, so nothing renders as streaming', () => {
    const turns = turnsFromMessages([
      message({ id: 1, role: 'user', content: 'Hi' }),
      message({ id: 2, role: 'assistant', content: 'Hello.' })
    ])
    expect(turns.every(t => t.state.phase === 'completed')).toBe(true)
    expect(turns.every(t => !t.streaming)).toBe(true)
  })

  it('is empty for an empty transcript', () => {
    expect(turnsFromMessages([])).toEqual([])
  })
})

describe('tool arguments', () => {
  const transcript = [
    message({ id: 1, role: 'user', content: 'Remember the delivery day' }),
    message({
      id: 2,
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_1',
          function: {
            name: 'memory',
            arguments: '{"action":"add","content":"Bellview delivers Tuesdays."}'
          }
        }
      ]
    }),
    message({ id: 3, role: 'tool', tool_name: 'memory', content: '{"success": true}' }),
    message({ id: 4, role: 'assistant', content: 'Saved.' })
  ]

  it('keeps the call’s arguments, which only the transcript has', () => {
    // The stream sends a display preview and a 500-character result; the arguments exist only
    // here. Without them a card can say that something was remembered and never what.
    const [turn] = turnsFromMessages(transcript)
    expect(turn.state.tools[0].args).toBe('{"action":"add","content":"Bellview delivers Tuesdays."}')
  })

  it('fills a live turn in without disturbing anything the client already knows', () => {
    const turn = {
      id: 'turn-1',
      input: 'Remember the delivery day',
      streaming: false,
      state: {
        ...createRunState('run_1'),
        phase: 'completed' as const,
        tools: [
          {
            key: 'memory#0',
            seq: 0,
            tool: 'memory',
            argsPreview: '+memory: "Bellview delivers Tu..."',
            result: '{"success": true}',
            status: 'ok' as const,
            duration: 0.31,
            startedAt: 5
          }
        ]
      }
    }

    const merged = withToolArguments(turn, transcript)
    expect(merged.state.tools[0].args).toBe('{"action":"add","content":"Bellview delivers Tuesdays."}')
    expect(merged.state.tools[0].argsPreview).toBe('+memory: "Bellview delivers Tu..."')
    expect(merged.state.tools[0].result).toBe('{"success": true}')
    expect(merged.state.tools[0].duration).toBe(0.31)
  })

  it('merges nothing when the counts disagree, rather than guessing which call is which', () => {
    const turn = {
      id: 'turn-1',
      input: 'x',
      streaming: false,
      state: {
        ...createRunState('run_1'),
        tools: [
          { key: 'a', seq: 0, tool: 'memory', status: 'ok' as const, startedAt: 0 },
          { key: 'b', seq: 1, tool: 'memory', status: 'ok' as const, startedAt: 0 }
        ]
      }
    }
    expect(withToolArguments(turn, transcript).state.tools.every(call => !call.args)).toBe(true)
  })

  it('does not attach a call to a different tool that happens to sit in the same place', () => {
    const turn = {
      id: 'turn-1',
      input: 'x',
      streaming: false,
      state: {
        ...createRunState('run_1'),
        tools: [{ key: 'a', seq: 0, tool: 'skill_manage', status: 'ok' as const, startedAt: 0 }]
      }
    }
    expect(withToolArguments(turn, transcript).state.tools[0].args).toBeUndefined()
  })

  it('leaves an already-reconciled call alone', () => {
    const [turn] = turnsFromMessages(transcript)
    expect(withToolArguments(turn, transcript).state.tools[0].args).toBe(turn.state.tools[0].args)
  })
})

describe('thinking', () => {
  /** Two finished turns and the one being written, so "this turn's own" can be checked. */
  const thread = [
    message({ id: 1, role: 'user', content: 'Invoice Bellview' }),
    message({ id: 2, role: 'assistant', content: '', reasoning: 'Look up the customer first.' }),
    message({ id: 3, role: 'tool', tool_name: 'ledger_customer', content: '{}' }),
    message({ id: 4, role: 'assistant', content: 'Two customers match.', reasoning: 'Ambiguous.' }),
    message({ id: 5, role: 'user', content: 'Bellview CSA then' }),
    message({ id: 6, role: 'assistant', content: 'Drafted.', reasoning: 'One customer, one price book.' })
  ]

  /** A turn as it exists mid-stream: its calls came off the wire, its thinking has not arrived. */
  const live = (over: Partial<Turn> = {}): Turn => ({
    id: 'turn-1',
    input: 'Bellview CSA then',
    streaming: true,
    state: { ...createRunState('run_1'), phase: 'running' },
    ...over
  })

  it('adds the thinking recorded for this turn, and nothing from the turns before it', () => {
    // The stream will never say any of this (the front-end design §2), so reading it out of
    // the transcript is the whole feature — and reading one turn too far back is the way it
    // would go wrong.
    const merged = withThoughts(live(), thread)
    expect(merged.state.thoughts.map(thought => thought.text)).toEqual([
      'One customer, one price book.'
    ])
  })

  it('anchors each thought to the calls that came before it', () => {
    const merged = withThoughts(live(), [
      ...thread,
      message({ id: 7, role: 'tool', tool_name: 'ledger_price', content: '{}' }),
      message({ id: 8, role: 'assistant', content: '', reasoning: 'Now price it.' })
    ])

    expect(merged.state.thoughts.map(thought => [thought.text, thought.seq])).toEqual([
      ['One customer, one price book.', 0],
      ['Now price it.', 1]
    ])
  })

  it('is idempotent: polling the same transcript again re-renders nothing', () => {
    const once = withThoughts(live(), thread)
    expect(withThoughts(once, thread)).toBe(once)
  })

  it('leaves the streamed text, tool state and approvals exactly as they were', () => {
    // The point of merging rather than refetching: mid-turn, the client's own record of the run
    // is the authority for everything except the thinking.
    const turn = live({
      state: {
        ...createRunState('run_1'),
        phase: 'awaiting_approval',
        text: 'half an answer',
        tools: [
          { key: 'ledger_customer#0', seq: 0, tool: 'ledger_customer', status: 'running', startedAt: 7 }
        ],
        approvals: [
          {
            key: '0',
            requestId: 'req-1',
            executionGeneration: null,
            description: 'Approve?',
            choices: ['once', 'deny']
          }
        ]
      }
    })

    const merged = withThoughts(turn, thread)
    expect(merged.state.text).toBe('half an answer')
    expect(merged.state.tools).toEqual(turn.state.tools)
    expect(merged.state.approvals).toEqual(turn.state.approvals)
    expect(merged.state.thoughts).toHaveLength(1)
  })

  it('keeps the newest thought of a running turn live and settles the ones behind it', () => {
    const merged = withThoughts(live(), [
      ...thread,
      message({ id: 7, role: 'tool', tool_name: 'ledger_price', content: '{}' }),
      message({ id: 8, role: 'assistant', content: '', reasoning: 'Now price it.' })
    ])

    expect(merged.state.thoughts.map(thought => thought.status)).toEqual(['settled', 'streaming'])
  })

  it('settles the last thought once the turn has finished', () => {
    const finished = live({ streaming: false, state: { ...createRunState('run_1'), phase: 'completed' } })
    expect(withThoughts(finished, thread).state.thoughts.map(thought => thought.status)).toEqual([
      'settled'
    ])
  })

  it('takes the final step’s thinking from the post-run read, already settled', () => {
    // The engine writes the last step's message as the step ends, which can be after the last
    // poll: the read that reconciles tool arguments is also where this arrives.
    const finished = live({ streaming: false, state: { ...createRunState('run_1'), phase: 'completed' } })
    const merged = withThoughts(finished, [
      ...thread,
      message({ id: 7, role: 'assistant', content: 'Drafted.', reasoning: 'Write it up plainly.' })
    ])

    expect(merged.state.thoughts.map(thought => [thought.text, thought.status])).toEqual([
      ['One customer, one price book.', 'settled'],
      ['Write it up plainly.', 'settled']
    ])
  })

  it('withdraws the live thought of a turn that stopped without a terminal phase', () => {
    // The operator's stop, or a stream that threw: nothing else will ever settle it, and a
    // pulsing "still thinking" on a turn that is over is a lie about the present.
    const running = withThoughts(live(), thread)
    expect(running.state.thoughts.map(thought => thought.status)).toEqual(['streaming'])

    const stopped = settleThoughts({ ...running, streaming: false })
    expect(stopped.state.thoughts.map(thought => thought.status)).toEqual(['settled'])
    expect(stopped.state.text).toBe(running.state.text)
    // Already settled: the same turn comes back, so nothing re-renders.
    expect(settleThoughts(stopped)).toBe(stopped)
  })

  it('finds a turn whose stored words are a composed attachment listing', () => {
    // A turn that carried attachments stores the operator's words plus the BFF's listing, so
    // matching on the raw text would never find it — it parses the same way the turn builder does.
    const composed = [
      message({ id: 1, role: 'user', content: 'Invoice Bellview\n\nAttached files (1):\n1. price-book.csv — text/csv\n   Path: /tmp/price-book.csv' }),
      message({ id: 2, role: 'assistant', content: '', reasoning: 'Read the price book.' })
    ]

    const merged = withThoughts(live({ input: 'Invoice Bellview' }), composed)
    expect(merged.state.thoughts.map(thought => thought.text)).toEqual(['Read the price book.'])
  })

  it('reads a reloaded turn’s thinking as already settled', () => {
    const [turn] = turnsFromMessages([
      message({ id: 1, role: 'user', content: 'Hi' }),
      message({ id: 2, role: 'assistant', content: 'Hello.', reasoning: 'A greeting.' })
    ])

    expect(turn.state.thoughts).toHaveLength(1)
    expect(turn.state.thoughts[0].status).toBe('settled')
    expect(turn.state.thoughts[0].seq).toBe(0)
  })
})
