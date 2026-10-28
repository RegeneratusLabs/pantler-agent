/**
 * What the app knows about the operator, kept on this machine.
 *
 * This is *our* profile, not the engine's: the engine has `display.personality`, `SOUL.md` and a
 * profile directory, and none of them is the right place for "what should I call you" or "what does
 * your business do". Those are the shell's business, so they live here.
 *
 * **Where it is stored, and the honest limit of that.** In the browser's `localStorage`, under one
 * key per profile (`profileKeyFor`). It follows the *app*, not the install: the operator's phone and
 * their desktop each keep their own copy, and clearing site data runs setup again. That is the right
 * trade for Phase 0/1 — the app is served from one origin on the operator's own machine and there is
 * no account to sync through — and it is a deliberate placeholder for a pantler-owned settings block
 * in the profile when the BFF grows one. Nothing here pretends to be that: one shape, a version and
 * a profile in the key, so a later move can migrate rather than guess. The installed profile keeps
 * the original key so an upgrade does not ask the first business who it is all over again.
 *
 * The storage is injected rather than reached for, so the parsing and the defaults are testable
 * without a browser (the suite runs in node — `vite.config.ts`).
 */

import { useSyncExternalStore } from 'react'
import { DEFAULT_VOICE_ID, isVoiceId, turnInstructions, type VoiceId } from './personalities'

/** One key, versioned in its name: a later shape gets a new key and a migration, not a guess. */
export const PROFILE_KEY = 'pantler.operator.v1'

/**
 * A profile is a business, and "what should I call you / what is the business called" is a
 * business's fact. The base key keeps the shape it always had for the installed profile; every
 * additional profile gets its own suffix so switching the rail's profile also switches these
 * answers. A browser that has only ever used one profile therefore keeps its answers.
 */
export function profileKeyFor(scope: string | null | undefined): string {
  const name = (scope ?? '').trim()
  return name ? `${PROFILE_KEY}.${name}` : PROFILE_KEY
}

/** What the business mostly does. Picks the pack, and colours the examples. */
export type WorkKind = 'grow' | 'make' | 'move'

export const WORK_KINDS: { id: WorkKind; label: string; blurb: string }[] = [
  { id: 'grow', label: 'I grow it', blurb: 'Market garden, farm, orchard, livestock' },
  { id: 'make', label: 'I make it', blurb: 'Bakery, preserves, dairy, drinks' },
  { id: 'move', label: 'I move it', blurb: 'Boxes, deliveries, markets, wholesale' }
]

export function isWorkKind(value: unknown): value is WorkKind {
  return value === 'grow' || value === 'make' || value === 'move'
}

export interface OperatorProfile {
  /** What to call the person. */
  name: string
  /** What to call the business. */
  business: string
  /** Empty until they answer — an unanswered question is not a default. */
  work: WorkKind | ''
  voice: VoiceId
  /** Setup finished (or was skipped). The gate reads this and nothing else. */
  complete: boolean
  /** Epoch millis of the last write, for the record. */
  updatedAt: number
}

export const EMPTY_PROFILE: OperatorProfile = {
  name: '',
  business: '',
  work: '',
  voice: DEFAULT_VOICE_ID,
  complete: false,
  updatedAt: 0
}

const asText = (value: unknown, limit = 80): string =>
  typeof value === 'string' ? value.trim().slice(0, limit) : ''

/**
 * Whatever is in storage, as a profile. Tolerant on purpose: this data is written by an older build,
 * a different tab, or a person with a text editor, and none of those is a reason to break the app.
 * Anything unrecognised falls back to the default for that field rather than being repaired into
 * something the operator did not choose.
 */
export function parseProfile(raw: string | null | undefined): OperatorProfile {
  if (!raw) return { ...EMPTY_PROFILE }
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return { ...EMPTY_PROFILE }
  }
  if (!data || typeof data !== 'object') return { ...EMPTY_PROFILE }
  const record = data as Record<string, unknown>
  return {
    name: asText(record.name),
    business: asText(record.business),
    work: isWorkKind(record.work) ? record.work : '',
    voice: isVoiceId(record.voice) ? record.voice : DEFAULT_VOICE_ID,
    complete: record.complete === true,
    updatedAt: typeof record.updatedAt === 'number' && Number.isFinite(record.updatedAt) ? record.updatedAt : 0
  }
}

export function serializeProfile(profile: OperatorProfile): string {
  return JSON.stringify(profile)
}

/** The two things a store needs; injecting it is what makes this module testable in node. */
export interface StoragePort {
  read(key: string): string | null
  write(key: string, value: string): void
}

/** In-memory storage: the test double, and the fallback when a browser refuses us its store. */
export function memoryStorage(seed: Record<string, string> = {}): StoragePort {
  const cells = new Map(Object.entries(seed))
  return {
    read: key => cells.get(key) ?? null,
    write: (key, value) => void cells.set(key, value)
  }
}

/**
 * `localStorage` when it is there and usable. It throws rather than being absent in a few real
 * situations — private modes, a blocked third-party context, a full quota — so the read is the test,
 * and a refusal is a silent fall back to memory rather than a broken first run.
 */
function browserStorage(): StoragePort {
  try {
    const probe = '__pantler_probe__'
    window.localStorage.setItem(probe, '1')
    window.localStorage.removeItem(probe)
    return {
      read: key => window.localStorage.getItem(key),
      write: (key, value) => window.localStorage.setItem(key, value)
    }
  } catch {
    return memoryStorage()
  }
}

export interface ProfileStore {
  get(): OperatorProfile
  /** Merge a change and persist it. Returns the profile as it now stands. */
  update(patch: Partial<OperatorProfile>): OperatorProfile
  /** Everything back to the start, including `complete` — the "set up again" path. */
  reset(): OperatorProfile
  subscribe(listener: () => void): () => void
  /**
   * Point the store at a profile's answers. `inheritLegacy` copies the old single-key value
   * into the installed profile the first time it is scoped, so upgrading does not make an
   * operator answer the setup questions again.
   */
  setScope(scope: string | null | undefined, options?: { inheritLegacy?: boolean }): void
}

export interface ProfileStoreOptions {
  /** The key this store starts on; defaults to the legacy key. */
  key?: string
}

export function createProfileStore(storage: StoragePort, options: ProfileStoreOptions = {}): ProfileStore {
  let currentKey = options.key ?? PROFILE_KEY
  // Cached so `getSnapshot` is referentially stable: `useSyncExternalStore` re-renders forever
  // otherwise, and this is the classic way to ship that bug.
  let cache = parseProfile(storage.read(currentKey))
  const listeners = new Set<() => void>()

  const publish = (next: OperatorProfile) => {
    cache = next
    storage.write(currentKey, serializeProfile(next))
    for (const listener of listeners) listener()
    return next
  }

  return {
    get: () => cache,
    update: patch => publish({ ...cache, ...patch, updatedAt: Date.now() }),
    reset: () => publish({ ...EMPTY_PROFILE, updatedAt: Date.now() }),
    subscribe: listener => {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    setScope: (scope, options = {}) => {
      const key = profileKeyFor(scope)
      if (key === currentKey) return
      if (options.inheritLegacy) {
        const legacy = storage.read(PROFILE_KEY)
        if (legacy !== null && storage.read(key) === null) storage.write(key, legacy)
      }
      currentKey = key
      cache = parseProfile(storage.read(key))
      for (const listener of listeners) listener()
    }
  }
}

/** The app's store. One instance, created at import; its scope follows the selected profile. */
export const operatorProfile = createProfileStore(
  typeof window === 'undefined' ? memoryStorage() : browserStorage()
)

/** React binding. The profile is small, so every consumer may re-render on a change. */
export function useOperatorProfile(): OperatorProfile {
  return useSyncExternalStore(operatorProfile.subscribe, operatorProfile.get, operatorProfile.get)
}

/**
 * The overlay for the next turn, read at send time rather than at render time — a voice changed in
 * Settings applies to the message after it, which is what the settings copy promises.
 *
 * It is never empty: the voice may be absent, but the chat surface's formatting instruction is
 * always sent (`turnInstructions`).
 */
export function currentVoiceInstructions(): string {
  return turnInstructions(operatorProfile.get().voice)
}
