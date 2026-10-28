/**
 * The engine's own ledger, said in words.
 *
 * `skills/.curator_ledger.jsonl` is a file, not a sentence: one row per *write*, with the verb
 * the engine used (`patch`, `write_file`, `create`), the skill it touched, and — the part that
 * makes it worth showing at all — the conversation whose turn caused it (`evidence.session_id`).
 *
 * Read raw, that file says "9 changes". That number is true and it is useless: the curator writes
 * a skill in several passes and every pass is its own row, so the operator sees a tally of edits
 * to a file rather than a fact about what the assistant knows. So this module rolls the rows up
 * to **one line per skill**, and it is the one place that decides how the ledger is said
 * (`LearningStrip` lays it out, `LearningPanel`'s log prints it straight).
 *
 * Two rules, and they are the rules `learning.ts` is held to as well:
 *
 *   - **A roll-up may say less than the ledger, never something else.** The verb kept for a skill
 *     is one the ledger actually recorded against it, so "wrote a new skill" is only ever said
 *     about a skill with a `create` row. Verb by verb, the whole log is in Settings.
 *   - **Nothing prints its JSON, and nothing prints an id.** The rows are read, the sentence is
 *     written — the session a change came from is the engine's bookkeeping, and the strip already
 *     sits in the conversation it is talking about.
 */

import type { LearningLedgerEntry } from '@shared/wire'
import { toMillis } from '../shell/sessions'

/** The quiet line names at most this many skills before it starts counting instead. */
const NAMED = 3

/**
 * The verb that best says what happened to a skill, when a session did several things to it.
 *
 * The ones that change *which skills exist* outrank the ones that change what is written inside
 * one, and an ordinary edit is last because it is the one that needs no saying. A roll-up is a
 * reading, so this is a ranked opinion rather than a rule the engine has — which is exactly why
 * it lives here, in one list, rather than in the component.
 */
const HEADLINE: readonly string[] = [
  'create',
  'rewrite',
  'delete',
  'archive',
  'write_file',
  'remove_file',
  'patch'
]

/** One skill this conversation changed, and the one thing worth saying about it. */
export interface LedgerChange {
  /** The skill's own name — the engine's, not a tidied version of it. */
  skill: string
  /** The headline verb as a phrase the name can follow: "wrote a new skill", "rewrote". */
  action: string
  /** Who made it: "while working" (mid-conversation) or "while tidying up" (its own review). */
  who: string
}

export interface LedgerSummary {
  /** The quiet line's own words, before the list. */
  label: string
  /** The skills it names, newest change first. Capped at `NAMED`. */
  skills: string[]
  /** How many skills the line does not name, because there were more than `NAMED`. */
  more: number
  /** "last 09:27 PM", or "last 11 Oct, 09:27 PM" once that is not today. Empty with no stamp. */
  stamp: string
  /** One entry per skill, newest change first. Empty when the ledger named no skill at all. */
  changes: LedgerChange[]
}

/**
 * The ledger for one conversation, rolled up.
 *
 * `rows` is oldest-first, which is the order the engine wrote them and the order the API returns
 * them; the newest change is the one to lead with, so the walk runs backwards from the end.
 */
export function ledgerSummary(
  rows: readonly LearningLedgerEntry[],
  now: Date = new Date()
): LedgerSummary {
  const changes: LedgerChange[] = []
  const seen = new Set<string>()

  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index]
    const skill = row.skill?.trim()
    if (!skill || seen.has(skill)) continue
    seen.add(skill)
    changes.push({ skill, action: describeAction(headline(rows, skill)), who: actorLabel(row.actor) })
  }

  const named = changes.slice(0, NAMED)

  return {
    label: 'Learned from this conversation',
    skills: named.map(change => change.skill),
    more: changes.length - named.length,
    stamp: changeStamp(newestStamp(rows), now),
    changes
  }
}

/** The most significant verb the ledger recorded against one skill. */
function headline(rows: readonly LearningLedgerEntry[], skill: string): string {
  const verbs = rows
    .filter(row => row.skill?.trim() === skill)
    .map(row => row.action?.trim().toLowerCase())
    .filter(Boolean)

  for (const candidate of HEADLINE) {
    if (verbs.includes(candidate)) return candidate
  }
  // A verb we have no rank for is still the engine's own word for what it did, and the newest
  // one is the closest thing to the outcome. It is printed as written rather than guessed at.
  return verbs[verbs.length - 1] ?? 'update'
}

/** The newest stamp the ledger carried — the newest row's, or the newest that has one. */
function newestStamp(rows: readonly LearningLedgerEntry[]): number | null {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const at = rows[index].at
    if (typeof at === 'number' && Number.isFinite(at) && at > 0) return at
  }
  return null
}

/**
 * When the newest change happened, said the way a person says it: a bare time while it is still
 * today, and the day in front of it once it is not.
 *
 * The line this replaces printed the time alone, which read correctly for the rest of that
 * evening and became a small lie — "last 09:27 PM" — every day after it.
 */
export function changeStamp(at: number | null, now: Date = new Date()): string {
  // `at <= 0` is the engine's way of saying it could not read the stamp, and `toMillis` folds it
  // to 0 — which is a perfectly valid `Date` and would print the epoch as "1 Jan 1970".
  if (at === null || !Number.isFinite(at) || at <= 0) return ''
  const date = new Date(toMillis(at))
  if (Number.isNaN(date.getTime())) return ''

  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  if (sameDay(date, now)) return `last ${time}`

  const day = date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  return `last ${day}, ${time}`
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

// --------------------------------------------------------------------- words

/**
 * The engine's ledger verbs, as a verb phrase the skill's name can follow: "wrote a new skill
 * delivery-days", "added a file to soil-amendment-engine".
 *
 * An unknown verb is printed as the engine wrote it rather than dressed up — the ledger is
 * evidence, and paraphrasing evidence is how a record stops being one.
 */
export function describeAction(action: string): string {
  const known: Record<string, string> = {
    create: 'wrote a new skill',
    patch: 'changed',
    rewrite: 'rewrote',
    write_file: 'added a file to',
    remove_file: 'removed a file from',
    delete: 'archived',
    archive: 'archived'
  }
  return known[action.toLowerCase()] ?? action.replace(/[_-]+/g, ' ')
}

/** Who made the change. `agent` is the assistant mid-conversation; `curator`, its own review. */
export function actorLabel(actor: string): string {
  if (actor === 'agent') return 'while working'
  if (actor === 'curator') return 'while tidying up'
  return actor
}
