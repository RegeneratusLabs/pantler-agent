import { describe, expect, it } from 'vitest'
import type { ProfileSummary } from '../seam/bff'
import {
  gatewayNotice,
  profileLabel,
  profileMeta,
  profileState,
  profileStateSentence,
  slugifyProfileName,
  sortProfiles,
  validateProfileName
} from './profiles'

const profile = (overrides: Partial<ProfileSummary> = {}): ProfileSummary => ({
  name: 'garden',
  display_name: '',
  description: '',
  is_install: false,
  active: false,
  provider: 'opencode-go',
  model: 'deepseek-v4.1-flash',
  has_env: true,
  served: true,
  ...overrides
})

describe('profile names', () => {
  it('derives a usable id from a business name', () => {
    expect(slugifyProfileName('Bellview Farm')).toBe('bellview-farm')
    expect(slugifyProfileName('  Josh’s  market garden ')).toBe('josh-s-market-garden')
    expect(slugifyProfileName('__Already Fine__')).toBe('already-fine')
    expect(slugifyProfileName('x'.repeat(80))).toHaveLength(64)
  })

  it('refuses what the engine would refuse, with the rule', () => {
    expect(validateProfileName('')).toMatch(/required/)
    expect(validateProfileName('default')).toMatch(/host profile/)
    expect(validateProfileName('Two Words')).toMatch(/Lowercase/)
    expect(validateProfileName('-leading')).toMatch(/Lowercase/)
    expect(validateProfileName('x'.repeat(65))).toMatch(/64/)
    expect(validateProfileName('bellview-farm_2')).toBeNull()
  })
})

describe('profile labels', () => {
  it('prefers the operator’s name and keeps the id beside the model', () => {
    expect(profileLabel(profile({ display_name: 'Bellview Farm' }))).toBe('Bellview Farm')
    expect(profileLabel(profile())).toBe('garden')
    expect(profileMeta(profile({ display_name: 'Bellview Farm' }))).toBe(
      'garden · deepseek-v4.1-flash · opencode-go'
    )
  })

  it('sorts the installed profile first, then the selected one', () => {
    const sorted = sortProfiles([
      profile({ name: 'zebra' }),
      profile({ name: 'pantler', is_install: true }),
      profile({ name: 'garden', active: true })
    ])
    expect(sorted.map(item => item.name)).toEqual(['pantler', 'garden', 'zebra'])
  })
})

describe('what the screen may claim', () => {
  it('says active, ready or restart — and never turns a missing record into a failure', () => {
    const gateway = { multiplex: false, served: [], live: true }
    expect(profileState(profile({ active: true }), gateway)).toBe('active')
    expect(profileState(profile({ served: true }), gateway)).toBe('ready')
    expect(profileState(profile({ served: false }), gateway)).toBe('restart')
    expect(profileState(profile({ served: false }), { ...gateway, multiplex: true })).toBe('pending')
    expect(profileState(profile({ served: null }), null)).toBe('unknown')
    expect(profileState(profile({ served: null }), gateway)).toBe('restart')
  })

  it('explains the restart case with the setting that fixes it', () => {
    const speech = profileStateSentence('restart')
    expect(speech).toMatch(/gateway\.multiplex_profiles|multi-profile/i)
  })

  it('warns when a second profile exists on a single-profile engine', () => {
    const gateway = { multiplex: false, served: ['pantler'], live: true }
    expect(gatewayNotice([profile({ is_install: true }), profile()], gateway, true)).toMatch(
      /multi-profile/
    )
    expect(gatewayNotice([profile({ is_install: true })], gateway, false)).toBeNull()
  })
})
