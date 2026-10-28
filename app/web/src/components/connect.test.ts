import { describe, expect, it } from 'vitest'
import { connectOffers, connectorLabel } from './connect'

/**
 * The connection offer, against the real envelope.
 *
 * The fixture is the verbatim result of a live `manage_connections` call on 2026-10-15 (kept in
 * `output/connector-probe/messages2.json`), shortened only where it says so. A parser tested
 * against a shape somebody imagined is how a Connect button ends up never rendering.
 */
const LIVE = JSON.stringify({
  op_id: '194ab7c9b1ab',
  seq: 1,
  deadline_at: 1792040876.5861413,
  settled_at: null,
  settled_by: null,
  targets: [
    {
      name: 'shopify',
      kind: 'connector',
      action: 'connect',
      state: 'initiated',
      connect_url: 'https://portal.nousresearch.com/connect/UnzE54ZHIJO9'
    }
  ],
  status: 'initiated',
  note: 'Show each connect_url to the user; they open it in a browser to authorize. Ask them to tell you when they are done, then check with action \u0027status\u0027. Do not call connect again for the same app.'
})

describe('connectOffers', () => {
  it('reads the live envelope', () => {
    expect(connectOffers(LIVE)).toEqual([
      {
        name: 'shopify',
        label: 'Shopify',
        url: 'https://portal.nousresearch.com/connect/UnzE54ZHIJO9'
      }
    ])
  })

  it('reads it out of the transcript’s untrusted-result wrapper too', () => {
    // A resumed transcript wraps the same JSON, which is why `embeddedJson` takes a span.
    const wrapped = `<untrusted_tool_result source="manage_connections">\n${LIVE}\n</untrusted_tool_result>`
    expect(connectOffers(wrapped)).toHaveLength(1)
  })

  it('reads several apps in the order the engine listed them', () => {
    const two = JSON.stringify({
      targets: [
        { name: 'gmail', connect_url: 'https://portal.example/connect/a', state: 'initiated' },
        { name: 'xero', connect_url: 'https://portal.example/connect/b', state: 'initiated' }
      ]
    })
    expect(connectOffers(two).map(offer => offer.label)).toEqual(['Gmail', 'Xero'])
  })

  it('offers nothing for a target that is already connected, or has no address', () => {
    expect(
      connectOffers(JSON.stringify({ targets: [{ name: 'slack', state: 'connected' }] }))
    ).toEqual([])
    expect(
      connectOffers(JSON.stringify({ targets: [{ name: 'slack', connect_url: '' }] }))
    ).toEqual([])
  })

  it('never puts an address that is not http(s) on a button', () => {
    // The result is untrusted text. A `javascript:` URL in that slot is the whole reason this
    // rule lives in the parser rather than in the component.
    const hostile = JSON.stringify({
      targets: [
        { name: 'evil', connect_url: 'javascript:alert(1)' },
        { name: 'data', connect_url: 'data:text/html,<script>x</script>' },
        { name: 'relative', connect_url: '/connect/abc' },
        { name: 'scheme', connect_url: 'pantler-placeholder://oauth/callback' },
        { name: 'good', connect_url: 'https://portal.example/connect/ok' }
      ]
    })
    expect(connectOffers(hostile)).toEqual([
      { name: 'good', label: 'Good', url: 'https://portal.example/connect/ok' }
    ])
  })

  it('offers nothing for another tool’s result, prose, or nothing at all', () => {
    expect(connectOffers(JSON.stringify({ connectors: [], hint: 'nothing connected' }))).toEqual([])
    expect(connectOffers('I connected your shop.')).toEqual([])
    expect(connectOffers(JSON.stringify({ targets: 'shopify' }))).toEqual([])
    expect(connectOffers(undefined)).toEqual([])
    expect(connectOffers('')).toEqual([])
  })

  it('keeps one button when the same address appears twice', () => {
    const twice = JSON.stringify({
      targets: [
        { name: 'shopify', connect_url: 'https://portal.example/connect/a' },
        { name: 'shopify', connect_url: 'https://portal.example/connect/a' }
      ]
    })
    expect(connectOffers(twice)).toHaveLength(1)
  })
})

describe('connectorLabel', () => {
  it('uses the connector’s own spelling where title-case would be wrong', () => {
    expect(connectorLabel('woocommerce')).toBe('WooCommerce')
    expect(connectorLabel('googledrive')).toBe('Google Drive')
    expect(connectorLabel('googlecalendar')).toBe('Google Calendar')
    expect(connectorLabel('hubspot')).toBe('HubSpot')
    expect(connectorLabel('sendgrid')).toBe('SendGrid')
    expect(connectorLabel('discordbot')).toBe('Discord')
  })

  it('strips the catalogue’s mcp suffix and title-cases the rest', () => {
    expect(connectorLabel('stripe_mcp')).toBe('Stripe')
    expect(connectorLabel('canva_mcp')).toBe('Canva')
    expect(connectorLabel('supabase')).toBe('Supabase')
    expect(connectorLabel('peopledatalabs')).toBe('Peopledatalabs')
    expect(connectorLabel('better_stack_mcp')).toBe('Better Stack')
  })

  it('does not fall over on an empty or odd slug', () => {
    expect(connectorLabel('')).toBe('')
    expect(connectorLabel('   ')).toBe('   ')
  })
})
