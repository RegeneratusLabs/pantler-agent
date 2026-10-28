/**
 * One step's thinking, on screen.
 *
 * This is the quietest thing in a turn and it is meant to be. A tool card is a record and looks
 * like one; an activity line is the assistant working, said in words. Thinking is the assistant
 * working *something out*, which is more private than either — so it is one muted line by
 * default. The body is the operator's to ask for.
 *
 * What "opens" means is the whole of this component, and it is deliberately small enough to read
 * off the screen:
 *
 *  - **Closed until asked.** A live step and a thought from history both show their first line
 *    and a `read it` control. The live one also has a pulse and the word `Think`; neither opens
 *    the body. A live turn used to open a body per step, which made the transcript a column of
 *    blocks expanding and contracting under the reader.
 *  - **The body is a scroll region, not a window.** "read it" opens the whole text in a
 *    fixed-height box that scrolls. While the step is live it follows the end of the text — the
 *    decision the step is about to act on — until the operator scrolls up; once it lands it keeps
 *    the position they were at.
 *  - **An opened body stays open.** The operator's click is latched here, so the body survives
 *    the step landing and the next thought taking the live slot. "hide" is the only thing that
 *    closes it, and the operator's click is the only thing that opens one.
 *
 * The word changes once, `Think` to `Thought`, and it is the only thing on the line that marks
 * the step as finished — a shimmer or a blinking cursor would be a lie here, because the engine
 * persists thinking per step and no characters are arriving (`seam/reducer.ts`, `Thought.status`).
 * The liveness that is true — *this step is still being read* — is the pulse, and it stops when
 * the step does.
 */

import { Brain } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type UIEvent } from 'react'
import type { Thought } from '../seam/reducer'
import { cn } from '../ui/cn'
import { thoughtControl, thoughtLine, thoughtOpen } from './thought'

/**
 * `useLayoutEffect` warns when it runs on the server, and the component tests render with
 * `react-dom/server` (the internal audit WEB-16). There is no layout there to get wrong,
 * so the effect version is the honest substitute.
 */
const useSafeLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

/** How close to the end counts as "following", in pixels — a line of this type is about 20. */
const FOLLOW_SLACK = 24

export function ThoughtRow({ thought }: { thought: Thought }) {
  const live = thought.status === 'streaming'
  const line = thoughtLine(thought.text)

  // The operator's answer, or `null` while they have not given one. Kept here rather than derived
  // so that a click outlives the state that prompted it; `null` means closed, which is the
  // default for a live step and for history alike.
  const [choice, setChoice] = useState<boolean | null>(null)

  // Captured at mount: a thought that arrives while the turn runs enters once, and a transcript
  // read back whole does not animate ten rows at the reader on first paint.
  const [animate] = useState(live)

  const open = thoughtOpen({ choice })
  // The word and what the press does are decided together, so they cannot disagree.
  const control = thoughtControl({ open })

  const body = useRef<HTMLDivElement | null>(null)
  // Whether the region should keep following the end of the text. True until the operator
  // scrolls up inside it — the one gesture that means "let me read what is above".
  const following = useRef(true)

  // Pin before paint when the body opens or its text grows, so a long thought is never flashed
  // from its beginning before jumping to its end. Not when it settles: the position the reader
  // was at is part of the body staying put.
  useSafeLayoutEffect(() => {
    const node = body.current
    if (!node || !open || !live || !following.current) return
    node.scrollTop = node.scrollHeight
  }, [open, live, thought.text])

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const node = event.currentTarget
    following.current = node.scrollHeight - node.scrollTop - node.clientHeight < FOLLOW_SLACK
  }

  return (
    <div className={cn('flex flex-col gap-1', animate && 'animate-row-in')}>
      <p className="flex items-start gap-2 text-sm">
        <span className="mt-1 flex size-3.5 shrink-0 items-center justify-center">
          {live ? (
            <span aria-hidden className="animate-pulse-dot size-1.5 rounded-full bg-accent" />
          ) : (
            <Brain aria-hidden className="size-3.5 text-ink-disabled" />
          )}
        </span>

        <span className="text-ink-3">{live ? 'Think' : 'Thought'}</span>

        {/* The summary is the collapsed state, so it is not repeated once the text is open. */}
        {!open && line && <span className="min-w-0 truncate text-ink-3">· {line}</span>}

        <button
          type="button"
          aria-expanded={open}
          onClick={() => setChoice(control.choice)}
          className="shrink-0 text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
        >
          {control.label}
        </button>
      </p>

      {open && (
        <div
          ref={body}
          onScroll={onScroll}
          className="thought-scroll text-xs leading-relaxed"
        >
          <p className="ml-[1.375rem] max-w-[62ch] whitespace-pre-wrap text-ink-3">{thought.text}</p>
        </div>
      )}
    </div>
  )
}
