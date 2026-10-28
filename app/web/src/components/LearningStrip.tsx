/**
 * A line under the conversation, when the engine says this conversation changed what the
 * assistant knows.
 *
 * The inline cards only cover what the *stream* showed — a `memory` or `skill_manage` call the
 * assistant made while it was answering. They cannot cover the other half of self-improvement:
 * the background review and the curator, which run after the turn, on their own thread, and
 * change a skill without ever appearing in the transcript. Over the seam this app uses, nothing
 * announces that at all.
 *
 * What does announce it is the engine's own ledger, and — this is the part that makes the line
 * trustworthy — it records **which conversation caused the change** (`evidence.session_id`).
 * So this is not "something changed recently"; it is "this conversation is the reason that skill
 * is different now", in the engine's own words. When the ledger has nothing for this session,
 * there is no line: most conversations change nothing, and a permanent "nothing learned" badge
 * would be noise pretending to be information.
 *
 * **It is a quiet row, not a notification.** It used to be a tinted band across the foot of the
 * conversation reading "This conversation changed its own notes: pdf, producer-sourcing 9 times",
 * which is three mistakes in one sentence: a skill is not a note, the conversation did not do it
 * (the assistant's own review did, on its own thread), and nine writes at a file is not nine
 * events. So it now reads like the two other things in a turn that are the assistant's own
 * business rather than the operator's reading — `Think` and the activity lines
 * (the front-end design §4): one quiet line, a label, a gist, and everything else one click
 * away. What the roll-up says, and the rule that it may only ever say less than the ledger, is
 * `ledger.ts`.
 *
 * The mark leads it, wearing the monocle. This is the one moment in a conversation that is
 * about the assistant itself, so it is the one place the loaf gets a costume; 32 px is where the
 * monocle's rim reads (`brand/reference/pantler-learning-variants.png`), and the drawing is
 * decorative — the label already says what happened.
 */

import { ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import type { LearningLedgerEntry } from '@shared/wire'
import { ledgerSummary } from './ledger'
import { PantlerMark } from '../brand/PantlerMark'
import { CHAT_COLUMN, CHAT_GUTTER } from '../ui/chat-layout'
import { cn } from '../ui/cn'

export function LearningStrip({ rows }: { rows: readonly LearningLedgerEntry[] }) {
  // Before the empty guard, so the hook is not conditional: a conversation gains a ledger as its
  // background review lands, and this component stays mounted across that.
  const [open, setOpen] = useState(false)

  if (rows.length === 0) return null

  const summary = ledgerSummary(rows)
  const named = summary.changes.length > 0

  return (
    <div className="shrink-0 border-t border-line py-2">
      <div className={cn(CHAT_COLUMN, 'flex flex-col gap-1', CHAT_GUTTER)}>
        <p className="flex items-start gap-2 text-sm">
          {/* A 32 px drawing in a line-height-high slot, so its centre sits on the first
              line's centre and the row keeps its 14 px line box. */}
          <span className="flex h-[1.375rem] w-8 shrink-0 items-center justify-center">
            <PantlerMark outfit="monocle" size={32} />
          </span>

          {/* The label is the sentence: it never shrinks or wraps. The skills list is
              what gives way on a phone. */}
          <span className="shrink-0 whitespace-nowrap text-ink-3">{summary.label}</span>

          {/* The list is the collapsed state, so it is not repeated once the detail is open. */}
          {!open && named && (
            <span className="min-w-0 truncate text-ink-3">
              ·{' '}
              {summary.skills.map((skill, index) => (
                <span key={skill}>
                  {index > 0 && ', '}
                  <span className="font-mono">{skill}</span>
                </span>
              ))}
              {summary.more > 0 && ` and ${summary.more} more`}
              {summary.stamp && ` — ${summary.stamp}`}
            </span>
          )}

          {named && (
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen(value => !value)}
              className="shrink-0 text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
            >
              {open ? 'hide' : 'what changed'}
            </button>
          )}
        </p>

        {open && (
          <div className="ml-10 flex flex-col gap-1">
            {summary.changes.map(change => (
              <p key={change.skill} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                <span className="text-ink-2">
                  {change.action} <span className="font-mono">{change.skill}</span>
                </span>
                <span className="text-ink-disabled">{change.who}</span>
              </p>
            ))}

            <Link
              to="/settings"
              className="self-start text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
            >
              Everything it has learned is in Settings
              <ArrowRight aria-hidden className="ml-1 inline size-3" />
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
