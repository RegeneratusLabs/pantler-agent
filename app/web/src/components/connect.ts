/**
 * A connection offer, read out of a tool result.
 *
 * The engine's connector tool (`manage_connections`) answers with a JSON envelope whose `targets`
 * carry a `connect_url` when an app still needs to be authorised:
 *
 * ```json
 * {"targets": [{"name": "shopify", "kind": "connector", "action": "connect",
 *               "state": "initiated", "connect_url": "https://portal…/connect/UnzE54ZHIJO9"}],
 *  "status": "initiated"}
 * ```
 *
 * **VERIFIED** against a live run on 2026-10-15 (`output/connector-probe/`), which is why this is a
 * parser and not a guess. The `note` in the same envelope is deliberately *not* read: it is written
 * to the model — *"Show each connect_url to the user; they open it in a browser to authorize…"* —
 * and printing instructions to a language model at an operator is the failure this app keeps
 * fixing.
 *
 * The one safety rule lives here rather than in the component: **a URL only becomes an offer if it
 * is an absolute `http(s)` address.** A tool result is untrusted text (the engine even wraps some
 * of them in `<untrusted_tool_result>`), so a `javascript:` or `data:` address in that slot must
 * never reach an `href` on a button. Everything else in the envelope is ignored rather than
 * guessed at — no offers means the call renders as the activity line it is.
 */

import { embeddedJson } from './tool-result'

/** The engine's connector tool. The name is checked, so a future tool cannot inherit this card. */
export const CONNECT_TOOL = 'manage_connections'

export interface ConnectOffer {
  /** The connector slug, as the gateway names it. */
  name: string
  /** What to call it on a button. */
  label: string
  /** Where the operator authorises it. Absolute `http(s)` only. */
  url: string
}

/**
 * Every app in a tool result that is waiting to be authorised, in the order the engine listed it.
 *
 * Empty for anything that is not a connection offer — the wrong tool, prose, a malformed envelope,
 * a result whose targets are already connected, or a URL this will not put on a button.
 */
export function connectOffers(result: string | undefined): ConnectOffer[] {
  const parsed = embeddedJson(result)
  if (!isRecord(parsed)) return []
  const targets = parsed.targets
  if (!Array.isArray(targets)) return []

  const offers: ConnectOffer[] = []
  const seen = new Set<string>()

  for (const target of targets) {
    if (!isRecord(target)) continue
    const name = typeof target.name === 'string' ? target.name.trim() : ''
    const url = httpUrl(target.connect_url)
    if (!name || !url || seen.has(url)) continue
    seen.add(url)
    offers.push({ name, label: connectorLabel(name), url })
  }

  return offers
}

/**
 * What to call a connector on screen.
 *
 * The gateway's slugs are Composio's, so they are lower-case and underscore-joined. A generic
 * title-case is right for most of them (`supabase` → Supabase) and wrong for the handful whose own
 * spelling is not mechanical — which is the whole reason for the table.
 */
export function connectorLabel(slug: string): string {
  const key = (slug ?? '').trim().toLowerCase().replace(/_mcp$/, '')
  if (!key) return slug ?? ''

  const known = CONNECTOR_NAMES[key]
  if (known) return known

  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

const CONNECTOR_NAMES: Record<string, string> = {
  gmail: 'Gmail',
  gdrive: 'Google Drive',
  googledrive: 'Google Drive',
  googlecalendar: 'Google Calendar',
  googlesheets: 'Google Sheets',
  woocommerce: 'WooCommerce',
  shopify: 'Shopify',
  square: 'Square',
  xero: 'Xero',
  mailchimp: 'Mailchimp',
  facebook: 'Facebook',
  instagram: 'Instagram',
  hubspot: 'HubSpot',
  sendgrid: 'SendGrid',
  clickup: 'ClickUp',
  clickhouse: 'ClickHouse',
  posthog: 'PostHog',
  coinbase: 'Coinbase',
  coinbase_wallet: 'Coinbase Wallet',
  customerio: 'Customer.io',
  better_stack: 'Better Stack',
  wispr_flow: 'Wispr Flow',
  adobe_marketing_agent: 'Adobe Marketing Agent',
  ahrefs: 'Ahrefs',
  discordbot: 'Discord',
  amazon: 'Amazon',
  ebay: 'eBay',
  paypal: 'PayPal',
  youtube: 'YouTube',
  linkedin: 'LinkedIn',
  tiktok: 'TikTok'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** An absolute `http(s)` URL, or undefined. Anything else is not put on a button. */
function httpUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  if (!/^https?:\/\/[^\s]+$/i.test(text)) return undefined
  try {
    const parsed = new URL(text)
    return parsed.hostname ? text : undefined
  } catch {
    return undefined
  }
}
