/**
 * Reading a learning moment off a tool call.
 *
 * The cases here are the engine's real payloads, captured from this machine: a `memory` call
 * that saved a delivery day, a `skill_manage` batch that created a skill and was refused once
 * for a description that was too long. Three rules are what these tests defend:
 *
 *   1. **Only a write counts.** `skill_view` and `skills_list` read; a card for them would
 *      claim the assistant changed something when it only looked.
 *   2. **A refusal is never a success.** The engine answers `{"success": false, "error": …}`,
 *      and the card has to say the write did not happen (invariant 3).
 *   3. **Nothing prints its JSON.** The envelope is read, the sentence is written.
 */

import { describe, expect, it } from 'vitest'
import type { ToolCall } from '../seam/reducer'
import { isLearningTool, learningKind, learningLine, learningMoment, learningMoments } from './learning'

function call(patch: Partial<ToolCall> & { tool: string }): ToolCall {
  return { key: `${patch.tool}#0`, seq: 0, status: 'ok', startedAt: 0, ...patch }
}

/** A transcript result: the envelope wrapped the way the engine persists it. */
function persisted(envelope: unknown): string {
  return `<untrusted_tool_result source="memory">\n${JSON.stringify(envelope)}\n</untrusted_tool_result>`
}

const MEMORY_ARGS = JSON.stringify({
  action: 'add',
  content: 'Bellview CSA delivery day is Tuesday.',
  target: 'memory'
})

const MEMORY_RESULT = {
  success: true,
  done: true,
  target: 'memory',
  usage: '1% — 37/2,200 chars',
  entry_count: 1,
  message: 'Entry added.'
}

const SKILL_ARGS = JSON.stringify({
  operations: [
    {
      action: 'create',
      category: 'social-media',
      name: 'social-carousel',
      content: '---\nname: social-carousel\n---\n'
    }
  ]
})

const SKILL_RESULT = {
  success: true,
  operations_applied: 1,
  results: [{ name: 'social-carousel', action: 'create', success: true, lint_warnings: [] }]
}

describe('what counts as learning', () => {
  it('counts the two tools that write', () => {
    expect(learningKind('memory')).toBe('memory')
    expect(learningKind('skill_manage')).toBe('skill')
    expect(isLearningTool('memory')).toBe(true)
  })

  it('does not count reading a skill as learning anything', () => {
    // The one that matters: these run constantly and change nothing.
    expect(learningMoment(call({ tool: 'skill_view', args: '{"name":"invoicing"}' }))).toBeNull()
    expect(learningMoment(call({ tool: 'skills_list', args: '{}' }))).toBeNull()
    expect(learningMoment(call({ tool: 'web_search', argsPreview: 'organic farms' }))).toBeNull()
  })
})

describe('a memory write', () => {
  it('reads the remembered text out of the arguments, not the clipped preview', () => {
    const moment = learningMoment(
      call({
        tool: 'memory',
        args: MEMORY_ARGS,
        argsPreview: '+memory: "Bellview CSA delivery day..."',
        result: JSON.stringify(MEMORY_RESULT)
      })
    )!

    expect(moment.kind).toBe('memory')
    expect(moment.status).toBe('ok')
    expect(moment.changes).toHaveLength(1)
    expect(moment.changes[0].label).toBe('Remembered')
    expect(moment.changes[0].subject).toBe('Bellview CSA delivery day is Tuesday.')
    expect(moment.note).toBe('1% — 37/2,200 chars')
  })

  it('falls back to the engine’s own preview when the arguments are not on hand', () => {
    // A live call has no arguments — only the display preview, clipped to 25 characters. A
    // clipped quotation is still better than nothing, and the ellipsis shows the clip.
    const moment = learningMoment(
      call({ tool: 'memory', argsPreview: '+memory: "Bellview CSA delivery day..."', status: 'running' })
    )!

    expect(moment.status).toBe('running')
    expect(moment.changes[0].subject).toBe('Bellview CSA delivery day...')
    expect(moment.changes[0].label).toBe('Remembered')
  })

  it('says a removal was a removal', () => {
    const moment = learningMoment(
      call({
        tool: 'memory',
        args: JSON.stringify({ action: 'remove', old_text: 'delivers Tuesdays', target: 'memory' }),
        result: JSON.stringify({ success: true, target: 'memory' })
      })
    )!
    expect(moment.changes[0].label).toBe('Forgot')
    expect(moment.changes[0].subject).toBe('delivers Tuesdays')
  })

  it('reads a raised-cap replace as a change, not a new fact', () => {
    const moment = learningMoment(
      call({
        tool: 'memory',
        args: JSON.stringify({ action: 'replace', old_text: 'Tuesday', content: 'Wednesday', target: 'memory' })
      })
    )!
    expect(moment.changes[0].label).toBe('Changed what it remembers')
    expect(moment.changes[0].subject).toBe('Wednesday')
  })

  it('prints an action it has no phrase for rather than guessing what it meant', () => {
    const moment = learningMoment(
      call({ tool: 'memory', args: JSON.stringify({ action: 'merge', content: 'x', target: 'memory' }) })
    )!
    expect(moment.changes[0].label).toBe('Merge')
  })
})

describe('a skill write', () => {
  it('names the skill and what it did to it', () => {
    const moment = learningMoment(
      call({
        tool: 'skill_manage',
        args: SKILL_ARGS,
        result: persisted(SKILL_RESULT)
      })
    )!

    expect(moment.kind).toBe('skill')
    expect(moment.changes[0].label).toBe('Wrote itself a new skill')
    expect(moment.changes[0].subject).toBe('social-carousel')
  })

  it('reads every operation in a batch, in order', () => {
    const moment = learningMoment(
      call({
        tool: 'skill_manage',
        args: JSON.stringify({
          operations: [
            { action: 'patch', name: 'invoicing', old_string: 'a', new_string: 'b' },
            { action: 'write_file', name: 'invoicing', file_path: 'references/rates.md' }
          ]
        }),
        result: JSON.stringify({
          success: true,
          operations_applied: 2,
          results: [
            { name: 'invoicing', action: 'patch', success: true },
            { name: 'invoicing', action: 'write_file', success: true }
          ]
        })
      })
    )!

    expect(moment.changes.map(change => change.label)).toEqual([
      'Rewrote part of a skill',
      'Added a file to a skill'
    ])
    expect(moment.changes[1].detail).toBe('references/rates.md')
  })

  it('says nothing about the skill while the call is still running with no arguments', () => {
    // The engine sends no preview at all for this tool — its primary argument is not one the
    // batch schema uses — so the honest card is the one that claims least.
    const moment = learningMoment(call({ tool: 'skill_manage', status: 'running' }))!

    expect(moment.status).toBe('running')
    expect(moment.changes[0].subject).toBeUndefined()
  })

  it('takes the name from the result when the arguments did not carry one', () => {
    const moment = learningMoment(
      call({ tool: 'skill_manage', status: 'running', result: JSON.stringify(SKILL_RESULT) })
    )!
    expect(moment.changes[0].subject).toBe('social-carousel')
  })
})

describe('a write that did not happen', () => {
  it('shows the engine’s refusal rather than a success', () => {
    // Captured from this machine: a description over the 60-character budget.
    const moment = learningMoment(
      call({
        tool: 'skill_manage',
        status: 'error',
        args: SKILL_ARGS,
        result: JSON.stringify({
          success: false,
          error: "operations[0] (create on 'social-carousel') failed: Description is 112 chars",
          failed_index: 0
        })
      })
    )!

    expect(moment.status).toBe('failed')
    expect(moment.error).toContain('Description is 112 chars')
  })

  it('reads a refusal from a resumed transcript, which carries no error flag', () => {
    // A `tool` message has the result and nothing else, so `success: false` is the only signal.
    const moment = learningMoment(
      call({
        tool: 'memory',
        args: MEMORY_ARGS,
        result: persisted({ success: false, error: 'Memory is full' })
      })
    )!

    expect(moment.status).toBe('failed')
    expect(moment.error).toBe('Memory is full')
  })

  it('calls a stalled write stalled rather than saved', () => {
    const moment = learningMoment(
      call({
        tool: 'memory',
        args: MEMORY_ARGS,
        result: JSON.stringify({ success: true, staged: true, pending_id: 'abc12345' })
      })
    )!

    expect(moment.status).toBe('ok')
    expect(moment.note).toBe('waiting for your approval')
  })

  it('reports a per-operation failure inside a successful batch', () => {
    const moment = learningMoment(
      call({
        tool: 'skill_manage',
        args: SKILL_ARGS,
        result: JSON.stringify({
          success: true,
          operations_applied: 1,
          results: [{ name: 'social-carousel', action: 'create', success: false, error: 'already exists' }]
        })
      })
    )!
    expect(moment.changes[0].label).toBe('Could not change a skill')
    expect(moment.changes[0].detail).toBe('already exists')
  })

  it('has nothing to say about an envelope it cannot read, and does not throw', () => {
    const moment = learningMoment(call({ tool: 'memory', status: 'running', result: '{"success": tru' }))
    expect(moment?.status).toBe('running')
    expect(moment?.note).toBeUndefined()
  })
})

describe('the roll-up', () => {
  it('names what happened, in the order it happened', () => {
    const moments = learningMoments([
      call({ tool: 'memory', key: 'a', args: MEMORY_ARGS, result: JSON.stringify(MEMORY_RESULT) }),
      call({ tool: 'skill_manage', key: 'b', args: SKILL_ARGS, result: JSON.stringify(SKILL_RESULT) })
    ])
    expect(learningLine(moments)).toBe('Remembered · Wrote itself a new skill')
  })

  it('counts a repeated verb instead of listing it', () => {
    const same = (key: string) =>
      call({ tool: 'memory', key, args: MEMORY_ARGS, result: JSON.stringify(MEMORY_RESULT) })
    expect(learningLine(learningMoments([same('a'), same('b'), same('c')]))).toBe('Remembered ×3')
  })

  it('never folds a failure into a count', () => {
    const moments = learningMoments([
      call({ tool: 'memory', key: 'a', args: MEMORY_ARGS, result: JSON.stringify(MEMORY_RESULT) }),
      call({ tool: 'memory', key: 'b', args: MEMORY_ARGS, status: 'error', result: JSON.stringify({ success: false, error: 'no' }) })
    ])
    expect(learningLine(moments)).toBe('Something it tried to write down did not go through.')
  })

  it('does not claim a running call has happened yet', () => {
    const moments = learningMoments([call({ tool: 'memory', argsPreview: '+memory: "x"', status: 'running' })])
    expect(learningLine(moments)).toBe('Writing down what it learned…')
  })

  it('has no line at all when the turn learned nothing', () => {
    expect(learningLine(learningMoments([call({ tool: 'web_search' })]))).toBeUndefined()
  })
})
