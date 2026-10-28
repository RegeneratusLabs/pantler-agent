// @vitest-environment jsdom
/**
 * The learning line, as it reads under a conversation.
 *
 * Two things are load-bearing here and both are easy to lose: the label is the sentence (it must
 * not shrink or wrap), and the detail the operator opens aligns with that label rather than with
 * the mark. The costume is checked too, because the mark is the one piece of brand artwork in an
 * otherwise typographic row.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import type { LearningLedgerEntry } from '@shared/wire'
import { LearningStrip } from './LearningStrip'

afterEach(cleanup)

const row = (over: Partial<LearningLedgerEntry> = {}): LearningLedgerEntry => ({
  id: 'row-1',
  at: 1792623051,
  actor: 'curator',
  action: 'patch',
  skill: 'producer-sourcing',
  session: 'web-1',
  file: null,
  files: [],
  ...over
})

const strip = (rows: LearningLedgerEntry[]) =>
  render(
    <MemoryRouter>
      <LearningStrip rows={rows} />
    </MemoryRouter>
  )

describe('LearningStrip', () => {
  it('leads the line with the monocled mark', () => {
    const { container } = strip([row()])
    expect(container.querySelector('[data-outfit="monocle"]')).not.toBeNull()
    expect(screen.getByText('Learned from this conversation')).toBeTruthy()
  })

  it('is absent when the ledger has nothing for this conversation', () => {
    const { container } = strip([])
    expect(container.firstChild).toBeNull()
  })

  it('opens the detail with the words the ledger supports', () => {
    strip([row()])
    fireEvent.click(screen.getByRole('button', { name: 'what changed' }))
    expect(screen.getByText(/producer-sourcing/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /Everything it has learned/ })).toBeTruthy()
  })

  it('keeps the label whole and lets the skills list give way', () => {
    strip([row()])
    const label = screen.getByText('Learned from this conversation')
    expect(label.className).toContain('shrink-0')
    expect(label.className).toContain('whitespace-nowrap')
  })
})
