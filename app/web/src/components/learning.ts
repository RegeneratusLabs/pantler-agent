/**
 * What the assistant did to its own memory, read off the tool call that did it.
 *
 * The engine gives a front end no memory or skill event to subscribe to. What it does give is
 * two tools — `memory` and `skill_manage` — and, for both, the full argument and result on the
 * transcript. So the moment is *derived* rather than announced, and that has one consequence
 * worth stating plainly: **the card is only as good as what the engine actually sent.**
 * `tool.started` carries a display preview and nothing else, `tool.completed` carries a result
 * capped at 500 characters and redacted before that cap (`_tool_completed_preview`,
 * `api_server_runs.py:101`), and only the transcript carries the arguments in full. Where the
 * envelope is missing, this module says less rather than guessing more — a card that named the
 * wrong skill would be worse than a card that said only "working on a skill".
 *
 * Two actions are **not** learning and are deliberately not claimed as such: `skill_view` and
 * `skills_list` read. Only a write is a change to what it knows, and the tests pin that.
 *
 * The wording follows the front-end design §4: the assistant's own plumbing is spoken,
 * never dumped, and a failure is never softened into a success. Nothing here prints JSON — the
 * envelope is read, the sentence is written.
 */

import type { ToolCall } from '../seam/reducer'
import { effectiveStatus, embeddedJson } from './tool-result'

export type LearningKind = 'memory' | 'skill'
export type LearningStatus = 'running' | 'ok' | 'failed'

/** One thing that changed: the engine's action, said in the operator's words. */
export interface LearningChange {
  /** The engine's own action verb, kept so a screen can always show the raw fact. */
  action: string
  /** What happened, in words: "Remembered", "Wrote a new skill". */
  label: string
  /** The memory's text, or the skill's name. */
  subject?: string
  /** A second line, when there is one worth reading. */
  detail?: string
}

export interface LearningMoment {
  key: string
  kind: LearningKind
  status: LearningStatus
  changes: LearningChange[]
  /** The engine's own bookkeeping line, e.g. "1% — 37/2,200 chars". */
  note?: string
  /** The tool's own failure sentence. */
  error?: string
  /** The file a skill write touched, when the tool said. */
  path?: string
}

/** The tools that *write* to what the assistant knows. Everything else is work. */
export function learningKind(tool: string): LearningKind | null {
  const name = tool.trim().toLowerCase()
  if (name === 'memory') return 'memory'
  if (name === 'skill_manage') return 'skill'
  return null
}

export function isLearningTool(tool: string): boolean {
  return learningKind(tool) !== null
}

// ------------------------------------------------------------------- the arguments

/**
 * The arguments as an object: the transcript's own JSON when the turn has been reconciled, the
 * engine's display preview otherwise. The preview is not JSON for either tool — it is
 * `+memory: "…"`, or nothing at all — so a preview that fails to parse is not an error, it is
 * the normal shape of a live call.
 */
function argsOf(call: ToolCall): Record<string, unknown> {
  for (const source of [call.args, call.argsPreview]) {
    const text = (source ?? '').trim()
    if (!text.startsWith('{')) continue
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // Not JSON. Keep looking, then fall back to the preview's own text.
    }
  }
  return {}
}

function text(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed || undefined
}

/**
 * The action and the memory text, out of a live preview.
 *
 * The engine builds it as `+<target>: "<content>"` for an add, `~` for a replace and `-` for a
 * remove, clipping the quoted part to 25 or 20 characters (`agent/display.py:_preview_memory`).
 * The sigil is the engine's own encoding of the action, so reading it is reading the engine
 * rather than guessing at it — without this a live call could only ever be called "Changed
 * something", which is the one thing it is not when it plainly says `+`.
 *
 * When the arguments themselves are on hand this is never reached. When they are not, a clipped
 * quotation is still more than nothing, and the ellipsis the engine leaves makes the clipping
 * visible rather than passing an abbreviation off as the text.
 */
function fromPreview(preview: string | undefined): { action?: string; subject?: string } {
  const match = /^([-+~])[^:]*:\s*"(.*)"\s*$/.exec((preview ?? '').trim())
  if (!match) return {}
  const action = { '+': 'add', '~': 'replace', '-': 'remove' }[match[1]]
  return { action, subject: match[2].trim() || undefined }
}

// ------------------------------------------------------------------- the vocabulary

const MEMORY_LABELS: Readonly<Record<string, string>> = {
  add: 'Remembered',
  replace: 'Changed what it remembers',
  remove: 'Forgot',
  delete: 'Forgot'
}

const SKILL_LABELS: Readonly<Record<string, string>> = {
  create: 'Wrote itself a new skill',
  patch: 'Rewrote part of a skill',
  rewrite: 'Rewrote a skill',
  write_file: 'Added a file to a skill',
  remove_file: 'Removed a file from a skill',
  delete: 'Archived a skill',
  archive: 'Archived a skill'
}

/**
 * An action we have no phrase for, said with the engine's own word rather than a guess at what
 * it meant. A card that says "Merge" is thin; a card that says "Updated what it remembers" when
 * the engine said something else is wrong, and the thin one is the better failure.
 */
function titleCase(value: string): string {
  const text = value.replace(/[_-]+/g, ' ').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Changed something'
}

/** The memory tool's one change. */
function memoryChange(call: ToolCall, args: Record<string, unknown>): LearningChange[] {
  const preview = fromPreview(call.argsPreview)
  // The arguments are the record; the preview is what a running call has instead.
  const action = (text(args.action) ?? preview.action ?? '').toLowerCase()
  const content = text(args.content)
  const old = text(args.old_text) ?? text(args.old)
  const subject = action === 'remove' || action === 'delete' ? (old ?? content) : (content ?? old)

  return [
    {
      action: action || 'update',
      label: MEMORY_LABELS[action] ?? titleCase(action),
      subject: subject ?? preview.subject
    }
  ]
}

/** The skill tool's batch: one entry per operation, in the order it applied them. */
function skillChanges(args: Record<string, unknown>): LearningChange[] {
  const operations = Array.isArray(args.operations) ? args.operations : []
  const changes: LearningChange[] = []

  for (const operation of operations) {
    if (!operation || typeof operation !== 'object' || Array.isArray(operation)) continue
    const record = operation as Record<string, unknown>
    const action = (text(record.action) ?? '').toLowerCase()
    const name = text(record.name) ?? text(record.skill)
    const category = text(record.category)
    changes.push({
      action: action || 'update',
      label: SKILL_LABELS[action] ?? titleCase(action),
      subject: name,
      // The file for a reference write; the group for a create, because a skill called
      // `delivery-days` sitting in the group `pantler` is the sort of thing worth being able to
      // see at a glance, and a bare category name next to a skill name reads as a second name.
      detail: text(record.file_path) ?? (category ? `in ${category}` : undefined)
    })
  }

  // The live preview carries no arguments at all for this tool (its primary argument, `name`,
  // is not one the batch schema uses), so a running call honestly says only what it is doing.
  if (changes.length === 0) {
    changes.push({ action: 'update', label: 'Working on its own skills' })
  }
  return changes
}

// ---------------------------------------------------------------------- the result

interface Outcome {
  failed: boolean
  error?: string
  note?: string
  /** Skill names and actions the result names, when the arguments did not. */
  applied?: LearningChange[]
  path?: string
}

/**
 * What the tool's result says happened.
 *
 * Both tools answer with the same envelope shape — `{success, error, …}` — and both report
 * `success: false` with the reason in `error`, which is the one thing that must reach the
 * screen: an action that did not happen must never be shown as having happened (invariant 3).
 * A `staged` write is a third state, not a success: the engine parked it for approval.
 */
function outcomeOf(call: ToolCall): Outcome {
  const raw = (call.result ?? '').trim()
  if (!raw) {
    return effectiveStatus(call) === 'error'
      ? { failed: true, error: 'The tool failed.' }
      : { failed: false }
  }

  const parsed = embeddedJson(raw)
  const envelope =
    parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null

  if (!envelope) {
    // Not an envelope: a live preview capped mid-object, or a plain sentence. The transcript's
    // own status is the only thing left, and the raw text is not printed.
    return effectiveStatus(call) === 'error'
      ? { failed: true, error: 'The tool failed.' }
      : { failed: false }
  }

  const error = text(envelope.error)
  if (envelope.success === false || (error && effectiveStatus(call) === 'error')) {
    return { failed: true, error: error ?? 'The engine refused the write.' }
  }

  const notes: string[] = []
  if (text(envelope.usage)) notes.push(String(text(envelope.usage)))
  else if (typeof envelope.entry_count === 'number') {
    notes.push(`${envelope.entry_count} ${envelope.entry_count === 1 ? 'entry' : 'entries'}`)
  }

  if (envelope.staged === true) notes.push('waiting for your approval')

  const applied: LearningChange[] = []
  const results = Array.isArray(envelope.results) ? envelope.results : []
  for (const entry of results) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue
    const record = entry as Record<string, unknown>
    const action = (text(record.action) ?? '').toLowerCase()
    const name = text(record.name)
    const failed = record.success === false
    applied.push({
      action,
      label: failed ? 'Could not change a skill' : (SKILL_LABELS[action] ?? titleCase(action)),
      subject: name,
      detail: failed ? text(record.error) : undefined
    })
  }

  const warnings = results
    .flatMap(entry =>
      entry && typeof entry === 'object' && Array.isArray((entry as Record<string, unknown>).lint_warnings)
        ? ((entry as Record<string, unknown>).lint_warnings as unknown[])
        : []
    )
    .length
  if (warnings > 0) {
    notes.push(`${warnings} thing${warnings === 1 ? '' : 's'} to tidy up`)
  }

  return {
    failed: false,
    note: notes.length > 0 ? notes.join(' · ') : undefined,
    applied: applied.length > 0 ? applied : undefined,
    path: text(envelope.path)
  }
}

// ------------------------------------------------------------------------- the moment

/**
 * The learning moment a tool call represents, or `null` when it represents none.
 *
 * `null` is the answer for every tool that is not a write, for a read (`skill_view`), and for
 * a call whose result we cannot read — in the last case the caller falls back to the quiet
 * activity line, which is the honest thing to show when the only truth available is "it ran".
 */
export function learningMoment(call: ToolCall): LearningMoment | null {
  const kind = learningKind(call.tool)
  if (!kind) return null

  const args = argsOf(call)
  const status = effectiveStatus(call)
  const outcome = outcomeOf(call)

  let changes = kind === 'memory' ? memoryChange(call, args) : skillChanges(args)

  // The result names what it did, and the arguments may not have (a live call has none). Prefer
  // the arguments — they carry the content — but let the result fill in a name they lack, and
  // let it *override* on a failure: "already exists" is the sentence that matters, and it must
  // not lose to the category the arguments happened to mention.
  if (outcome.applied && outcome.applied.length > 0) {
    changes = changes.map((change, index) => {
      const applied = outcome.applied?.[index]
      if (!applied) return change
      const failed = applied.label.startsWith('Could not')
      return {
        ...change,
        subject: change.subject ?? applied.subject,
        detail: failed ? (applied.detail ?? change.detail) : (change.detail ?? applied.detail),
        // A batch that the engine rolled back reports per-operation failure. The label must
        // say so even when the envelope's own `success` is true.
        label: failed ? applied.label : change.label
      }
    })
  }

  return {
    key: call.key,
    kind,
    status: outcome.failed ? 'failed' : status === 'running' ? 'running' : 'ok',
    changes,
    note: outcome.note,
    error: outcome.failed ? (outcome.error ?? 'The write did not go through.') : undefined,
    path: outcome.path
  }
}

/** Every learning moment in a turn, in the order they happened. */
export function learningMoments(calls: readonly ToolCall[]): LearningMoment[] {
  return calls.map(learningMoment).filter((moment): moment is LearningMoment => moment !== null)
}

/**
 * One line for the whole turn — the roll-up the engine's own client shows as
 * "💾 Self-improvement review: …", said in this app's voice.
 *
 * Counts rather than a list once there is more than one of a kind, for the same reason
 * `activity.summarise` counts: three "Rewrote part of a skill" lines is a list, not a summary.
 * The order is the order things happened — the engine's own summary joins with `" · "` in
 * insertion order for the same reason, and a turn reads as a sequence. A failure is never
 * folded into a count: it is what the operator has to see.
 */
export function learningLine(moments: readonly LearningMoment[]): string | undefined {
  if (moments.length === 0) return undefined

  const failed = moments.filter(moment => moment.status === 'failed')
  if (failed.length > 0) {
    return failed.length === 1
      ? 'Something it tried to write down did not go through.'
      : `${failed.length} things it tried to write down did not go through.`
  }

  const counts = new Map<string, number>()
  for (const moment of moments) {
    for (const change of moment.changes) {
      // A running call has not happened yet; saying it did would be a claim ahead of the fact.
      if (moment.status === 'running') continue
      counts.set(change.label, (counts.get(change.label) ?? 0) + 1)
    }
  }
  if (counts.size === 0) return 'Writing down what it learned…'

  return [...counts.entries()]
    .map(([label, count]) => (count === 1 ? label : `${label} ×${count}`))
    .join(' · ')
}
