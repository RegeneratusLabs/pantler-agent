import type { ToolsetEntry } from '@shared/wire'

/**
 * The toolset half of the page: the states the engine's own toolsets can be in.
 *
 * The registry's rows (`GET /api/capabilities`) carry their own `enabled` and `toggleable`, so
 * none of this applies to them — `capability-rows.ts` decides those. What is left here is the
 * Advanced disclosure, where the engine reports its toolsets on `GET /v1/toolsets` and holds its
 * suppression list in `agent.disabled_toolsets`; a row's state is worked out from those two.
 *
 * This module used to hold a hand-written map from six operator words to toolset strings — `photos`
 * meant `vision`, `records` meant `records`. An engine rename would have silently unmapped a card,
 * which is the drift the registry exists to remove (the internal capability plan §3 A6). Nothing here
 * names a toolset; every name and every state comes from the engine.
 */

export type CapabilityState = 'on' | 'off' | 'unavailable'

export interface CapabilityStatus {
  /**
   * `on` — the engine offers every toolset here.
   * `off` — this app switched at least one of them off, and can switch it back on.
   * `unavailable` — the engine does not offer it on this build, and no switch can change that.
   */
  state: CapabilityState
  /** Named toolsets the engine does not list at all (e.g. the plugin is not loaded). */
  missing: string[]
  /** Named toolsets present in `agent.disabled_toolsets`. */
  disabled: string[]
}

/** The state of a named group of toolsets, as the engine's own two lists describe it. */
export function capabilityStatus(
  names: string[],
  toolsets: ToolsetEntry[],
  disabledToolsets: string[]
): CapabilityStatus {
  const byName = new Map(toolsets.map(toolset => [toolset.name, toolset]))
  const present = names.filter(name => byName.has(name))
  const missing = names.filter(name => !byName.has(name))
  const offered = present.filter(name => byName.get(name)?.enabled)
  const disabled = names.filter(name => disabledToolsets.includes(name))

  let state: CapabilityState
  if (present.length > 0 && offered.length === present.length) state = 'on'
  else if (disabled.length > 0) state = 'off'
  else state = 'unavailable'

  return { state, missing, disabled }
}

/** Whether a switch can honestly change anything: turn it off, or back on if we turned it off. */
export function isSwitchable(status: CapabilityStatus): boolean {
  return status.state === 'on' || status.disabled.length > 0
}

/** One toolset as a group of one, so the same status rules apply in Advanced. */
export function toolsetStatus(
  toolset: ToolsetEntry,
  disabledToolsets: string[]
): CapabilityStatus {
  return capabilityStatus([toolset.name], [toolset], disabledToolsets)
}

/**
 * The next disabled list for one switch — `agent.disabled_toolsets` or `skills.disabled`.
 *
 * `current` is the engine's list as written, not ours: names this screen does not manage are
 * kept, and only names the engine actually reports are added. Writing a name the engine
 * would ignore is the same failure as accepting one, so `known` is required.
 */
export function setNamesDisabled(
  names: string[],
  on: boolean,
  current: string[],
  known: string[]
): string[] {
  const next = new Set(current)
  for (const name of names) {
    if (!known.includes(name)) continue
    if (on) next.delete(name)
    else next.add(name)
  }
  return [...next].sort()
}
