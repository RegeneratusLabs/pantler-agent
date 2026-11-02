/**
 * Where thinking lands among the work, what it says when it is collapsed, and when its body is
 * showing.
 *
 * The interleaving is the part worth testing: `seq` is an anchor ("how many calls came before
 * this thought"), the tools arrive as segments that fold, and getting the two into one order is
 * the whole of "the reason for a search sits next to the search".
 *
 * The other one is the rule the row is judged by now: a thought is closed until the operator
 * asks. Being the live step is not enough; the pulse says it is running, and the body is one
 * click away. Once the operator opens it, the body stays open when the step lands.
 */

import { describe, expect, it } from 'vitest'
import type { Thought, ToolCall } from '../seam/reducer'
import { stepsOf, thoughtControl, thoughtLine, thoughtOpen, type TurnStep } from './thought-steps'

function call(seq: number, tool = 'web_search', status: ToolCall['status'] = 'ok'): ToolCall {
  return { key: `${tool}#${seq}`, seq, tool, status, startedAt: 0 }
}

/** A pack tool's own record — the one result shape that prints as a card (`activity.ts`). */
const DRAFT = [
  'Draft INV-0001 for Bellview CSA:',
  '  • 12 kg Green Beans @ $12.00 = $144.00',
  '  Total: $144.00',
  'It is a draft and has not been sent.'
].join('\n')

function card(seq: number, tool = 'invoice_create'): ToolCall {
  return { key: `${tool}#${seq}`, seq, tool, status: 'ok', result: DRAFT, startedAt: 0 }
}

function thought(seq: number, text = 'thinking', status: Thought['status'] = 'settled'): Thought {
  return { key: `hist-thought-${seq}`, seq, text, status }
}

/** What a step list looks like as text: a thought as `?`, a card as the tool's name. */
const shape = (steps: readonly TurnStep[]): string[] =>
  steps.map(step => (step.kind === 'thought' ? `?${step.thought.seq}` : step.kind))

describe('stepsOf', () => {
  it('puts a thought above the calls it produced', () => {
    const steps = stepsOf([thought(0)], [card(0), card(1, 'invoice_show')])

    expect(shape(steps)).toEqual(['?0', 'card', 'card'])
    expect(steps[1]).toMatchObject({ kind: 'card', call: { tool: 'invoice_create' } })
  })

  it('reads the anchor as "calls before this thought", so it can land between two', () => {
    // The engine writes a step's reasoning and its calls on one message, so the second thought
    // of a two-step turn is anchored at 1 — ahead of its own call and behind the first one's.
    expect(shape(stepsOf([thought(1)], [card(0), card(1, 'invoice_show')]))).toEqual([
      'card',
      '?1',
      'card'
    ])
  })

  it('opens the turn with a thought that had nothing behind it yet', () => {
    expect(shape(stepsOf([thought(0)], [card(0)]))).toEqual(['?0', 'card'])
  })

  it('keeps thinking with no calls at all', () => {
    expect(shape(stepsOf([thought(0)], []))).toEqual(['?0'])
  })

  it('orders by seq, not by the order the transcript happened to be read in', () => {
    const steps = stepsOf([thought(2), thought(0), thought(1)], [card(0), card(1), card(2)])

    expect(steps.filter(step => step.kind === 'thought').map(step => step.thought.seq)).toEqual([0, 1, 2])
  })

  it('does not split a folded run of activity, even when a thought is anchored inside it', () => {
    // Five plumbing calls fold into one line (`segmentTools`). A thought between them must not
    // cut the run in half: the run is one piece of work and reads as one.
    const tools = [call(0), call(1), call(2), call(3), call(4)]
    const steps = stepsOf([thought(3)], tools)

    expect(shape(steps)).toEqual(['activity', '?3'])
    expect(steps[0]).toMatchObject({ kind: 'activity' })
    expect((steps[0] as { calls: ToolCall[] }).calls).toHaveLength(5)
  })

  it('lets a card end the run before the next thought', () => {
    const steps = stepsOf([thought(1)], [call(0, 'web_search'), card(1, 'invoice_create')])

    expect(shape(steps)).toEqual(['activity', '?1', 'card'])
  })

  it('places thinking anchored past the last call after the work', () => {
    expect(shape(stepsOf([thought(9)], [call(0)]))).toEqual(['activity', '?9'])
  })

  it('renders nothing for a turn with neither', () => {
    expect(stepsOf([], [])).toEqual([])
  })
})

describe('thoughtLine', () => {
  it('is the first line, because that is what a reader decides on', () => {
    expect(thoughtLine('Sum the ledger.\nThen check the tax.')).toBe('Sum the ledger.')
  })

  it('skips blank lines rather than summarising as nothing', () => {
    expect(thoughtLine('\n\n  Two customers match.  \nmore\n')).toBe('Two customers match.')
  })

  it('clips a long line, so a summary stays a line', () => {
    const line = thoughtLine('x'.repeat(300))
    expect(line).toHaveLength(96)
    expect(line.endsWith('…')).toBe(true)
  })

  it('says nothing for text that has nothing to say', () => {
    expect(thoughtLine('   \n\n')).toBe('')
  })
})

describe('thoughtOpen', () => {
  it('keeps every thought closed until the operator asks', () => {
    // Live or from history, the row is the same one-line record. The pulse says the step is
    // running; it does not open a body.
    expect(thoughtOpen({ choice: null })).toBe(false)
  })

  it('opens on the operator’s yes', () => {
    expect(thoughtOpen({ choice: true })).toBe(true)
  })

  it('closes on the operator’s no', () => {
    expect(thoughtOpen({ choice: false })).toBe(false)
  })
})

describe('thoughtControl', () => {
  it('offers to open a thought that is showing only its line', () => {
    expect(thoughtControl({ open: false })).toEqual({ label: 'read it', choice: true })
  })

  it('offers to close a body that is showing, whole or not', () => {
    // There is no "read it all" any more: the body has always been the whole text, scrolled
    // rather than clipped, so opening it has no cap to lift (`Thought.tsx`).
    expect(thoughtControl({ open: true })).toEqual({ label: 'hide', choice: false })
  })

  it('never labels a press with a state it would not produce', () => {
    // The one invariant that matters: "hide" must close and "read it" must open.
    for (const open of [true, false]) {
      const { label, choice } = thoughtControl({ open })
      if (label === 'hide') expect(choice).toBe(false)
      else expect(choice).toBe(true)
    }
  })
})
