/**
 * The toolset vocabulary is the honest part of the Advanced disclosure: it decides whether a
 * switch is offered at all, and what a write means. The failure mode worth testing is a switch
 * that claims something it cannot do — so the tests pin the three states, the refusal to offer a
 * switch the engine cannot honour, and that a write never drops a name it does not manage and
 * never invents one the engine does not report.
 *
 * The registry's own rows — the page's list — are tested next door in `capability-rows.test.ts`.
 */

import { describe, expect, it } from 'vitest'
import type { ToolsetEntry } from '@shared/wire'
import { capabilityStatus, isSwitchable, setNamesDisabled, toolsetStatus } from './capabilities'

function toolset(name: string, enabled: boolean, extra: Partial<ToolsetEntry> = {}): ToolsetEntry {
  return { name, enabled, ...extra }
}

describe('capabilityStatus', () => {
  it('is on when the engine offers every toolset', () => {
    const status = capabilityStatus(['web'], [toolset('web', true)], [])
    expect(status.state).toBe('on')
    expect(status.missing).toEqual([])
    expect(status.disabled).toEqual([])
  })

  it('is off when this app switched it off', () => {
    const status = capabilityStatus(['web'], [toolset('web', false)], ['web'])
    expect(status.state).toBe('off')
    expect(status.disabled).toEqual(['web'])
  })

  it('is unavailable when the engine does not offer it and we did not switch it off', () => {
    // Some toolsets are excluded by the engine's own platform choice, and some are config-only.
    // Offering a switch that cannot turn them on would be the lie this page exists to avoid.
    const status = capabilityStatus(
      ['tts', 'stt'],
      [toolset('tts', false), toolset('stt', false)],
      []
    )
    expect(status.state).toBe('unavailable')
    expect(isSwitchable(status)).toBe(false)
  })

  it('reports a toolset the engine does not list at all as missing', () => {
    const status = capabilityStatus(['records'], [toolset('web', true)], [])
    expect(status.state).toBe('unavailable')
    expect(status.missing).toEqual(['records'])
  })

  it('treats a partly-off group as on only when every part is offered', () => {
    const status = capabilityStatus(
      ['tts', 'stt'],
      [toolset('tts', true), toolset('stt', false)],
      []
    )
    expect(status.state).toBe('unavailable')
  })
})

describe('isSwitchable', () => {
  it('offers a switch for something on, and for something this app turned off', () => {
    expect(isSwitchable(capabilityStatus(['web'], [toolset('web', true)], []))).toBe(true)
    expect(isSwitchable(capabilityStatus(['web'], [toolset('web', false)], ['web']))).toBe(true)
  })
})

describe('toolsetStatus', () => {
  it('applies the same rules to a single toolset', () => {
    expect(toolsetStatus(toolset('terminal', true), []).state).toBe('on')
    expect(toolsetStatus(toolset('terminal', false), ['terminal']).state).toBe('off')
    expect(toolsetStatus(toolset('kanban', false), []).state).toBe('unavailable')
  })
})

describe('setNamesDisabled', () => {
  const known = ['web', 'records', 'browser']

  it('adds every named toolset when switching off', () => {
    expect(setNamesDisabled(['web'], false, [], known)).toEqual(['web'])
  })

  it('removes every named toolset when switching on', () => {
    expect(setNamesDisabled(['web'], true, ['browser', 'web'], known)).toEqual(['browser'])
  })

  it('keeps names this screen does not manage', () => {
    expect(setNamesDisabled(['web'], false, ['memory'], known)).toEqual(['memory', 'web'])
  })

  it('never writes a name the engine does not report', () => {
    expect(setNamesDisabled(['ghost'], false, [], known)).toEqual([])
    expect(setNamesDisabled(['web', 'ghost'], false, [], known)).toEqual(['web'])
  })

  it('sorts the result so the file is stable between writes', () => {
    expect(setNamesDisabled(['web', 'records'], false, ['browser'], known)).toEqual([
      'browser',
      'records',
      'web'
    ])
  })

  it('handles skill names, which carry hyphens where toolset names cannot', () => {
    const skillNames = ['youtube-content', 'sdlc-review', 'invoicing']
    expect(setNamesDisabled(['sdlc-review'], false, [], skillNames)).toEqual(['sdlc-review'])
    expect(
      setNamesDisabled(['sdlc-review'], true, ['sdlc-review', 'invoicing'], skillNames)
    ).toEqual(['invoicing'])
  })
})
