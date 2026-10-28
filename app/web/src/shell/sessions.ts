/**
 * Grouping and searching the session rail, and what to say when a rail write is refused.
 *
 * Pure and DOM-free so it can be tested without a browser — the same reason the run
 * reducer is pure. The rail is the one part of the shell that must stay predictable when
 * a business has hundreds of sessions.
 */

import type { SessionSummary } from '@shared/wire'
import { SeamError, SeamUnreachable } from '../seam/client'

export interface SessionGroup {
  key: string
  label: string
  sessions: SessionSummary[]
}

const DAY = 86_400_000

/**
 * The engine timestamps in **epoch seconds** (a float: `1791612881.9544098`), but
 * `Date` and every other API here wants milliseconds. Anything below this threshold is
 * unambiguously seconds — 1e12 ms is the year 2001, 1e12 s is the year 33658 — so the
 * conversion is total and needs no flag from the caller.
 */
const MILLIS_THRESHOLD = 1e12

export function toMillis(timestamp: number): number {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return 0
  return timestamp < MILLIS_THRESHOLD ? timestamp * 1000 : timestamp
}

/** Local midnight for a timestamp, so "Today" means the operator's today. */
export function startOfDay(timestamp: number): number {
  const date = new Date(timestamp)
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

/**
 * What to print for a session. The engine sometimes stores an empty-string title, and a
 * preview is a better label than a raw id when it exists.
 */
export function sessionLabel(session: SessionSummary): string {
  const title = session.title?.trim()
  if (title) return title
  const preview = session.preview?.trim()
  if (preview) return preview
  return 'Untitled session'
}

/** The second line: a preview when the title was used as the first, else nothing. */
export function sessionSubtitle(session: SessionSummary): string | null {
  const title = session.title?.trim()
  const preview = session.preview?.trim()
  if (title && preview && preview !== title) return preview
  return null
}

/** The sort key and age source, always in milliseconds. */
export function lastActive(session: SessionSummary): number {
  return toMillis(session.last_active ?? session.started_at ?? 0)
}

function bucketKey(timestamp: number, today: number): string {
  if (timestamp >= today) return 'today'
  if (timestamp >= today - DAY) return 'yesterday'
  if (timestamp >= today - 7 * DAY) return 'week'
  if (timestamp >= today - 30 * DAY) return 'month'
  return 'older'
}

const LABELS: Record<string, string> = {
  pinned: 'Pinned',
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Previous 7 days',
  month: 'Previous 30 days',
  older: 'Older'
}

const ORDER = ['pinned', 'today', 'yesterday', 'week', 'month', 'older']

/**
 * Newest first within a bucket; pinned lifted into its own bucket at the top. Empty
 * buckets are omitted rather than rendered as dead headings.
 */
export function groupSessions(
  sessions: readonly SessionSummary[],
  now: number = Date.now()
): SessionGroup[] {
  const today = startOfDay(now)
  const buckets = new Map<string, SessionSummary[]>()

  for (const session of sessions) {
    const key = session.pinned ? 'pinned' : bucketKey(lastActive(session), today)
    const bucket = buckets.get(key)
    if (bucket) bucket.push(session)
    else buckets.set(key, [session])
  }

  return ORDER.filter(key => buckets.has(key)).map(key => ({
    key,
    label: LABELS[key] ?? key,
    sessions: (buckets.get(key) ?? []).sort((a, b) => lastActive(b) - lastActive(a))
  }))
}

/** Case-insensitive match over title, preview and id — an id is how a person quotes one. */
export function filterSessions(
  sessions: readonly SessionSummary[],
  query: string
): SessionSummary[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return [...sessions]
  return sessions.filter(session =>
    [session.title, session.preview, session.id]
      .filter((value): value is string => typeof value === 'string')
      .some(value => value.toLowerCase().includes(needle))
  )
}

/** "just now" · "12m" · "3h" · "5d" · a date. Compact, for a narrow rail. */
export function shortAge(timestamp: number, now: number = Date.now()): string {
  if (!timestamp) return ''
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d`
  return new Date(timestamp).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** The engine's session ids are ours (`web-…`); show the tail so two are distinguishable. */
export function shortId(id: string): string {
  return id.length > 14 ? `…${id.slice(-12)}` : id
}

// ------------------------------------------------------------- refused rail writes
//
// Every write the rail makes can be refused, and a refusal used to be invisible: the
// mutation had no error path, so the dialog simply stayed open and the button looked dead.
// These turn the engine's answer into a sentence that says what happened and what to do.
//
// The loudest case is the one an operator actually hits. The engine refuses to delete a
// session while a turn holds its lease (`409 session_active_turn`) because a run is still
// writing to that transcript — deleting underneath it would strand the run. The refusal is
// correct; its own message (“session 'web-…' has an active turn lease or compression lock”)
// is engine vocabulary, not something to hand a person.

/** A live turn — the one refusal that has an obvious remedy, so it gets its own sentence. */
function isActiveTurn(error: unknown): boolean {
  return (
    error instanceof SeamError && (error.code === 'session_active_turn' || error.status === 409)
  )
}

/** Why a session was not deleted, in words an operator can act on. */
export function describeDeleteFailure(error: unknown, label: string): string {
  if (isActiveTurn(error)) {
    return (
      `“${label}” is mid-turn, and the engine will not delete a session while a run is ` +
      'writing to it. Stop the run in the transcript, or wait for it to finish, then ' +
      'delete again.'
    )
  }
  if (error instanceof SeamUnreachable) {
    return `The engine is not answering, so “${label}” was not deleted.`
  }
  const said = error instanceof Error ? error.message.trim() : ''
  return said
    ? `“${label}” was not deleted. The engine said: ${said}`
    : `“${label}” was not deleted.`
}

/**
 * The same for the two smaller rail writes. `what` is the verb phrase, already carrying the
 * session's name: `rename “Assess soil test”`, `pin “…”`.
 */
export function describeWriteFailure(error: unknown, what: string): string {
  if (error instanceof SeamUnreachable) return `The engine is not answering, so ${what} failed.`
  const said = error instanceof Error ? error.message.trim() : ''
  return said ? `Could not ${what} — the engine said: ${said}` : `Could not ${what}.`
}
