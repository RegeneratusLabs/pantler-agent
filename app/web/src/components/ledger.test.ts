/**
 * Reading the engine's ledger for one conversation.
 *
 * The rows here are the real thing, copied out of `skills/.curator_ledger.jsonl` on this machine:
 * the session that produced nine writes across two skills — four passes at `pdf` and five at
 * `producer-sourcing`, all of them the curator's, on its own thread, after the turn had finished.
 * That session is the case this module exists for. The strip used to render it as
 *
 *     This conversation changed its own notes: pdf, producer-sourcing 9 times — last 09:27 PM.
 *
 * which names a file count as if it were an event count, attributes the change to the conversation
 * rather than to the assistant, and calls a skill a note. Four rules are what these tests defend:
 *
 *   1. **One line per skill, not per write.** Nine passes at a file is one fact about two skills.
 *   2. **A roll-up says less, never something else.** "wrote a new skill" is only ever said about a
 *      skill with a `create` row behind it.
 *   3. **Newest first.** A skill touched again today belongs above one left alone yesterday, even
 *      if it appeared in the ledger first.
 *   4. **A time alone is only said about today.** "last 09:27 PM" is a small lie the morning after.
 */

import { describe, expect, it } from 'vitest'
import type { LearningLedgerEntry } from '@shared/wire'
import { actorLabel, changeStamp, describeAction, ledgerSummary } from './ledger'

let counter = 0

function row(
  patch: Partial<LearningLedgerEntry> & { action: string; skill: string }
): LearningLedgerEntry {
  counter += 1
  return {
    id: `row-${counter}`,
    at: null,
    actor: 'curator',
    session: 'web-baafc8983237',
    ...patch
  }
}

/** Epoch *seconds*, which is the engine's unit, built from a local wall clock. */
function at(year: number, month: number, day: number, hour: number, minute: number, second = 0) {
  return new Date(year, month - 1, day, hour, minute, second).getTime() / 1000
}

/** The same instant, formatted by the platform — the decision under test is ours, the words are not. */
function clock(...when: [number, number, number, number, number, number?]): string {
  return new Date(
    when[0],
    when[1] - 1,
    when[2],
    when[3],
    when[4],
    when[5] ?? 0
  ).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

const PDF = { skill: 'pdf', actor: 'curator' }
const SOURCING = { skill: 'producer-sourcing', actor: 'curator' }

/** The real session: four passes at `pdf`, then five at `producer-sourcing`. */
const NINE_WRITES: LearningLedgerEntry[] = [
  row({ ...PDF, action: 'patch', at: at(2026, 10, 13, 21, 26, 14) }),
  row({ ...PDF, action: 'patch', at: at(2026, 10, 13, 21, 26, 14) }),
  row({ ...PDF, action: 'patch', at: at(2026, 10, 13, 21, 26, 14) }),
  row({ ...PDF, action: 'write_file', at: at(2026, 10, 13, 21, 26, 15) }),
  row({ ...SOURCING, action: 'create', at: at(2026, 10, 13, 21, 26, 49) }),
  row({ ...SOURCING, action: 'write_file', at: at(2026, 10, 13, 21, 26, 49) }),
  row({ ...SOURCING, action: 'patch', at: at(2026, 10, 13, 21, 27, 4) }),
  row({ ...SOURCING, action: 'patch', at: at(2026, 10, 13, 21, 27, 4) }),
  row({ ...SOURCING, action: 'patch', at: at(2026, 10, 13, 21, 27, 5) })
]

const THAT_EVENING = new Date(2026, 9, 13, 22, 0)
const TWO_DAYS_LATER = new Date(2026, 9, 15, 9, 0)

describe('rolling the ledger up', () => {
  it('says one thing per skill, not one per write', () => {
    const summary = ledgerSummary(NINE_WRITES, THAT_EVENING)

    expect(summary.changes).toHaveLength(2)
    expect(summary.skills).toEqual(['producer-sourcing', 'pdf'])
    expect(summary.more).toBe(0)
  })

  it('says what the session did to each skill, not what it last did', () => {
    // `producer-sourcing` ends on three patches; the fact worth keeping is that it did not exist
    // before this conversation. `pdf` ends on a file write, which outranks the patches under it.
    const summary = ledgerSummary(NINE_WRITES, THAT_EVENING)

    expect(summary.changes).toEqual([
      { skill: 'producer-sourcing', action: 'wrote a new skill', who: 'while tidying up' },
      { skill: 'pdf', action: 'added a file to', who: 'while tidying up' }
    ])
  })

  it('leads with the skill changed most recently, wherever it sat in the ledger', () => {
    // `pdf` is written first and again last: it is the newest change and goes first, even though
    // `delivery-days` was the last *skill* to appear for the first time.
    const rows = [
      row({ skill: 'pdf', action: 'patch', at: at(2026, 10, 13, 9, 0) }),
      row({ skill: 'delivery-days', action: 'create', at: at(2026, 10, 13, 10, 0) }),
      row({ skill: 'pdf', action: 'patch', at: at(2026, 10, 13, 11, 0) })
    ]

    expect(ledgerSummary(rows, THAT_EVENING).skills).toEqual(['pdf', 'delivery-days'])
  })

  it('never claims a verb the ledger did not record against that skill', () => {
    // No `create` row for `pdf`, so nothing may say a skill was written — even though the same
    // session created another one. A roll-up says less; it does not borrow.
    const summary = ledgerSummary(
      [row({ skill: 'pdf', action: 'patch' }), row({ ...SOURCING, action: 'create' })],
      THAT_EVENING
    )

    expect(summary.changes).toEqual([
      { skill: 'producer-sourcing', action: 'wrote a new skill', who: 'while tidying up' },
      { skill: 'pdf', action: 'changed', who: 'while tidying up' }
    ])
  })

  it('passes an unfamiliar verb through as the engine wrote it', () => {
    const summary = ledgerSummary([row({ skill: 'pdf', action: 'lint_fix' })], THAT_EVENING)

    expect(summary.changes[0].action).toBe('lint fix')
  })

  it('names three skills and counts the rest', () => {
    const rows = ['a', 'b', 'c', 'd', 'e'].map((skill, index) =>
      row({ skill, action: 'patch', at: at(2026, 10, 13, 9, index) })
    )
    const summary = ledgerSummary(rows, THAT_EVENING)

    expect(summary.skills).toEqual(['e', 'd', 'c'])
    expect(summary.more).toBe(2)
    expect(summary.changes).toHaveLength(5)
  })

  it('ignores a row with no skill to name', () => {
    const rows = [row({ skill: '', action: 'patch' }), row({ skill: 'pdf', action: 'patch' })]

    expect(ledgerSummary(rows, THAT_EVENING).skills).toEqual(['pdf'])
  })

  it('says nothing at all about an empty ledger', () => {
    const summary = ledgerSummary([], THAT_EVENING)

    expect(summary.changes).toEqual([])
    expect(summary.skills).toEqual([])
    expect(summary.stamp).toBe('')
  })
})

describe('saying when', () => {
  it('gives a bare time while it is still the same day', () => {
    expect(changeStamp(at(2026, 10, 13, 21, 27, 5), THAT_EVENING)).toBe(
      `last ${clock(2026, 10, 13, 21, 27, 5)}`
    )
  })

  it('puts the day in front of it once it is not', () => {
    const day = new Date(2026, 9, 13).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short'
    })

    expect(changeStamp(at(2026, 10, 13, 21, 27, 5), TWO_DAYS_LATER)).toBe(
      `last ${day}, ${clock(2026, 10, 13, 21, 27, 5)}`
    )
  })

  it('says nothing when the ledger carried no stamp', () => {
    expect(changeStamp(null, THAT_EVENING)).toBe('')
    expect(changeStamp(0, THAT_EVENING)).toBe('')
  })

  it('reaches back to the newest row that has a stamp', () => {
    const rows = [
      row({ skill: 'pdf', action: 'patch', at: at(2026, 10, 13, 9, 0) }),
      row({ skill: 'delivery-days', action: 'create', at: null })
    ]

    expect(ledgerSummary(rows, THAT_EVENING).stamp).toBe(`last ${clock(2026, 10, 13, 9, 0)}`)
  })
})

describe('the words', () => {
  it('says who made the change without naming the engine', () => {
    expect(actorLabel('agent')).toBe('while working')
    expect(actorLabel('curator')).toBe('while tidying up')
    expect(actorLabel('something-else')).toBe('something-else')
  })

  it('phrases every verb the ledger writes so a skill name can follow it', () => {
    expect(describeAction('create')).toBe('wrote a new skill')
    expect(describeAction('write_file')).toBe('added a file to')
    expect(describeAction('archive')).toBe('archived')
    expect(describeAction('PATCH')).toBe('changed')
  })
})
