// @vitest-environment jsdom
/**
 * The two rows that show the assistant working — a step's thinking and a run of tool calls —
 * and the rules a live turn is judged by.
 *
 * Thinking is closed until the operator asks. The live step is marked by its pulse and the word
 * `Think`, not by an auto-opened body; a body the operator did open stays open when the step
 * lands. The tool tests are markup, because the ticker's whole job is the shape of the DOM — a
 * summary line and one reel rather than a list that folds at the fourth call.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Thought, ToolCall } from '../seam/reducer'
import { ActivityGroup } from './Activity'
import { ThoughtRow } from './Thought'

afterEach(cleanup)

function call(patch: Partial<ToolCall> & { tool: string }): ToolCall {
  return { key: `${patch.tool}#0`, seq: 0, status: 'ok', startedAt: 0, ...patch }
}

const THOUGHT = [
  'First line of the thought.',
  'A middle line the reader would have to scroll to.',
  'The end — the decision the step acts on.'
].join('\n')

const thought = (status: Thought['status']): Thought => ({
  key: 'hist-thought-1',
  text: THOUGHT,
  status,
  seq: 0
})

describe('ThoughtRow', () => {
  it('keeps a live step to one line until the operator asks', () => {
    const { container } = render(<ThoughtRow thought={thought('streaming')} />)
    const html = container.innerHTML

    expect(html).toContain('Think')
    expect(html).toContain('First line of the thought.')
    expect(html).toContain('read it')
    expect(html).not.toContain('The end — the decision the step acts on.')
    expect(html).not.toContain('thought-scroll')
    expect(html).not.toContain('hide')
  })

  it('opens the whole thought when the operator asks', () => {
    const { container } = render(<ThoughtRow thought={thought('streaming')} />)
    fireEvent.click(screen.getByRole('button', { name: 'read it' }))

    expect(container.innerHTML).toContain('The end — the decision the step acts on.')
    expect(container.innerHTML).toContain('thought-scroll')
    expect(container.innerHTML).toContain('hide')
  })

  it('keeps an opened body when the step lands under the reader', () => {
    // The exact sequence a poll produces: the same row, one status later. The operator opened
    // this body; the step ending is not a reason to close it.
    const { container, rerender } = render(<ThoughtRow thought={thought('streaming')} />)
    fireEvent.click(screen.getByRole('button', { name: 'read it' }))
    rerender(<ThoughtRow thought={thought('settled')} />)

    expect(container.innerHTML).toContain('The end — the decision the step acts on.')
    expect(container.innerHTML).toContain('hide')
    expect(container.innerHTML).not.toContain('read it')
  })

  it('closes again on hide', () => {
    const { container } = render(<ThoughtRow thought={thought('streaming')} />)
    fireEvent.click(screen.getByRole('button', { name: 'read it' }))
    fireEvent.click(screen.getByRole('button', { name: 'hide' }))

    expect(container.innerHTML).not.toContain('The end — the decision the step acts on.')
    expect(container.innerHTML).toContain('read it')
  })

  it('leaves a thought from history closed, with its first line as the summary', () => {
    const { container } = render(<ThoughtRow thought={thought('settled')} />)
    const html = container.innerHTML

    expect(html).toContain('First line of the thought.')
    expect(html).not.toContain('The end — the decision the step acts on.')
    expect(html).not.toContain('thought-scroll')
    expect(html).toContain('read it')
  })
})

describe('ActivityGroup', () => {
  it('ticks a live run over one line instead of growing it', () => {
    const calls = [
      call({ tool: 'web_search', key: 'a', seq: 0 }),
      call({ tool: 'web_search', key: 'b', seq: 1 }),
      call({ tool: 'read_file', key: 'c', seq: 2 }),
      call({ tool: 'web_search', key: 'd', seq: 3, status: 'running', argsPreview: 'soil tests' })
    ]
    const { container } = render(<ActivityGroup calls={calls} live />)
    const html = container.innerHTML

    expect(html).toContain('activity-ticker')
    // ×2, not ×3: the search still running is the ticker's line, not part of the count.
    expect(html).toContain('Searched the web ×2 · Read a file')
    expect(html).toContain('Searching the web for “soil tests”…')
    // Live is a ticker, never a fold: the label that folds a settled run must not appear.
    expect(html).not.toContain('4 steps ·')
  })

  it('keeps a failure on its own row even while the run ticks', () => {
    const refused = JSON.stringify({ error: 'Refusing to overwrite /x/brief.md' })
    const calls = [
      call({ tool: 'web_search', key: 'a', seq: 0 }),
      call({ tool: 'write_file', key: 'b', seq: 1, result: refused }),
      call({ tool: 'read_file', key: 'c', seq: 2, status: 'running' })
    ]
    const { container } = render(<ActivityGroup calls={calls} live />)
    const html = container.innerHTML

    expect(html).toContain('Couldn’t write that file')
    // The disclosure label only ever comes from a row, not from the summary.
    expect(html).toContain('what happened')
    expect(html).toContain('activity-ticker')
  })

  it('folds a settled run to one line, with the rows a click away', () => {
    const calls = [
      call({ tool: 'web_search', key: 'a', seq: 0 }),
      call({ tool: 'web_search', key: 'b', seq: 1 }),
      call({ tool: 'web_search', key: 'c', seq: 2 }),
      call({ tool: 'terminal', key: 'd', seq: 3 }),
      call({ tool: 'read_file', key: 'e', seq: 4 })
    ]
    const { container } = render(<ActivityGroup calls={calls} />)
    const html = container.innerHTML

    expect(html).toContain('5 steps · Searched the web ×3 · Ran a command · Read a file')
    expect(html).toContain('show all 5')
    expect(html).not.toContain('activity-ticker')
    // Each phrase appears exactly once — in the summary. A row would be a second.
    expect(html.match(/Ran a command/g)).toHaveLength(1)
  })

  it('never gives a call in flight a row of its own in a settled run', () => {
    // Parallel calls: a card ended this run while four of them were still answering. Each was
    // printed as a row and each vanished as its call completed — 104 pixels gone in one frame,
    // measured on a live turn. The line says what has finished and never claims the rest.
    const inFlight = [
      call({ tool: 'web_search', key: 'a', seq: 0 }),
      call({ tool: 'web_search', key: 'b', seq: 1 }),
      call({ tool: 'read_file', key: 'c', seq: 2 }),
      call({ tool: 'terminal', key: 'd', seq: 3, status: 'running' })
    ]
    const running = render(<ActivityGroup calls={inFlight} />).container.innerHTML

    expect(running).toContain('4 steps · Searched the web ×2 · Read a file')
    expect(running).not.toContain('Running a command')
    expect(running).not.toContain('activity-ticker')

    // And when it answers, only the line's words change — no row appears or disappears.
    const answered = [
      ...inFlight.slice(0, 3),
      call({ tool: 'terminal', key: 'd', seq: 3 })
    ]
    const settled = render(<ActivityGroup calls={answered} />).container.innerHTML

    expect(settled).toContain('4 steps · Searched the web ×2 · Ran a command · Read a file')
    expect(settled).not.toContain('Running a command')
  })

  it('leaves a short settled run as rows, with nothing to fold', () => {
    const calls = [
      call({ tool: 'web_search', key: 'a', seq: 0 }),
      call({ tool: 'read_file', key: 'b', seq: 1 })
    ]
    const { container } = render(<ActivityGroup calls={calls} />)
    const html = container.innerHTML

    expect(html).toContain('Searched the web')
    expect(html).toContain('Read a file')
    expect(html).not.toContain('steps ·')
    expect(html).not.toContain('activity-ticker')
  })
})
