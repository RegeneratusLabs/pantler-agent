/**
 * The registry's rows are the honest part of the Capabilities screen: they decide whether a
 * switch is drawn at all, what it is said to need, and when its effect is claimed. The failure
 * mode worth testing is a row that promises more than the registry allows — a switch on
 * something with `toggleable: false`, a restart sold as live, a need shown only after the
 * failure. The writer's three refusals (404, 409, anything else) are pinned here too, because
 * each one tells the operator a different fact.
 */

import { describe, expect, it } from 'vitest'
import type { Capability, CapabilityAppliedAt, CapabilityKind } from '@shared/wire'
import {
  capabilityRow,
  capabilityWriteFailure,
  capabilityWriteMessage,
  groupCapabilities,
  needsWording
} from './capability-rows'

const capability = (overrides: Partial<Capability> = {}): Capability => ({
  id: 'skill:invoicing',
  kind: 'skill',
  name: 'invoicing',
  label: 'invoicing',
  description: 'Draft invoices and keep the records behind them.',
  group: 'pantler',
  enabled: true,
  toggleable: true,
  reason: null,
  applied_at: 'new_conversations',
  needs: [],
  provenance: 'shipped',
  ...overrides
})

describe('capabilityRow', () => {
  it('draws a switch for a toggleable row, and claims only the next conversation', () => {
    const row = capabilityRow(capability())

    expect(row.switchable).toBe(true)
    expect(row.reason).toBeNull()
    expect(row.on).toBe(true)
    expect(row.applies).toBe('takes effect from your next conversation')
    expect(row.restartRequired).toBe(false)
  })

  it('shows the reason instead of a switch when the registry says it is not toggleable', () => {
    const row = capabilityRow(
      capability({
        id: 'connector:composio',
        kind: 'connector',
        name: 'composio',
        toggleable: false,
        reason: 'no connector is wired yet; a card gains a switch when one is'
      })
    )

    expect(row.switchable).toBe(false)
    expect(row.reason).toBe('no connector is wired yet; a card gains a switch when one is')
  })

  it('still refuses a switch when a non-toggleable row gives no reason', () => {
    const row = capabilityRow(capability({ toggleable: false, reason: null }))

    expect(row.switchable).toBe(false)
    expect(row.reason).toBeTruthy()
  })

  it('says a restart is a restart, so the row cannot read as a live switch', () => {
    const row = capabilityRow(capability({ id: 'plugin:pantler', kind: 'plugin', applied_at: 'next_restart' }))

    expect(row.restartRequired).toBe(true)
    expect(row.applies).toContain('restart')
    expect(row.applies).not.toContain('next conversation')
  })

  it('does not round an unfamiliar timing to the friendlier one', () => {
    const row = capabilityRow(
      capability({ applied_at: 'next_discovery' as unknown as CapabilityAppliedAt })
    )

    expect(row.restartRequired).toBe(false)
    expect(row.applies).not.toContain('next conversation')
    expect(row.applies).toContain('next_discovery')
  })

  it('draws the switch for an MCP server, whose id prefix is its whole kind', () => {
    const row = capabilityRow(
      capability({
        id: 'mcp_server:notion',
        kind: 'mcp_server',
        name: 'notion',
        label: 'notion',
        applied_at: 'next_restart'
      })
    )

    expect(row.switchable).toBe(true)
    expect(row.reason).toBeNull()
    expect(row.restartRequired).toBe(true)
    expect(row.applies).toBe('takes effect after a restart')
  })

  it('refuses a switch when the id does not name the kind the server dispatches on', () => {
    // The registry served `mcp:airtable` with `kind: mcp_server` until it was fixed, and the
    // writer partitions the id, so that switch answered 400. The guard is the defence against the
    // two sides drifting again: no switch is drawn, and the row says why.
    const row = capabilityRow(
      capability({ id: 'mcp:airtable', kind: 'mcp_server', name: 'airtable', applied_at: 'next_restart' })
    )

    expect(row.switchable).toBe(false)
    expect(row.reason).toContain('mcp:airtable')
    expect(row.reason).toContain('mcp_server')
  })
})

describe('needsWording', () => {
  it('says a required credential is a key, by name', () => {
    expect(needsWording(['credential:PANTRY_API_KEY'])).toEqual(['needs a key: PANTRY_API_KEY'])
  })

  it('says an optional credential may be needed rather than needed', () => {
    const [line] = needsWording(['credential:WEATHER_KEY?'])
    expect(line).toBe('may need a key: WEATHER_KEY')
    expect(line.startsWith('needs ')).toBe(false)
  })

  it('says an account and extra software in the operator’s words', () => {
    expect(needsWording(['auth'])).toEqual(['needs an account'])
    expect(needsWording(['dependencies'])).toEqual(['needs extra software'])
  })

  it('says a need it does not know rather than dropping it', () => {
    expect(needsWording(['instance:url'])).toEqual(['needs instance:url'])
  })

  it('has nothing to say about a capability that needs nothing', () => {
    expect(needsWording([])).toEqual([])
  })

  it('does not invent a name for an empty need', () => {
    expect(needsWording([''])).toEqual(['needs something the registry did not name'])
  })
})

describe('groupCapabilities', () => {
  it('reads kind, then group, then label', () => {
    const blocks = groupCapabilities([
      capability({ id: 'connector:composio', kind: 'connector', name: 'composio', group: 'Connectors' }),
      capability({ id: 'skill:zeta', name: 'zeta', label: 'zeta', group: 'General' }),
      capability(),
      capability({ id: 'plugin:pantler', kind: 'plugin', name: 'pantler', group: 'Plugins' }),
      capability({ id: 'skill:alpha', name: 'alpha', label: 'alpha', group: 'General' }),
      capability({ id: 'mcp:airtable', kind: 'mcp_server', name: 'airtable', group: 'MCP servers' })
    ])

    expect(blocks.map(block => block.kind)).toEqual(['skill', 'plugin', 'mcp_server', 'connector'])
    // The distribution's own group leads; the rest are alphabetical.
    expect(blocks[0].groups.map(group => group.group)).toEqual(['pantler', 'General'])
    expect(blocks[0].groups[0].rows.map(row => row.label)).toEqual(['invoicing'])
    expect(blocks[0].groups[1].rows.map(row => row.label)).toEqual(['alpha', 'zeta'])
  })

  it('lists a kind this build does not know rather than dropping it', () => {
    const blocks = groupCapabilities([
      capability({
        id: 'toolset:soil',
        kind: 'toolset' as unknown as CapabilityKind,
        name: 'soil',
        group: 'Tools'
      })
    ])

    expect(blocks).toHaveLength(1)
    expect(blocks[0].label).toBe('toolset')
    expect(blocks[0].groups[0].rows[0].name).toBe('soil')
  })

  it('has nothing to group when the profile holds nothing', () => {
    expect(groupCapabilities([])).toEqual([])
  })
})

describe('capabilityWriteMessage', () => {
  it('says a 404 means the row is stale, not that the click was wrong', () => {
    expect(capabilityWriteMessage({ status: 404, message: 'this profile holds no skill named ‘x’' })).toBe(
      'This profile no longer holds it. Reload the page to see what is there now.'
    )
  })

  it('says a 409 means there is nothing behind it to switch', () => {
    expect(capabilityWriteMessage({ status: 409, message: 'composio has no client wired yet' })).toBe(
      'There is nothing behind it to switch, so the server refused.'
    )
  })

  it('repeats the server for anything else, and never invents a reason', () => {
    expect(capabilityWriteMessage({ status: 422, message: 'skills.disabled is not a plain list' })).toBe(
      'skills.disabled is not a plain list'
    )
    expect(capabilityWriteMessage({ status: 500 })).toBe('The server answered HTTP 500.')
    expect(capabilityWriteMessage({})).toBe('The server could not be reached.')
  })
})

describe('capabilityWriteFailure', () => {
  it('reads the status and the words off a SeamError-shaped value', () => {
    expect(capabilityWriteFailure({ status: 409, code: 'not_toggleable', message: 'refused' })).toEqual({
      status: 409,
      message: 'refused'
    })
  })

  it('reads a plain Error, and a thrown string, without pretending either has a status', () => {
    expect(capabilityWriteFailure(new TypeError('socket hang up'))).toEqual({
      status: undefined,
      message: 'socket hang up'
    })
    expect(capabilityWriteFailure('no')).toEqual({ message: 'no' })
    expect(capabilityWriteFailure(null)).toEqual({})
  })
})
