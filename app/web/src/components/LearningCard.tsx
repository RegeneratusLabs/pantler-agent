/**
 * What the assistant wrote down — the one card in a turn that is about the assistant itself.
 *
 * Everything else in a turn is about the operator's business: a record it resolved, a question it
 * had to ask, a command it wants to run. This is the fifth thing, and it was invisible. The
 * engine gives its own front ends a "💾 Self-improvement review: …" line for exactly this, and
 * the argument for making it visible there holds here: a change to what the assistant knows
 * about the business should never be lost to a transient flash, and an operator who tells it
 * "remember the Bellview delivery day is Tuesday" deserves to see it kept rather than assume it.
 *
 * It is a card and not a quiet line, for the reason the front-end design §4 gives cards
 * their authority: this is a durable fact about the business, written into the assistant's own
 * memory, and it is the only place an operator can check what it thinks it was told. It reads more
 * quietly than a tool card — no raised surface, an accent that means "kept" rather than
 * "resolved" — because nothing here needs action.
 *
 * Two rules are inherited from the rest of the shell and are not softened:
 *
 *   - **A write that failed says so.** The engine answers `{"success": false, "error": …}` for a
 *     refused write, and `{"staged": true}` for one parked for approval; neither is a success
 *     and neither is rendered as one.
 *   - **Nothing shows its JSON.** The engine's own action verbs are printed (they are facts),
 *     the envelope they arrived in is not.
 */

import { Brain, Sparkles, TriangleAlert } from 'lucide-react'
import { Badge } from '../ui/badge'
import { cn } from '../ui/cn'
import type { LearningMoment } from './learning'

const KIND_TITLE: Record<LearningMoment['kind'], string> = {
  memory: 'Remembers',
  skill: 'Its own skills'
}

export function LearningCard({ moment }: { moment: LearningMoment }) {
  const Icon = moment.kind === 'memory' ? Brain : Sparkles
  const failed = moment.status === 'failed'

  return (
    <section
      className={cn(
        'flex flex-col gap-2 rounded-card border px-3.5 py-3',
        failed
          ? 'border-danger/45 bg-danger/5'
          : 'border-accent/25 bg-accent/[0.04]',
        moment.status === 'running' && 'border-line bg-surface/40'
      )}
    >
      <header className="flex items-center gap-2.5">
        <Icon
          aria-hidden
          className={cn(
            'size-3.5 shrink-0',
            failed ? 'text-danger' : moment.status === 'running' ? 'text-ink-3' : 'text-accent'
          )}
        />
        <h3 className="text-display min-w-0 flex-1 truncate text-[0.68rem] text-ink-3">
          {KIND_TITLE[moment.kind]}
        </h3>
        <LearningStatus moment={moment} />
      </header>

      <ul className="flex flex-col gap-2">
        {moment.changes.map((change, index) => (
          <li key={`${change.action}:${index}`} className="flex flex-col gap-0.5">
            <p className="flex flex-wrap items-baseline gap-x-2 text-sm text-ink-2">
              <span className={cn('font-medium', failed ? 'text-danger' : 'text-ink')}>
                {change.label}
              </span>
              {change.subject && moment.kind === 'skill' && (
                <span className="font-mono text-xs text-ink-3">{change.subject}</span>
              )}
            </p>
            {change.subject && moment.kind === 'memory' && (
              <p className="border-l-2 border-accent/35 pl-2.5 text-sm leading-relaxed whitespace-pre-wrap text-ink">
                {change.subject}
              </p>
            )}
            {change.detail && <p className="text-xs text-ink-3">{change.detail}</p>}
          </li>
        ))}
      </ul>

      {moment.error && <p className="text-sm text-danger">{moment.error}</p>}

      {moment.note && <p className="text-xs text-ink-3">{moment.note}</p>}

      {moment.path && (
        <p className="font-mono text-[0.65rem] text-ink-disabled">{moment.path}</p>
      )}
    </section>
  )
}

function LearningStatus({ moment }: { moment: LearningMoment }) {
  if (moment.status === 'running') return <Badge tone="warn">writing it down</Badge>
  if (moment.status === 'failed') {
    return (
      <Badge tone="danger">
        <TriangleAlert aria-hidden className="size-3" />
        not saved
      </Badge>
    )
  }
  return <Badge tone="accent">kept</Badge>
}
