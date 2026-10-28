/**
 * What the assistant has learned — an expandable summary in Settings, and the raw log under it.
 *
 * **Why it is here rather than on its own screen.** The learning itself is background work: the
 * engine curates a memory across conversations and the assistant writes its own skills, mostly
 * without anyone asking. That does not need a destination in the rail. What it does need is to be
 * *checkable* — an operator who says "remember the Bellview delivery day is Tuesday" should be able
 * to confirm it was kept — so it lives folded away in Settings, where a person goes when they
 * want to look at something rather than do something. The moment-to-moment half of it is in the
 * conversation itself (`LearningCard`, and the strip under a turn).
 *
 * **Two disclosures, and they are different questions.** The first is the plain one: what it
 * remembers, what it has written for itself, what it has rewritten, and when it last tidied up.
 * The second is the engine's raw ledger — one line per skill write, with the session that caused
 * it — which is evidence rather than information, and belongs behind Advanced for the same reason
 * the engine's other toolsets do.
 *
 * **It is read-only, and it says so.** The engine's memory, curator and node-mutation routes are
 * on its dashboard and TUI surfaces, not the seam this app uses (`app/server/learning.py` argues
 * it in full), so there is nothing here to edit or delete. What an operator wants changed, they can
 * ask the assistant to change — "forget the Bellview delivery day" is a request it can act on
 * with the tools it already has.
 *
 * **Nothing here is inferred.** Every figure comes off a file in the profile: an entry from
 * `memories/MEMORY.md`, an origin from `.usage.json` or the ledger, a conversation from the
 * ledger's own `evidence.session_id`. Where a file cannot be read it says so rather than showing
 * nothing — "it has learned nothing" and "we cannot see what it learned" are different sentences.
 */

import { Brain, ChevronRight, History, PenLine, Recycle, Wand2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import type {
  CuratorState,
  LearningLedgerEntry,
  MemoryEntry,
  MemoryFile,
  SkillProvenance
} from '@shared/wire'
import { useLearning } from '../state/app-context'
import { toMillis } from '../shell/sessions'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { cn } from '../ui/cn'
import { Spinner } from '../ui/spinner'
// The ledger's words live with the ledger's logic, because the strip says the same ones.
import { actorLabel, describeAction } from './ledger'

export function LearningPanel() {
  const { data, isPending, error } = useLearning()

  if (isPending) return <Spinner label="Reading what it has learned…" />

  if (error) {
    return (
      <Card className="border-danger/40">
        <p className="text-sm text-danger">Could not read what the assistant has learned.</p>
        <p className="text-xs text-ink-3">
          {error instanceof Error ? error.message : String(error)}
        </p>
      </Card>
    )
  }

  if (!data || !data.available) {
    return (
      <Card className="border-warning/40 bg-warning/5">
        <p className="text-xs text-ink-2">
          {data?.reason ?? 'No engine profile is configured for this server.'}
        </p>
      </Card>
    )
  }

  const skills = data.skills ?? []
  const learned = skills.filter(skill => skill.origin === 'learned')
  const touched = skills.filter(skill => skill.origin !== 'learned' && (skill.patches ?? 0) > 0)

  return (
    <div className="flex flex-col gap-2">
      <Disclosure
        icon={<Brain className="size-4" />}
        title="What it remembers and what it has written"
        hint={summaryLine(data.counts, data.memory?.total ?? 0)}
      >
        <MemoryBlock
          entries={data.memory?.entries ?? []}
          files={data.memory?.files ?? []}
          readable={data.memory?.readable !== false}
        />
        <Group
          icon={<Wand2 className="size-3.5" />}
          title="Skills it wrote itself"
          empty="None yet. When it works out a procedure worth repeating it writes it down, and it will appear here."
          skills={learned}
          learned
        />
        <Group
          icon={<PenLine className="size-3.5" />}
          title="Skills it has changed"
          empty="Nothing. It has not rewritten any of the skills that came with the app."
          skills={touched}
        />
        <CuratorRow curator={data.curator ?? null} />

        <p className="text-[0.68rem] leading-relaxed text-ink-disabled">
          This screen only reads. To change what it has learned, ask it — “forget the Bellview
          delivery day” or “that invoicing rule is wrong, fix your skill” are things it can do
          with the tools it already has.
        </p>
      </Disclosure>

      <Disclosure
        icon={<History className="size-4" />}
        title="Advanced — the change log"
        hint={`${(data.ledger ?? []).length} recorded ${(data.ledger ?? []).length === 1 ? 'change' : 'changes'}`}
      >
        <LearningLog ledger={data.ledger ?? []} />
      </Disclosure>
    </div>
  )
}

// ------------------------------------------------------------------ disclosure

/**
 * The fold. A native `<details>` would do, but the summary here is two lines with a rotating
 * chevron and a count on the right — the same shape the Capabilities page uses for its Advanced
 * section, so the app has one way of hiding something rather than two.
 */
function Disclosure({
  icon,
  title,
  hint,
  children
}: {
  icon: ReactNode
  title: string
  hint: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-card border border-line bg-surface/40">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
        className="flex w-full items-center gap-2.5 px-3.5 py-3 text-left"
      >
        <span aria-hidden className="shrink-0 text-ink-3">
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-ink-2">{title}</span>
          <span className="block text-xs text-ink-3">{hint}</span>
        </span>
        <ChevronRight
          aria-hidden
          className={cn('size-4 shrink-0 text-ink-3 transition-transform', open && 'rotate-90')}
        />
      </button>

      {open && <div className="flex flex-col gap-3 border-t border-line px-3.5 py-3">{children}</div>}
    </div>
  )
}

// --------------------------------------------------------------------- memory

function MemoryBlock({
  entries,
  files,
  readable
}: {
  entries: MemoryEntry[]
  files: MemoryFile[]
  readable: boolean
}) {
  return (
    <div className="flex flex-col gap-2">
      {files.map(file => (
        <div key={file.name} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
          <span className="text-ink-2">{file.label}</span>
          <span className="font-mono text-[0.65rem] text-ink-disabled">{file.name}</span>
          <span className="text-[0.65rem] text-ink-3">
            {file.readable && (file.entries ?? 0) > 0
              ? `${file.entries} ${file.entries === 1 ? 'entry' : 'entries'} · ${file.chars?.toLocaleString()} of ${file.limit.toLocaleString()} characters`
              : 'nothing written here yet'}
          </span>
        </div>
      ))}

      {!readable && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          A memory file exists but could not be read, so this list may be incomplete. Nothing has
          been changed.
        </p>
      )}

      {entries.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {entries.map(entry => (
            <li
              key={entry.id}
              className="rounded-lg border border-line bg-surface/50 px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap text-ink"
            >
              {entry.text}
              {entry.source === 'profile' && (
                <span className="text-display mt-1 block text-[0.6rem] text-ink-disabled">
                  your profile
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-3">
          It has not written anything down yet. Tell it something worth keeping — “remember the
          Bellview delivery day is Tuesday” — and it will appear here.
        </p>
      )}
    </div>
  )
}

// --------------------------------------------------------------------- skills

function Group({
  icon,
  title,
  empty,
  skills,
  learned
}: {
  icon: ReactNode
  title: string
  empty: string
  skills: SkillProvenance[]
  learned?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="text-display flex items-center gap-1.5 text-[0.65rem] text-ink-3">
        <span aria-hidden>{icon}</span>
        {title}
      </h4>

      {skills.length === 0 ? (
        <p className="text-xs text-ink-3">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {skills.map(skill => (
            <li
              key={skill.name}
              className="flex flex-col gap-0.5 rounded-lg border border-line bg-surface/50 px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-mono text-xs text-ink">{skill.name}</span>
                {learned && <Badge tone="accent">learned</Badge>}
                {skill.category && <Badge>{skill.category}</Badge>}
                {(skill.uses ?? 0) > 0 && (
                  <span className="text-[0.65rem] text-ink-disabled">used {skill.uses}×</span>
                )}
                {(skill.patches ?? 0) > 0 && (
                  <span className="text-[0.65rem] text-ink-disabled">
                    changed {skill.patches}×
                    {skill.lastPatchedAt ? ` · ${formatWhen(skill.lastPatchedAt)}` : ''}
                  </span>
                )}
                {skill.enabled === false && <Badge tone="warn">switched off</Badge>}
              </div>
              {skill.description && (
                <p className="text-xs leading-relaxed text-ink-3">{skill.description}</p>
              )}
              {learned && skill.learnedAt && (
                <p className="text-[0.65rem] text-ink-disabled">
                  Written {formatWhen(skill.learnedAt)}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CuratorRow({ curator }: { curator: CuratorState | null }) {
  if (!curator?.available) return null

  return (
    <div className="flex flex-col gap-1">
      <h4 className="text-display flex items-center gap-1.5 text-[0.65rem] text-ink-3">
        <span aria-hidden>
          <Recycle className="size-3.5" />
        </span>
        Its own tidying up
      </h4>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={curator.paused ? 'warn' : 'ok'}>{curator.paused ? 'paused' : 'active'}</Badge>
        <span className="text-xs text-ink-3">
          {curator.lastRunAt ? `last looked ${formatWhen(curator.lastRunAt)}` : 'has not run yet'}
        </span>
        {typeof curator.runCount === 'number' && curator.runCount > 0 && (
          <span className="text-[0.65rem] text-ink-disabled">
            {curator.runCount} {curator.runCount === 1 ? 'review' : 'reviews'} so far
          </span>
        )}
      </div>
      <p className="text-xs text-ink-3">
        Every so often it reviews the skills it has written and archives the ones it has stopped
        using. Archiving is reversible.
      </p>
      {curator.summary && <p className="text-[0.68rem] text-ink-disabled">{curator.summary}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ the log

/** The most recent lines the log shows. It is a log, not an archive. */
const LOG_LINES = 50

/**
 * The engine's ledger, as a log.
 *
 * Deliberately plain: one timestamped line per skill write, newest first, in the shape the file
 * itself is in. It is the only place in the app that names the conversation a change came from,
 * and that is the engine's own attribution (`evidence.session_id`) rather than a guess. Anything
 * friendlier than this would be dressing up evidence as a feature.
 */
export function LearningLog({ ledger }: { ledger: readonly LearningLedgerEntry[] }) {
  const recent = [...ledger].reverse().slice(0, LOG_LINES)

  if (recent.length === 0) {
    return (
      <p className="text-xs text-ink-3">
        Nothing logged yet. The engine writes a line here each time the assistant or its own
        review changes a skill.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <pre className="max-h-80 overflow-auto rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[0.68rem] leading-relaxed whitespace-pre-wrap text-ink-3">
        {recent
          .map(row => {
            const when = formatWhen(row.at) || 'unknown time'
            const who = actorLabel(row.actor)
            const file = row.file ? ` (${row.file})` : ''
            const session = row.session ? ` [${row.session}]` : ''
            return `${when}  ${who.padEnd(16)}${describeAction(row.action)} ${row.skill}${file}${session}`
          })
          .join('\n')}
      </pre>
      {ledger.length > recent.length && (
        <p className="text-[0.65rem] text-ink-disabled">
          Showing the {recent.length} most recent of {ledger.length} recorded changes.
        </p>
      )}
    </div>
  )
}

// --------------------------------------------------------------------- words

/** Epoch seconds (the engine's unit) or an ISO string, said the way an operator reads a date. */
export function formatWhen(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return ''
  const date = new Date(typeof value === 'number' ? toMillis(value) : value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/** One line for the collapsed fold, so the count is visible without opening it. */
function summaryLine(
  counts: { listed: number; learned: number; changed: number } | undefined,
  memories: number
): string {
  const parts = [
    memories === 0 ? 'nothing remembered yet' : `${memories} ${memories === 1 ? 'thing' : 'things'} remembered`,
    counts?.learned
      ? `${counts.learned} ${counts.learned === 1 ? 'skill' : 'skills'} written by it`
      : 'no skills of its own yet',
    counts?.changed ? `${counts.changed} changed` : null
  ].filter(Boolean)
  return parts.join(' · ')
}
