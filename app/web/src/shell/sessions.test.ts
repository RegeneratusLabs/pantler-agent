import type { SessionSummary } from '@shared/wire'
import { describe, expect, it } from 'vitest'
import { SeamError, SeamUnreachable } from '../seam/client'
import {
  describeDeleteFailure,
  describeWriteFailure,
  filterSessions,
  groupSessions,
  lastActive,
  sessionLabel,
  sessionSubtitle,
  shortAge,
  shortId,
  startOfDay,
  toMillis
} from './sessions'

const session = (over: Partial<SessionSummary> & { id: string }): SessionSummary => ({
  started_at: 0,
  ...over
})

const DAY = 86_400_000

describe('groupSessions', () => {
  // Noon, so "today" is unambiguous wherever the test runs.
  const now = new Date(2026, 5, 15, 12, 0, 0).getTime()
  const today = startOfDay(now)

  it('buckets by recency, newest first inside each bucket', () => {
    const groups = groupSessions(
      [
        session({ id: 'a', last_active: today - 3 * DAY }),
        session({ id: 'b', last_active: today + 1000 }),
        session({ id: 'c', last_active: today - DAY }),
        session({ id: 'd', last_active: today - 20 * DAY }),
        session({ id: 'e', last_active: today - 100 * DAY }),
        session({ id: 'f', last_active: today - 2 * DAY })
      ],
      now
    )

    expect(groups.map(g => g.key)).toEqual(['today', 'yesterday', 'week', 'month', 'older'])
    expect(groups.find(g => g.key === 'week')?.sessions.map(s => s.id)).toEqual(['f', 'a'])
    expect(groups.find(g => g.key === 'today')?.sessions.map(s => s.id)).toEqual(['b'])
    expect(groups.find(g => g.key === 'yesterday')?.sessions.map(s => s.id)).toEqual(['c'])
  })

  it('lifts pinned sessions above today, even when they are old', () => {
    const groups = groupSessions(
      [
        session({ id: 'new', last_active: today + 1000 }),
        session({ id: 'pinned', last_active: today - 200 * DAY, pinned: true })
      ],
      now
    )
    expect(groups[0].key).toBe('pinned')
    expect(groups[0].sessions.map(s => s.id)).toEqual(['pinned'])
  })

  it('omits empty buckets rather than rendering dead headings', () => {
    const groups = groupSessions([session({ id: 'only', last_active: today + 1 })], now)
    expect(groups).toHaveLength(1)
    expect(groups[0].key).toBe('today')
  })

  it('falls back to started_at when the engine sends no last_active', () => {
    const groups = groupSessions([session({ id: 'x', started_at: today + 1 })], now)
    expect(groups[0].key).toBe('today')
  })

  it('survives a session with no timestamps at all', () => {
    const groups = groupSessions([session({ id: 'x' })], now)
    expect(groups[0].key).toBe('older')
  })
})

describe('filterSessions', () => {
  const items = [
    session({ id: 'web-abc', title: 'Invoice Bellview CSA' }),
    session({ id: 'web-def', title: 'Chase unpaid invoices', preview: 'Bellview still owes' }),
    session({ id: 'web-ghi' })
  ]

  it('returns everything for an empty query', () => {
    expect(filterSessions(items, '   ')).toHaveLength(3)
  })

  it('matches the title, case-insensitively', () => {
    expect(filterSessions(items, 'bellview').map(s => s.id)).toEqual(['web-abc', 'web-def'])
  })

  it('matches the preview when the title does not', () => {
    expect(filterSessions(items, 'still owes').map(s => s.id)).toEqual(['web-def'])
  })

  it('matches an id, because an id is how a person quotes one', () => {
    expect(filterSessions(items, 'ghi').map(s => s.id)).toEqual(['web-ghi'])
  })

  it('returns nothing rather than everything when nothing matches', () => {
    expect(filterSessions(items, 'zzz')).toEqual([])
  })
})

describe('labels', () => {
  it('prefers the title, then the preview, then a placeholder', () => {
    expect(sessionLabel(session({ id: 'a', title: 'Named' }))).toBe('Named')
    expect(sessionLabel(session({ id: 'a', preview: 'First words' }))).toBe('First words')
    expect(sessionLabel(session({ id: 'a', title: '   ' }))).toBe('Untitled session')
  })

  it('does not repeat the preview when it is already the title', () => {
    expect(sessionSubtitle(session({ id: 'a', title: 'Same', preview: 'Same' }))).toBeNull()
    expect(sessionSubtitle(session({ id: 'a', title: 'Title', preview: 'Preview' }))).toBe('Preview')
    expect(sessionSubtitle(session({ id: 'a', preview: 'Preview' }))).toBeNull()
  })

  it('treats last_active as the sort key, falling back to started_at', () => {
    expect(lastActive(session({ id: 'a', last_active: 1_781_000_000_000, started_at: 1 }))).toBe(
      1_781_000_000_000
    )
    expect(lastActive(session({ id: 'a', started_at: 1_781_000_000_000 }))).toBe(1_781_000_000_000)
    expect(lastActive(session({ id: 'a' }))).toBe(0)
  })
})

describe('toMillis', () => {
  it('converts the engine’s epoch seconds to milliseconds', () => {
    // The shape the engine actually sends: 1791612881.9544098
    expect(toMillis(1_791_612_881.95)).toBe(1_791_612_881_950)
  })

  it('leaves a millisecond timestamp alone', () => {
    expect(toMillis(1_791_612_881_950)).toBe(1_791_612_881_950)
  })

  it('treats zero and nonsense as "no timestamp"', () => {
    expect(toMillis(0)).toBe(0)
    expect(toMillis(-5)).toBe(0)
    expect(toMillis(Number.NaN)).toBe(0)
  })

  it('makes a real engine timestamp land in this decade, not 1970', () => {
    const grouped = groupSessions(
      [session({ id: 'web-1', last_active: 1_791_612_927.9 })],
      Date.now()
    )
    expect(grouped[0].key).not.toBe('older')
  })
})

describe('shortAge', () => {
  const now = 1_000_000_000_000

  it('reads as a compact age', () => {
    expect(shortAge(now - 30_000, now)).toBe('just now')
    expect(shortAge(now - 5 * 60_000, now)).toBe('5m')
    expect(shortAge(now - 3 * 3_600_000, now)).toBe('3h')
    expect(shortAge(now - 2 * 86_400_000, now)).toBe('2d')
  })

  it('falls back to a date past a week', () => {
    expect(shortAge(now - 40 * 86_400_000, now)).toMatch(/\d/)
  })

  it('is empty for a session with no timestamp, rather than "just now"', () => {
    expect(shortAge(0, now)).toBe('')
  })
})

describe('shortId', () => {
  it('keeps short ids intact and elides long ones', () => {
    expect(shortId('web-abc')).toBe('web-abc')
    const long = 'web-b6637f493041aa'
    expect(shortId(long)).toBe(`…${long.slice(-12)}`)
  })
})

describe('describeDeleteFailure', () => {
  // The engine's real refusal, byte for byte: _error_response(..., 409,
  // code="session_active_turn") out of _handle_delete_session.
  const activeTurn = new SeamError(
    "session 'web-5ead85b6205f' (or a delegate child) has an active turn lease or compression lock",
    409,
    'session_active_turn'
  )

  it('explains a mid-turn refusal and how to get past it, not the engine’s lease vocabulary', () => {
    const message = describeDeleteFailure(activeTurn, 'Assess soil test')
    expect(message).toContain('“Assess soil test” is mid-turn')
    expect(message).toContain('Stop the run in the transcript, or wait for it to finish')
    expect(message).not.toContain('lease')
  })

  it('treats a bare 409 as the same refusal', () => {
    expect(describeDeleteFailure(new SeamError('nope', 409), 'x')).toContain('is mid-turn')
  })

  it('names the engine as the reason the engine is not the one asking', () => {
    expect(describeDeleteFailure(new SeamUnreachable('down'), 'Assess soil test')).toBe(
      'The engine is not answering, so “Assess soil test” was not deleted.'
    )
  })

  it('passes an unexplained refusal through verbatim', () => {
    expect(describeDeleteFailure(new SeamError('title is taken', 400), 'Beans')).toBe(
      '“Beans” was not deleted. The engine said: title is taken'
    )
  })

  it('never renders an empty sentence when the failure is not an Error at all', () => {
    expect(describeDeleteFailure(undefined, 'Beans')).toBe('“Beans” was not deleted.')
  })
})

describe('describeWriteFailure', () => {
  it('says which write failed, in the engine’s words', () => {
    expect(describeWriteFailure(new SeamError('that title exists', 400), 'rename “Beans”')).toBe(
      'Could not rename “Beans” — the engine said: that title exists'
    )
  })

  it('falls back when the engine offered no sentence', () => {
    expect(describeWriteFailure(new Error(''), 'pin “Beans”')).toBe('Could not pin “Beans”.')
    expect(describeWriteFailure(new SeamUnreachable('down'), 'pin “Beans”')).toBe(
      'The engine is not answering, so pin “Beans” failed.'
    )
  })
})
