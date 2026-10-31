/**
 * What a registry row shows, decided in one place.
 *
 * `GET /api/capabilities` answers with data, not with sentences: `toggleable`, `reason`,
 * `applied_at`, `needs`. This module is the only thing that turns that data into a row, so the
 * honesty rules of the screen are decided here rather than in JSX — they can be tested without
 * rendering, and there is one place to look when a switch claims more than it can do
 * (the design notes invariant 4, the internal capability plan §3 A6):
 *
 *   · `toggleable: false` ⇒ the row carries its `reason` and no switch, ever;
 *   · `applied_at: next_restart` ⇒ the row says so, because a restart is a different promise
 *     from the next conversation and the two must not read alike;
 *   · `needs` ⇒ said before the switch, in the operator's words, never after the failure.
 *
 * The registry is the authority on all three. Nothing here may be more optimistic than it.
 */

import type { Capability, CapabilityAppliedAt, CapabilityKind } from '@shared/wire'

/** The order the kinds read in: what the assistant knows, then what it can reach. */
export const KIND_ORDER: readonly CapabilityKind[] = ['skill', 'plugin', 'mcp_server', 'connector']

/** A kind's heading. Plural, because a heading names a list. */
export const KIND_LABELS: Record<CapabilityKind, string> = {
  skill: 'Skills',
  plugin: 'Plugins',
  mcp_server: 'MCP servers',
  connector: 'Connectors'
}

/** The group the distribution's own skills carry; it leads, because it is the one that is ours. */
export const DISTRIBUTION_GROUP = 'pantler'

/** A `toggleable: false` row the server gave no reason for still gets no switch. */
const NO_REASON = 'No switch is offered for this one.'

/** A row, as the screen draws it. */
export interface CapabilityRow {
  /** The registry's `enabled` — the state a switch would move. */
  on: boolean
  /** Whether a switch may be drawn: the registry allows it *and* the write path can act on the id. */
  switchable: boolean
  /** Why there is no switch, or null when there is one. */
  reason: string | null
  /** What it needs, in the operator's words. Shown before the switch, never after a failure. */
  needs: string[]
  /** When a change lands, as a sentence. */
  applies: string
  /** Whether that sentence is the restart one, so the row can weigh it differently. */
  restartRequired: boolean
}

export function capabilityRow(capability: Capability): CapabilityRow {
  const mismatch = idKindMismatch(capability)

  return {
    on: capability.enabled,
    switchable: capability.toggleable && mismatch === null,
    reason: capability.toggleable ? mismatch : (capability.reason?.trim() || NO_REASON),
    needs: needsWording(capability.needs),
    applies: appliesWording(capability.applied_at),
    restartRequired: capability.applied_at === 'next_restart'
  }
}

/**
 * Whether the id names the kind the writer dispatches on.
 *
 * `PUT /api/capabilities/{id}` reads the kind off the id's prefix — `skill:…`, `plugin:…`,
 * `mcp_server:…`, `connector:…` — so an id whose prefix is not its kind reaches no writer and
 * answers 400 `bad_id`. Drawing a switch for one would be a switch that cannot work, which is the
 * one thing this screen must not do; the row says what is wrong instead, and says whose fault it
 * is, because an operator can do nothing about it but report it.
 *
 * This is not hypothetical: the registry served `mcp:<name>` next to `kind: mcp_server` until it
 * was fixed, and those rows could be read but never switched. The guard is what turns a drift like
 * that into a sentence rather than a 400 on click, so it stays even while the two sides agree.
 */
export function idKindMismatch(capability: Capability): string | null {
  const prefix = capability.id.split(':')[0]
  if (prefix === capability.kind) return null
  return (
    `Cannot be switched: its id “${capability.id}” does not name the kind the server dispatches ` +
    `on (${capability.kind}). That is a fault in the capability registry rather than in this screen.`
  )
}

/**
 * `needs` in the operator's words.
 *
 * The vocabulary is the engine's own manifest fields (`app/server/capabilities.py`), so a
 * credential is `credential:FOO_KEY`, an account is `auth`, extra code is `dependencies` — and a
 * trailing `?` means the capability works without it. A need this build does not recognise is
 * still said: dropping one would be the same silence as never having declared it.
 */
export function needsWording(needs: readonly string[]): string[] {
  return needs.map(need => {
    const optional = need.endsWith('?')
    const value = (optional ? need.slice(0, -1) : need).trim()
    if (!value) return 'needs something the registry did not name'

    const [kind, ...rest] = value.split(':')
    const detail = rest.join(':').trim()
    const lead = optional ? 'may need' : 'needs'

    switch (kind) {
      case 'credential':
        return `${lead} a key: ${detail || 'unnamed'}`
      case 'auth':
        return `${lead} an account`
      case 'dependencies':
        return `${lead} extra software`
      default:
        return `${lead} ${value}`
    }
  })
}

/**
 * When a write lands, as the row's own sentence.
 *
 * Most switches are read when the engine builds the next agent; plugins and MCP servers are read
 * at load, so their change waits for a restart. An unfamiliar timing is never rounded to the
 * friendlier one.
 */
export function appliesWording(appliedAt: CapabilityAppliedAt): string {
  switch (appliedAt) {
    case 'new_conversations':
      return 'takes effect from your next conversation'
    case 'next_restart':
      return 'takes effect after a restart'
    default:
      return `takes effect at a time this app cannot say (${String(appliedAt)})`
  }
}

export interface CapabilityGroup {
  /** The registry's own group: a skill's category, or `Plugins` / `MCP servers` / `Connectors`. */
  group: string
  rows: Capability[]
}

export interface CapabilityKindBlock {
  kind: CapabilityKind
  label: string
  groups: CapabilityGroup[]
}

/**
 * Kind, then group, then label — the order the page reads in.
 *
 * A kind this build does not know is listed after the ones it does rather than dropped: a
 * capability the registry reports must be visible, or the list is claiming the profile holds less
 * than it does.
 */
export function groupCapabilities(capabilities: readonly Capability[]): CapabilityKindBlock[] {
  const kinds = [...new Set(capabilities.map(capability => capability.kind))]
  const order = [
    ...KIND_ORDER.filter(kind => kinds.includes(kind)),
    ...kinds.filter(kind => !KIND_ORDER.includes(kind)).sort()
  ]

  return order.map(kind => {
    const groups = new Map<string, Capability[]>()
    for (const capability of capabilities.filter(entry => entry.kind === kind)) {
      const group = capability.group.trim() || KIND_LABELS[kind] || kind
      groups.set(group, [...(groups.get(group) ?? []), capability])
    }

    return {
      kind,
      label: KIND_LABELS[kind] ?? kind,
      groups: [...groups.entries()]
        .sort(([a], [b]) =>
          a === DISTRIBUTION_GROUP ? -1 : b === DISTRIBUTION_GROUP ? 1 : a.localeCompare(b)
        )
        .map(([group, rows]) => ({
          group,
          rows: [...rows].sort((a, b) => labelOf(a).localeCompare(labelOf(b)))
        }))
    }
  })
}

const labelOf = (capability: Capability) => capability.label.trim() || capability.name

/** What a refused write could tell us: the status the server answered, and its words. */
export interface CapabilityWriteFailure {
  status?: number
  message?: string
}

/**
 * What the operator is told when a write is refused.
 *
 * The status decides the sentence, because the three cases are three different facts: a 404 means
 * the row is stale — the profile moved on under this page — a 409 means there is nothing behind
 * the capability to switch, and anything else is the server's own words rather than ours.
 */
export function capabilityWriteMessage(failure: CapabilityWriteFailure): string {
  if (failure.status === 404) {
    return 'This profile no longer holds it. Reload the page to see what is there now.'
  }
  if (failure.status === 409) {
    return 'There is nothing behind it to switch, so the server refused.'
  }
  if (failure.message?.trim()) return failure.message
  if (failure.status) return `The server answered HTTP ${failure.status}.`
  return 'The server could not be reached.'
}

/**
 * Read a thrown value into the two things a refusal can carry.
 *
 * Structural rather than `instanceof SeamError`, so this module stays free of the transport and a
 * test can hand it a plain object.
 */
export function capabilityWriteFailure(error: unknown): CapabilityWriteFailure {
  if (typeof error === 'string' && error.trim()) return { message: error }
  if (typeof error !== 'object' || error === null) return {}

  const candidate = error as { status?: unknown; message?: unknown }
  return {
    status: typeof candidate.status === 'number' ? candidate.status : undefined,
    message: typeof candidate.message === 'string' ? candidate.message : undefined
  }
}
