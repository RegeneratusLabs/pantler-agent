/**
 * The shape of the first run: which questions, in what order, and what counts as finished.
 *
 * Six steps, and the order is the argument. Who they are, then how they want to be spoken to, then
 * what we may reach — each answer is used by the step after it, and the last step is not a
 * congratulations screen but the first thing to actually do.
 *
 * Pure data and pure functions, so the order can be asserted without rendering anything
 * (`flow.test.ts`), and so the page itself stays presentational.
 *
 * Each step's own words — the eyebrow, the question, the sentence under it — live in
 * `steps.tsx` beside the body that renders them. They were copied here as well and never
 * rendered, so they drifted: the sixth screen said "Step 5 of 6"
 * (the internal audit WEB-17).
 */

import type { OperatorProfile } from './profile'

export type StepId = 'welcome' | 'business' | 'voice' | 'apps' | 'tour' | 'done'

export interface Step {
  id: StepId
}

export const STEPS: Step[] = [
  { id: 'welcome' },
  { id: 'business' },
  { id: 'voice' },
  { id: 'apps' },
  { id: 'tour' },
  { id: 'done' }
]

const ORDER: StepId[] = STEPS.map(step => step.id)

export function stepIndex(id: StepId): number {
  const index = ORDER.indexOf(id)
  return index === -1 ? 0 : index
}

/** The next step, or null at the end — the page turns null into "finish". */
export function nextStep(id: StepId): StepId | null {
  return ORDER[stepIndex(id) + 1] ?? null
}

/** The previous step, or null on the first — the Back button disappears rather than dead-ends. */
export function previousStep(id: StepId): StepId | null {
  const index = stepIndex(id)
  return index === 0 ? null : ORDER[index - 1]
}

export function progressOf(id: StepId): { index: number; total: number } {
  return { index: stepIndex(id) + 1, total: ORDER.length }
}

/**
 * The gate's whole decision. `complete` is the only field it reads: a half-finished run that was
 * closed mid-way shows setup again, which is the right thing to do with someone who has not been
 * told where anything is yet. Skipping sets `complete` too — skipping is an answer.
 */
export function needsSetup(profile: Pick<OperatorProfile, 'complete'>): boolean {
  return profile.complete !== true
}
