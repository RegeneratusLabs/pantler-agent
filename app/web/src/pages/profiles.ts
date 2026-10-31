/**
 * The Profiles screen's pure half: names, labels and the sentences that explain what the
 * engine is actually serving. Kept DOM-free so the rules are testable without a browser.
 */

import type { ProfileGateway, ProfileSummary } from '../seam/bff'

/** The engine's own profile-id grammar (`hermes_constants.PROFILE_ID_RE`). */
export const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/

export const PROFILE_NAME_RULE =
  'Lowercase letters, numbers, “-” or “_”, starting with a letter or number, up to 64 characters.'

/** A readable id from what an operator typed: “Bellview Farm” → “bellview-farm”. */
export function slugifyProfileName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^[-_]+|[-_]+$/g, '')
    .slice(0, 64)
}

/** The refusal for a name, or null when it may be used. `default` is the engine's host. */
export function validateProfileName(raw: string): string | null {
  const name = raw.trim().toLowerCase()
  if (!name) return 'A profile name is required.'
  if (name === 'default') {
    return '“default” is the engine’s own host profile. Choose another name.'
  }
  if (!PROFILE_NAME_RE.test(name)) return PROFILE_NAME_RULE
  return null
}

export function profileLabel(profile: Pick<ProfileSummary, 'name' | 'display_name'>): string {
  return profile.display_name?.trim() || profile.name
}

/** What the card prints under the name: the id when a display name is in use, else the model. */
export function profileMeta(profile: ProfileSummary): string {
  const parts: string[] = []
  if (profile.display_name?.trim()) parts.push(profile.name)
  if (profile.model) parts.push(profile.model)
  if (profile.provider) parts.push(profile.provider)
  return parts.join(' · ')
}

/** Installed first, then the selected one, then alphabetical — stable across refetches. */
export function sortProfiles(profiles: readonly ProfileSummary[]): ProfileSummary[] {
  return [...profiles].sort((a, b) => {
    if (a.is_install !== b.is_install) return a.is_install ? -1 : 1
    if (a.active !== b.active) return a.active ? -1 : 1
    return a.name.localeCompare(b.name)
  })
}

export type ProfileState = 'active' | 'ready' | 'pending' | 'restart' | 'unknown'

/**
 * What the card can honestly say about using this profile.
 *
 * `served === null` is "we could not read the gateway", not "off": the Profiles screen must not
 * turn a missing status file into a claim that a working profile is broken.
 */
export function profileState(
  profile: ProfileSummary,
  gateway: ProfileGateway | null
): ProfileState {
  if (profile.active) return 'active'
  if (profile.served === true) return 'ready'
  if (profile.served === false) return gateway?.multiplex ? 'pending' : 'restart'
  if (gateway?.multiplex === false) return 'restart'
  return 'unknown'
}

export function profileStateSentence(state: ProfileState): string {
  switch (state) {
    case 'active':
      return 'The profile the app is using.'
    case 'ready':
      return 'The engine is serving this profile. Switch to it to use it.'
    case 'pending':
      return 'The engine has not picked this profile up yet. It rescans the profiles directory within about half a minute; a restart does it at once.'
    case 'restart':
      return 'The running engine serves one profile. Restart the engine with multi-profile serving switched on before a conversation can use this profile.'
    default:
      return 'The engine’s serving status could not be read. The profile can still be selected; if a conversation fails, restart the engine.'
  }
}

/** The engine-level notice above the list, or null when there is nothing to warn about. */
export function gatewayNotice(
  profiles: readonly ProfileSummary[],
  gateway: ProfileGateway | null,
  restartRequired: boolean
): string | null {
  if (profiles.length < 2) return null
  if (restartRequired) {
    return (
      'More than one profile exists, and the engine is still serving one. The profiles are safe on disk; ' +
      'switch the engine to multi-profile serving (gateway.multiplex_profiles: true) and restart it to hold ' +
      'a conversation in each.'
    )
  }
  if (gateway && !gateway.live) {
    return (
      'The engine’s serving record could not be read, so this screen cannot say which profiles it is serving. ' +
      'That is a status, not a failure — the conversations themselves say the rest.'
    )
  }
  return null
}
