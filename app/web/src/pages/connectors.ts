/**
 * The connectors — the apps a small food business already runs on, in the operator's words.
 *
 * This file is the **display catalogue**: the twenty names, their kind, their copy, their colour,
 * their group and their mark. It is not the connection state and it is not the wiring. The BFF
 * owns the catalogue's capability half — `available`, `managed_oauth` and the setup note — and
 * `GET /api/connectors` answers what is actually connected. `ConnectorsSection` renders that
 * answer beside each entry. The ids, slugs and names here are checked against the BFF's catalogue
 * in `app/server/tests/test_connectors.py`, so the two cannot drift.
 *
 * **Composio is the layer underneath**, and that is a product decision rather than a detail: one
 * authenticated connection that carries every app below, instead of this app holding a password
 * for each one. It is also a third-party surface — the tools it exposes are not ours — which is
 * why the card states what it is and where its own documentation lives.
 */

/** The group a connector is listed under. The order here is the order on the screen. */
export type ConnectorCategory = 'selling' | 'money' | 'workspace' | 'marketing' | 'operations'

export const CONNECTOR_CATEGORIES: readonly { id: ConnectorCategory; label: string }[] = [
  { id: 'selling', label: 'Selling & takings' },
  { id: 'money', label: 'Money' },
  { id: 'workspace', label: 'Workspace' },
  { id: 'marketing', label: 'Marketing & social' },
  { id: 'operations', label: 'Operations & customers' }
]

export interface Connector {
  id: string
  /** The toolkit slug Composio uses. The BFF validates against the same pair. */
  slug: string
  /** The name on the tin. */
  name: string
  /** What an operator would call it, in three or four words. */
  kind: string
  /** What connecting it would let the assistant do — one line, no promises about how. */
  blurb: string
  /** The brand's own colour, tuned to stay legible on both themes. */
  color: string
  /** The group it is listed under. */
  category: ConnectorCategory
}

export const CONNECTORS: Connector[] = [
  {
    id: 'square',
    slug: 'square',
    name: 'Square',
    kind: 'Till and card payments',
    blurb: 'Bring the day’s takings and the item list across from the till.',
    color: '#8a8f98',
    category: 'selling'
  },
  {
    id: 'stripe',
    slug: 'stripe',
    name: 'Stripe',
    kind: 'Online payments',
    blurb: 'Take a payment or send an invoice without leaving the conversation.',
    color: '#635bff',
    category: 'selling'
  },
  {
    id: 'quickbooks',
    slug: 'quickbooks',
    name: 'QuickBooks',
    kind: 'Accounts',
    blurb: 'Invoices, bills and who owes what, for a QuickBooks business.',
    color: '#2ca01c',
    category: 'money'
  },
  {
    id: 'zoho_books',
    slug: 'zoho_books',
    name: 'Zoho Books',
    kind: 'Accounts',
    blurb: 'Invoices, bills and who owes what, for a Zoho Books business.',
    color: '#e42527',
    category: 'money'
  },
  {
    id: 'gmail',
    slug: 'gmail',
    name: 'Gmail',
    kind: 'Email',
    blurb: 'Read a supplier’s reply, and draft one back from your own address.',
    color: '#e05545',
    category: 'workspace'
  },
  {
    id: 'outlook',
    slug: 'outlook',
    name: 'Outlook',
    kind: 'Email and calendar',
    blurb: 'Read mail and see the diary for a Microsoft 365 business.',
    color: '#0078d4',
    category: 'workspace'
  },
  {
    id: 'gdrive',
    slug: 'googledrive',
    name: 'Google Drive',
    kind: 'Documents',
    blurb: 'The folders the paperwork already lives in — agreements, labels, records.',
    color: '#1a9e63',
    category: 'workspace'
  },
  {
    id: 'gdocs',
    slug: 'googledocs',
    name: 'Google Docs',
    kind: 'Documents',
    blurb: 'Menus, labels, agreements and records you keep as documents.',
    color: '#4285f4',
    category: 'workspace'
  },
  {
    id: 'gsheets',
    slug: 'googlesheets',
    name: 'Google Sheets',
    kind: 'Stock and orders',
    blurb: 'Orders, stock counts and market planning in a spreadsheet.',
    color: '#0f9d58',
    category: 'workspace'
  },
  {
    id: 'gcal',
    slug: 'googlecalendar',
    name: 'Google Calendar',
    kind: 'Calendar',
    blurb: 'Deliveries, markets and pickups, put where you will actually see them.',
    color: '#4285f4',
    category: 'workspace'
  },
  {
    id: 'mailchimp',
    slug: 'mailchimp',
    name: 'Mailchimp',
    kind: 'Newsletter',
    blurb: 'Tell the list what is in season, and keep the customers who asked.',
    color: '#b88700',
    category: 'marketing'
  },
  {
    id: 'facebook',
    slug: 'facebook',
    name: 'Facebook',
    kind: 'Page and messages',
    blurb: 'Draft a page post, or answer a message that came in about an order.',
    color: '#1877f2',
    category: 'marketing'
  },
  {
    id: 'instagram',
    slug: 'instagram',
    name: 'Instagram',
    kind: 'Posts and messages',
    blurb: 'Post a photo of what is ready this week, and read the replies.',
    color: '#d9425f',
    category: 'marketing'
  },
  {
    id: 'canva',
    slug: 'canva',
    name: 'Canva',
    kind: 'Menus and graphics',
    blurb: 'Menus, price cards and social images without a designer.',
    color: '#00c4cc',
    category: 'marketing'
  },
  {
    id: 'hubspot',
    slug: 'hubspot',
    name: 'HubSpot',
    kind: 'Customers',
    blurb: 'Keep customer details, deals and follow-ups in one place.',
    color: '#ff7a59',
    category: 'marketing'
  },
  {
    id: 'whatsapp',
    slug: 'whatsapp',
    name: 'WhatsApp',
    kind: 'Customer messages',
    blurb: 'Answer orders and questions on the number customers already have.',
    color: '#25d366',
    category: 'operations'
  },
  {
    id: 'eventbrite',
    slug: 'eventbrite',
    name: 'Eventbrite',
    kind: 'Markets and events',
    blurb: 'List a market, workshop or tasting and see who is coming.',
    color: '#f05537',
    category: 'operations'
  },
  {
    id: 'calendly',
    slug: 'calendly',
    name: 'Calendly',
    kind: 'Pickups and bookings',
    blurb: 'Let customers book a pickup, tour or consultation.',
    color: '#006bff',
    category: 'operations'
  },
  {
    id: 'shippo',
    slug: 'shippo',
    name: 'Shippo',
    kind: 'Shipping',
    blurb: 'Buy a label and track a box for an online order.',
    color: '#4f46e5',
    category: 'operations'
  },
  {
    id: 'google_maps',
    slug: 'google_maps',
    name: 'Google Maps',
    kind: 'Delivery and places',
    blurb: 'Plan a delivery round and see where customers are.',
    color: '#ea4335',
    category: 'operations'
  }
]

/**
 * The connector layer, described in the same breath as the list because it is what makes the list
 * possible: one place the operator authenticates, rather than ten passwords in a settings file.
 */
export interface ConnectorPlatform {
  name: string
  /** Where its own documentation is. The one link in this section, and it is real. */
  url: string
  blurb: string
}

export const CONNECTOR_PLATFORM: ConnectorPlatform = {
  name: 'Composio',
  url: 'https://composio.dev/developers',
  blurb:
    'Connected through Composio. Using an app sends the request to Composio and then the app.'
}

/**
 * A sign-in link, only if it is Composio's own https address.
 *
 * The BFF already refuses anything else (`connectors.py::_safe_connect_url`), and this is the
 * second gate: a value from an API response is still not allowed to become an `href` just
 * because it arrived over loopback. A popup-blocked tile keeps an anchor, so this is the one
 * place the link is put in front of the operator.
 */
export function safeConnectUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:') return null
    const host = url.hostname.toLowerCase()
    return host === 'composio.dev' || host.endsWith('.composio.dev') ? value : null
  } catch {
    return null
  }
}

/**
 * A brand colour as a translucent fill, for a tile's background.
 *
 * Six-digit hex only, and anything else is returned as `transparent` rather than as a broken
 * colour: this is fed straight into a `style` attribute, so a value that is not a colour must
 * degrade to nothing rather than to whatever the browser makes of it.
 */
export function tintOf(color: string, alpha = 0.14): string {
  const match = /^#([0-9a-f]{6})$/i.exec((color ?? '').trim())
  if (!match) return 'transparent'
  const value = Number.parseInt(match[1], 16)
  const red = (value >> 16) & 0xff
  const green = (value >> 8) & 0xff
  const blue = value & 0xff
  const clamped = Math.min(Math.max(alpha, 0), 1)
  return `rgba(${red}, ${green}, ${blue}, ${clamped})`
}
