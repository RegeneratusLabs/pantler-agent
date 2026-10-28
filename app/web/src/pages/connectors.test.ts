import { describe, expect, it } from 'vitest'
import {
  CONNECTORS,
  CONNECTOR_CATEGORIES,
  CONNECTOR_PLATFORM,
  safeConnectUrl,
  tintOf
} from './connectors'

/**
 * What the catalogue promises, checked.
 *
 * The section makes two countable claims — *these twenty* and *five groups* — and one visual
 * one: every card has a mark in the brand's own colour. All are easy to break by editing the
 * list and none would fail a typecheck, so they are asserted here.
 */
describe('the connector catalogue', () => {
  it('lists twenty, one of each, with nothing repeated', () => {
    expect(CONNECTORS).toHaveLength(20)
    expect(new Set(CONNECTORS.map(connector => connector.id)).size).toBe(20)
    expect(new Set(CONNECTORS.map(connector => connector.name)).size).toBe(20)
    expect(new Set(CONNECTORS.map(connector => connector.slug)).size).toBe(20)
  })

  it('has something to say about every one of them', () => {
    for (const connector of CONNECTORS) {
      expect(connector.slug.length).toBeGreaterThan(0)
      expect(connector.name.length).toBeGreaterThan(0)
      expect(connector.kind.length).toBeGreaterThan(0)
      expect(connector.blurb.length).toBeGreaterThan(20)
      expect(tintOf(connector.color)).not.toBe('transparent')
    }
  })

  it('groups the twenty as 2 / 2 / 6 / 5 / 5', () => {
    const counts = CONNECTOR_CATEGORIES.map(category => ({
      id: category.id,
      count: CONNECTORS.filter(connector => connector.category === category.id).length
    }))
    expect(counts).toEqual([
      { id: 'selling', count: 2 },
      { id: 'money', count: 2 },
      { id: 'workspace', count: 6 },
      { id: 'marketing', count: 5 },
      { id: 'operations', count: 5 }
    ])
    for (const connector of CONNECTORS) {
      expect(CONNECTOR_CATEGORIES.some(category => category.id === connector.category)).toBe(true)
    }
  })

  it('keeps the food-business core and drops the removed entries', () => {
    const ids = CONNECTORS.map(connector => connector.id)
    for (const wanted of ['square', 'stripe', 'quickbooks', 'zoho_books']) {
      expect(ids).toContain(wanted)
    }
    for (const wanted of ['gmail', 'outlook', 'gdrive', 'gdocs', 'gsheets', 'gcal']) {
      expect(ids).toContain(wanted)
    }
    for (const wanted of ['mailchimp', 'facebook', 'instagram', 'canva', 'hubspot']) {
      expect(ids).toContain(wanted)
    }
    for (const wanted of ['whatsapp', 'eventbrite', 'calendly', 'shippo', 'google_maps']) {
      expect(ids).toContain(wanted)
    }
    for (const removed of ['shopify', 'paypal', 'xero', 'woocommerce', 'clover', '7shifts']) {
      expect(ids).not.toContain(removed)
    }
  })

  it('names a real documentation link and no key field', () => {
    expect(CONNECTOR_PLATFORM.url.startsWith('https://')).toBe(true)
    expect(CONNECTOR_PLATFORM.blurb).toMatch(/Composio/)
    expect('keyUrl' in CONNECTOR_PLATFORM).toBe(false)
  })
})

describe('tintOf', () => {
  it('turns a brand hex into a translucent fill', () => {
    expect(tintOf('#1877f2')).toBe('rgba(24, 119, 242, 0.14)')
    expect(tintOf('#FFFFFF', 0.5)).toBe('rgba(255, 255, 255, 0.5)')
    expect(tintOf('#000000', 0)).toBe('rgba(0, 0, 0, 0)')
  })

  it('refuses anything that is not a six-digit colour', () => {
    // It goes into a `style` attribute, so a value that is not a colour must become nothing.
    expect(tintOf('red')).toBe('transparent')
    expect(tintOf('#fff')).toBe('transparent')
    expect(tintOf('url(javascript:alert(1))')).toBe('transparent')
    expect(tintOf('')).toBe('transparent')
  })

  it('clamps an alpha that is not one', () => {
    expect(tintOf('#123456', 4)).toBe('rgba(18, 52, 86, 1)')
    expect(tintOf('#123456', -1)).toBe('rgba(18, 52, 86, 0)')
  })
})

describe('safeConnectUrl', () => {
  it('lets a Composio https link through', () => {
    expect(safeConnectUrl('https://connect.composio.dev/link/abc')).toBe(
      'https://connect.composio.dev/link/abc'
    )
    expect(safeConnectUrl('https://composio.dev/link/abc')).toBe('https://composio.dev/link/abc')
  })

  it('refuses anything that is not Composio’s own https address', () => {
    // A tool result and an API answer are both untrusted text; neither becomes an href.
    expect(safeConnectUrl('javascript:alert(1)')).toBeNull()
    expect(safeConnectUrl('http://connect.composio.dev/link/abc')).toBeNull()
    expect(safeConnectUrl('https://evil.example/link/abc')).toBeNull()
    expect(safeConnectUrl('https://composio.dev.evil.example/link')).toBeNull()
    expect(safeConnectUrl(null)).toBeNull()
    expect(safeConnectUrl('')).toBeNull()
  })
})
