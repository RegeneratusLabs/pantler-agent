/**
 * What the cards draw, from their props.
 *
 * There is no DOM here (the internal audit WEB-16), so these render with
 * `react-dom/server`: no effects, no events, just the markup a person would see. That is exactly
 * what the approval card's states are — the audit's WEB-3 was a card whose buttons were disabled
 * with nothing able to re-enable them, and the difference between the states is markup.
 */

import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApprovalCard, ToolCard } from './cards'
import type { ApprovalRequest } from '../seam/reducer'

const approval = (fields: Partial<ApprovalRequest> = {}): ApprovalRequest =>
  ({
    key: 'req-1',
    requestId: 'req-1',
    executionGeneration: null,
    kind: 'tool',
    description: 'Record the spray',
    choices: ['once', 'session', 'deny'],
    ...fields
  }) as ApprovalRequest

const draw = (fields: Partial<ApprovalRequest> = {}) =>
  renderToStaticMarkup(
    <ApprovalCard approval={approval(fields)} intent="Recording it now." onAnswer={async () => true} />
  )

describe('ApprovalCard', () => {
  it('offers the choices while the question is open', () => {
    const html = draw()
    expect(html).toContain('May I do this?')
    expect(html).toContain('waiting on you')
    // Both prominent choices are drawn, and neither is disabled: React renders a boolean
    // attribute as `disabled=""`, which is what to look for (Tailwind's `disabled:` classes are
    // not the button's state).
    expect(html).toContain('Do it once')
    expect(html).toContain('No, don’t do it')
    expect(html).not.toContain('disabled=""')
  })

  it('says the run moved on, and offers nothing to click, once it has expired', () => {
    // An unanswered approval whose run has ended can never be answered: showing buttons would be
    // a lie and blocking the composer would be worse (the internal audit WEB-2).
    const html = draw({ expired: true })
    expect(html).toContain('not answered in time')
    expect(html).toContain('Nothing happened')
    expect(html).not.toMatch(/<button/)
  })

  it('records a decision that was already made', () => {
    const html = draw({
      resolution: { choice: 'deny', requestId: 'req-1', resolvedAt: 1 } as never
    })
    expect(html).toContain('You said no')
    expect(html).not.toMatch(/<button/)
  })

  it('says what it will do, in the operator’s words', () => {
    expect(draw()).toContain('Recording it now.')
  })
})


describe('Capture card', () => {
  const result = JSON.stringify({
    success: true,
    id: 'CAP-0001',
    type: 'capture',
    record: {
      text: 'I sprayed the tomatoes in block B today',
      status: 'captured',
      occurred_on: '2026-10-30',
      source: 'chat'
    }
  })
  const call = {
    key: 'call-1',
    seq: 0,
    tool: 'capture_save',
    result,
    status: 'ok' as const,
    startedAt: 1
  }

  it('shows the operator words and the capture id', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ToolCard call={call} />
      </MemoryRouter>
    )
    expect(html).toContain('CAP-0001')
    expect(html).toContain('I sprayed the tomatoes in block B today')
    expect(html).toContain('Open in paper trail')
    expect(html).toContain('/records?type=capture&amp;id=CAP-0001')
  })
})
