/**
 * The three things a new chat suggests, and the line in the composer.
 *
 * These are prompts, not a feature list. They are chosen to show the commercial range of the
 * build in the operator's own words: money, something to sell, and the records or the story that
 * make the sale possible. A person who has never used an assistant does not need a catalogue;
 * they need to know that “find the zucchini a home” is a sentence they are allowed to type.
 *
 * **Why the work kind.** Setup already asks what the business mostly does, and the onboarding
 * tour already picks its examples from the same answer. The chat empty state reads that answer
 * too, so a bakery does not open on a spray record and a grower does not open on a jar count.
 * The default is for an operator who skipped the question; it is broad on purpose.
 *
 * **Why no demo customer.** Bellview is a fixture, not the operator’s business. The prompts use
 * archetypes — the cafe, the market shop, the wholesaler — and the assistant resolves them
 * against the operator’s own records. When it cannot, it asks: that is the product behaving
 * correctly, not the example failing.
 *
 * **Why these jobs.** Every set has a money job and two others, so the first screen is not an
 * invoice demo. The certification prompt asks for gaps in the operator’s records, never for a
 * certification verdict; the organic-certification and cite-or-refuse skills keep that line
 * honest. The lines are meant to be read aloud at a stall, not to sound like software.
 */

import type { WorkKind } from '../onboarding/profile'

/** The composer’s hint: two jobs, two moods, and no special command to learn. */
export const COMPOSER_PLACEHOLDER =
  'Just say the job — “invoice the cafe” or “find the zucchini a home”.'

/**
 * Three finished prompts per kind of business.
 *
 * A tuple, not an array: the UI has three slots and the copy should never quietly grow a fourth
 * without a layout decision. Each line ends in punctuation because it is a sentence the operator
 * could type as it stands.
 */
const BY_WORK: Record<WorkKind | 'default', readonly [string, string, string]> = {
  grow: [
    'Invoice the cafe for 12 kilos of beans and four dozen eggs — the easy part of the week.',
    'Tell the chefs what’s ready this week — beans, eggs and rocket for days.',
    'My organic certification is coming up — help me find the gaps before the highlighter comes out.'
  ],
  make: [
    'Invoice the market shop for 40 jars of jam — the fruit bill is due.',
    'Write a shop blurb for the quince paste — and no “artisanal”, please.',
    'Plan a month of posts — markets, restocks and whatever the fruit does next.'
  ],
  move: [
    'Invoice the wholesaler for 12 kilos of beans — they’ve had them a week.',
    'Make an availability list for this week’s boxes — beans, eggs and lettuce, no surprises.',
    'Draft the box note — make it sound like me, not a supermarket flyer.'
  ],
  default: [
    'Invoice the cafe for 12 kilos of beans and four dozen eggs — the easy part of the week.',
    'Tell the chefs what’s ready — beans, eggs and rocket for days.',
    'A buyer wants proof we’re organic — what have I actually got?'
  ]
}

/** Three things to try, chosen for the work they said they do. */
export function exampleAsks(work: WorkKind | ''): string[] {
  return [...BY_WORK[work || 'default']]
}
