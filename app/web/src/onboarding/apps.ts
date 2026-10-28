/**
 * Which apps to show during the first run, and in what order.
 *
 * The apps page (the other agent's surface, `pages/connectors.ts`) lists twenty, in an order that
 * suits browsing: shops first, then social, then accounts and the paperwork. That is the right
 * order for a page you read. It is the wrong order for a first run, where six tiles are a first
 * impression and the question in the operator's head is "would this help *me*?" — a grower sees
 * their email and their calendar before they see a till.
 *
 * So this is a deliberate selection, not a slice: from the shared twenty, six, ordered by what the
 * work they told us about actually needs. Nothing here invents an app or changes one — the ids are
 * looked up in the shared list, and an id that has been renamed upstream disappears from the step
 * rather than rendering an empty tile.
 */

import { CONNECTORS, type Connector } from '../pages/connectors'
import type { WorkKind } from './profile'

/**
 * Six ids per kind of work, most relevant first.
 *
 * `grow` and `make` lead with the paperwork that already exists (mail, then the calendar or the
 * shop); `move` leads with orders, because that is the day. Accounts come after the things that
 * generate the work, and the till sits with the money either way.
 */
const BY_WORK: Record<WorkKind | 'default', string[]> = {
  grow: ['gmail', 'gcal', 'square', 'google_maps', 'quickbooks', 'gdrive'],
  make: ['gmail', 'stripe', 'square', 'mailchimp', 'quickbooks', 'gdrive'],
  move: ['square', 'shippo', 'gmail', 'gcal', 'stripe', 'google_maps'],
  default: ['gmail', 'gcal', 'square', 'stripe', 'quickbooks', 'gdrive']
}

const HOW_MANY = 6

/**
 * The tiles to show, in order. Never empty: an unanswered kind of work gets the general six, so the
 * step is never a blank screen with a heading over it.
 */
export function connectorsToShow(work: WorkKind | ''): Connector[] {
  const wanted = BY_WORK[work || 'default']
  const byId = new Map(CONNECTORS.map(connector => [connector.id, connector]))
  return wanted
    .map(id => byId.get(id))
    .filter((connector): connector is Connector => connector !== undefined)
    .slice(0, HOW_MANY)
}

/** How many the step will show, for the copy that promises a number. */
export const CONNECTORS_SHOWN = HOW_MANY
