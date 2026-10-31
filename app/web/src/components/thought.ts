/**
 * Where a turn's thinking goes, and how much of it shows.
 *
 * A turn is a sequence of steps, and a step is some thinking followed by the calls it produced.
 * The stream gives us the calls and the transcript gives us the thinking (the front-end design
 * §2), so this module is what puts the two back into one order. It is pure, so that order can be
 * asserted without a DOM.
 *
 * Two rules about order, both deliberate:
 *
 *  - **A thought never splits a fold.** `segmentTools` decides which calls print as cards and
 *    which fold into one quiet line, and a thought anchored inside a folded run is placed after
 *    it rather than cutting the run in half. The run is read as one piece of work.
 *  - **A thought with nothing behind it starts the turn.** That is the step that had not called
 *    anything yet, which is exactly where it happened.
 *
 * Three rules about how much shows, which is the rest of this module:
 *
 *  - **A line is the record; the body is opt-in.** Every thought — the live step and history
 *    alike — shows one line and waits. The line is the thought's *first*, because that is where a
 *    reader decides whether it is worth opening. The live step adds a pulse and the word
 *    `Think`, but it does not open itself: a live turn used to expand a body per step, and the
 *    transcript read as a column of opening and closing blocks under the reader.
 *  - **The operator's click is the only thing that opens or closes it.** "read it" opens the whole
 *    text in a fixed-height scroll region; "hide" closes it. A body the operator opened stays
 *    open when its step lands and when the next thought takes the live slot — the click
 *    outlives the state that prompted it — but nothing opens without that click.
 *  - **A body the operator did not ask for cannot grow without limit.** The clamp is a
 *    `max-height` in `styles.css` (`thought-scroll`) and the text inside it scrolls, so a long
 *    thought is read by scrolling rather than by growing the turn. While the step is live and
 *    the body is open, it follows the end of the text; once the step has landed it keeps the
 *    position the reader was at, which is the no-jump rule applied inside the box as well as
 *    outside it.
 *
 * What a thought says in one line is a reading of the text rather than a rendering of it, which
 * is why it is here. The rendering is `Thought.tsx`.
 */

import type { Thought, ToolCall } from '../seam/reducer'
import { segmentTools, type TurnSegment } from './activity'

/** Thinking and work in one sequence, in the order the turn actually happened. */
export type TurnStep = { kind: 'thought'; key: string; thought: Thought } | TurnSegment

/** The one line a settled thought collapses to. Longer than this and it stops being a line. */
const MAX_LINE = 96

/**
 * Interleave thoughts and tool segments by `seq`.
 *
 * A thought's `seq` is how many of the turn's calls came before it, so it belongs before the
 * first segment carrying a call at or past that anchor — which is what makes the thinking for a
 * step appear above the calls that step made.
 */
export function stepsOf(thoughts: readonly Thought[], tools: readonly ToolCall[]): TurnStep[] {
  const segments = segmentTools(tools)
  const ordered = [...thoughts].sort((a, b) => a.seq - b.seq)
  const steps: TurnStep[] = []
  let index = 0

  for (const segment of segments) {
    while (index < ordered.length && ordered[index].seq <= segment.seq) {
      steps.push({ kind: 'thought', key: ordered[index].key, thought: ordered[index] })
      index += 1
    }
    steps.push(segment)
  }

  // Anchored past the last call on screen: the calls it precedes have not arrived yet (a thought
  // lands as its step ends, which can be a moment before its call is streamed), so it goes last.
  for (; index < ordered.length; index++) {
    steps.push({ kind: 'thought', key: ordered[index].key, thought: ordered[index] })
  }

  return steps
}

/**
 * The summary a settled thought shows: its first real line, clipped.
 *
 * The thinking is written as prose, so the first line is where a reader decides whether to open
 * it. Blank lines are skipped rather than summarised as nothing.
 */
export function thoughtLine(text: string): string {
  const line = text
    .split('\n')
    .map(part => part.trim())
    .find(part => part !== '')

  if (!line) return ''
  return line.length > MAX_LINE ? `${line.slice(0, MAX_LINE - 1).trimEnd()}…` : line
}

/**
 * Whether a thought's body is showing.
 *
 * Closed until the operator says otherwise. That is the whole rule, and it is deliberately
 * small: neither being the live step nor arriving from history opens a body. The live step is
 * marked by the pulse and the word `Think`; opening is a separate decision the operator makes
 * with the one control on the line.
 *
 * `choice` is latched in `Thought.tsx`, so a body the operator opened stays open when the step
 * lands and when the next thought takes the live slot. There is no other input: a rule that
 * derived "open" from the turn moving on was what made a live turn expand and contract under
 * the reader.
 */
export function thoughtOpen({ choice }: { choice: boolean | null }): boolean {
  return choice === true
}

/** What the row's one control says — and, inseparably, what pressing it records. */
export interface ThoughtControl {
  label: 'read it' | 'hide'
  /** The operator's answer the press stands for. */
  choice: boolean
}

/**
 * The label and the action, decided together.
 *
 * They were two expressions once, and they drifted: a body with more above it was labelled "read
 * it all", but a control that toggles `open` reads that as "close it", so the one press that was
 * supposed to show the whole thought shut the row instead. Returning both from one place is what
 * makes that unrepresentable — there is no arrangement of the booleans where the word and the
 * deed disagree.
 *
 * There is no "read it all" any more: the body has always been the whole text, scrolled rather
 * than clipped, so the press that opens it never has a cap to lift.
 */
export function thoughtControl({ open }: { open: boolean }): ThoughtControl {
  return open ? { label: 'hide', choice: false } : { label: 'read it', choice: true }
}
