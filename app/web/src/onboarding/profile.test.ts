import { describe, expect, it, vi } from 'vitest'
import {
  EMPTY_PROFILE,
  PROFILE_KEY,
  createProfileStore,
  memoryStorage,
  parseProfile,
  profileKeyFor,
  serializeProfile
} from './profile'

/**
 * The profile is the only thing this app keeps for itself, so the tests are about the two ways it
 * can go wrong: reading something that is not ours (an older build, a hand-edited value, a
 * half-written key) without breaking the app, and losing a choice the operator made.
 */
describe('parseProfile', () => {
  it('gives the defaults for nothing at all', () => {
    expect(parseProfile(null)).toEqual(EMPTY_PROFILE)
    expect(parseProfile(undefined)).toEqual(EMPTY_PROFILE)
    expect(parseProfile('')).toEqual(EMPTY_PROFILE)
  })

  it('survives a value that is not JSON, or not an object', () => {
    expect(parseProfile('{ not json')).toEqual(EMPTY_PROFILE)
    expect(parseProfile('"a string"')).toEqual(EMPTY_PROFILE)
    expect(parseProfile('[]')).toEqual(EMPTY_PROFILE)
  })

  it('round-trips what it wrote', () => {
    const profile = {
      name: 'Sam',
      business: 'Bellview',
      work: 'grow' as const,
      voice: 'brief' as const,
      complete: true,
      updatedAt: 1_700_000_000_000
    }
    expect(parseProfile(serializeProfile(profile))).toEqual(profile)
  })

  it('falls back per field rather than repairing the whole record', () => {
    const parsed = parseProfile(
      JSON.stringify({ name: 'Sam', work: 'fish', voice: 'pirate', complete: 'yes', updatedAt: 'soon' })
    )
    expect(parsed.name).toBe('Sam')
    // An answer we do not offer is not an answer: `work` goes back to unanswered, not to a guess.
    expect(parsed.work).toBe('')
    expect(parsed.voice).toBe('warm')
    // Only a real `true` counts — "yes" is not consent to skip setup.
    expect(parsed.complete).toBe(false)
    expect(parsed.updatedAt).toBe(0)
  })

  it('trims text and ignores a value of the wrong type', () => {
    expect(parseProfile(JSON.stringify({ name: '  Sam  ' })).name).toBe('Sam')
    expect(parseProfile(JSON.stringify({ name: 42 })).name).toBe('')
  })
})

describe('the store', () => {
  it('starts from what is already in storage', () => {
    const storage = memoryStorage({
      [PROFILE_KEY]: serializeProfile({ ...EMPTY_PROFILE, name: 'Sam', complete: true })
    })
    expect(createProfileStore(storage).get().name).toBe('Sam')
  })

  it('persists a change and tells its subscribers', () => {
    const storage = memoryStorage()
    const store = createProfileStore(storage)
    const listener = vi.fn()
    store.subscribe(listener)

    store.update({ name: 'Sam', work: 'make' })

    expect(listener).toHaveBeenCalledTimes(1)
    expect(createProfileStore(storage).get()).toMatchObject({ name: 'Sam', work: 'make' })
  })

  it('merges rather than replaces, so a later step cannot drop an earlier answer', () => {
    const store = createProfileStore(memoryStorage())
    store.update({ name: 'Sam' })
    store.update({ business: 'Bellview' })
    store.update({ voice: 'patient' })
    expect(store.get()).toMatchObject({ name: 'Sam', business: 'Bellview', voice: 'patient' })
  })

  it('resets everything, including the answer that gates the app', () => {
    const store = createProfileStore(memoryStorage())
    store.update({ name: 'Sam', complete: true })
    store.reset()
    expect(store.get()).toMatchObject({ name: '', complete: false })
  })

  it('returns one stable object until something changes', () => {
    const store = createProfileStore(memoryStorage())
    // `useSyncExternalStore` re-renders forever if this is a fresh object each call.
    expect(store.get()).toBe(store.get())
    const before = store.get()
    store.update({ name: 'Sam' })
    expect(store.get()).not.toBe(before)
  })

  it('stops telling a listener that has unsubscribed', () => {
    const store = createProfileStore(memoryStorage())
    const listener = vi.fn()
    store.subscribe(listener)()
    store.update({ name: 'Sam' })
    expect(listener).not.toHaveBeenCalled()
  })
})


describe('per-profile scope', () => {
  it('keeps each business’s answers under its own key', () => {
    const storage = memoryStorage()
    const store = createProfileStore(storage)
    store.setScope('pantler')
    store.update({ name: 'Sam', business: 'Bellview', complete: true })

    store.setScope('garden')
    expect(store.get().name).toBe('')
    store.update({ name: 'Jo', business: 'Market garden' })

    store.setScope('pantler')
    expect(store.get()).toMatchObject({ name: 'Sam', business: 'Bellview', complete: true })
    store.setScope('garden')
    expect(store.get()).toMatchObject({ name: 'Jo', business: 'Market garden' })
  })

  it('inherits the single-key value for the installed profile, once', () => {
    const storage = memoryStorage({
      [profileKeyFor(null)]: serializeProfile({ ...EMPTY_PROFILE, name: 'Sam', complete: true })
    })
    const store = createProfileStore(storage)
    store.setScope('pantler', { inheritLegacy: true })
    expect(store.get().name).toBe('Sam')

    // A second profile must start empty: the same inheritance for every profile would put one
    // business's details under another's name.
    store.setScope('garden')
    expect(store.get().name).toBe('')
    store.setScope('garden', { inheritLegacy: true })
    expect(store.get().name).toBe('')
  })

  it('names the key predictably and leaves the legacy key alone', () => {
    expect(profileKeyFor(null)).toBe(PROFILE_KEY)
    expect(profileKeyFor('garden')).toBe(`${PROFILE_KEY}.garden`)
  })
})
