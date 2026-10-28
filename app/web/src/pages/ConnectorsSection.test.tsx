// @vitest-environment jsdom
/**
 * The Connectors section, as the operator reads it.
 *
 * The state comes from the BFF, so these tests mock the data hook and the BFF client. The things
 * worth holding: twenty grouped rows, no key field anywhere, an unconfigured screen that does not
 * ask for a key, a connected tile that says what the server said, a pending tile that keeps
 * waiting, and a disconnect that asks first.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConnectorStatus, ConnectorsResponse } from '@shared/wire'

const mocks = vi.hoisted(() => ({
  data: null as ConnectorsResponse | null,
  isPending: false,
  error: null as unknown,
  connectConnector: vi.fn(),
  disconnectConnector: vi.fn()
}))

vi.mock('../state/app-context', () => ({
  qk: { connectors: ['connectors'] },
  useConnectors: () => ({
    data: mocks.data,
    isPending: mocks.isPending,
    error: mocks.error
  }),
  useApp: () => ({
    bff: {
      connectConnector: mocks.connectConnector,
      disconnectConnector: mocks.disconnectConnector
    }
  })
}))

const { ConnectorsSection } = await import('./ConnectorsSection')

const CATALOGUE: [string, string][] = [
  ['square', 'Square'],
  ['stripe', 'Stripe'],
  ['quickbooks', 'QuickBooks'],
  ['zoho_books', 'Zoho Books'],
  ['gmail', 'Gmail'],
  ['outlook', 'Outlook'],
  ['gdrive', 'Google Drive'],
  ['gdocs', 'Google Docs'],
  ['gsheets', 'Google Sheets'],
  ['gcal', 'Google Calendar'],
  ['mailchimp', 'Mailchimp'],
  ['facebook', 'Facebook'],
  ['instagram', 'Instagram'],
  ['canva', 'Canva'],
  ['hubspot', 'HubSpot'],
  ['whatsapp', 'WhatsApp'],
  ['eventbrite', 'Eventbrite'],
  ['calendly', 'Calendly'],
  ['shippo', 'Shippo'],
  ['google_maps', 'Google Maps']
]

const NOTES: Record<string, string> = {
  facebook: 'Needs a Facebook Page, not a personal profile.',
  instagram: 'Needs a Business or Creator account.',
  whatsapp: 'Needs a WhatsApp Business account and a phone number.'
}

const row = (overrides: Partial<ConnectorStatus> = {}): ConnectorStatus => ({
  id: 'gmail',
  name: 'Gmail',
  slug: 'gmail',
  available: true,
  managed_oauth: true,
  note: '',
  state: 'not_connected',
  account: null,
  can_connect: true,
  reason: null,
  ...overrides
})

const twentyRows = (overrides: Partial<ConnectorStatus> = {}): ConnectorStatus[] =>
  CATALOGUE.map(([id, name]) =>
    row({
      id,
      name,
      slug: id,
      note: NOTES[id] ?? '',
      ...(id === 'gmail' ? overrides : {})
    })
  )

const response = (partial: Partial<ConnectorsResponse> = {}): ConnectorsResponse => ({
  available: true,
  configured: true,
  error: null,
  connectors: twentyRows(),
  ...partial
})

const renderSection = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  return render(
    <QueryClientProvider client={client}>
      <ConnectorsSection />
    </QueryClientProvider>
  )
}

const tile = (name: string): HTMLElement => {
  const found = screen.getByText(name).closest('li')
  if (!found) throw new Error(`no tile for ${name}`)
  return found as HTMLElement
}

beforeEach(() => {
  mocks.data = response()
  mocks.isPending = false
  mocks.error = null
  mocks.connectConnector.mockReset()
  mocks.disconnectConnector.mockReset()
  mocks.connectConnector.mockResolvedValue({
    connector: 'gmail',
    state: 'pending',
    account: null,
    connect_url: 'https://connect.composio.dev/link/abc',
    connected_account_id: 'ca_1',
    expires_at: null
  })
  mocks.disconnectConnector.mockResolvedValue({
    connector: 'gmail',
    disconnected: 1,
    state: 'not_connected'
  })
  vi.spyOn(window, 'open').mockImplementation(() => null)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ConnectorsSection', () => {
  it('draws the twenty rows in five groups with no key field and no switch', () => {
    const { container } = renderSection()

    expect(screen.getAllByRole('listitem')).toHaveLength(20)
    for (const label of [
      'Selling & takings',
      'Money',
      'Workspace',
      'Marketing & social',
      'Operations & customers'
    ]) {
      expect(screen.getByText(label)).toBeTruthy()
    }
    expect(screen.queryByLabelText(/project key/i)).toBeNull()
    expect(container.querySelector('input[type=password]')).toBeNull()
    expect(container.querySelectorAll('input[type=checkbox]')).toHaveLength(0)
  })

  it('points at the backend, not a key field, when nothing is configured', () => {
    mocks.data = response({
      configured: false,
      connectors: twentyRows({ can_connect: false, reason: 'Connectors are not set up on this machine.' })
    })
    renderSection()

    expect(screen.getByText('Connectors are not set up on this machine.')).toBeTruthy()
    expect(screen.getByText(/The backend provides it/)).toBeTruthy()
    expect(screen.queryByLabelText(/project key/i)).toBeNull()
    expect(within(tile('Gmail')).getByText('Not set up')).toBeTruthy()
    expect(within(tile('Gmail')).queryByRole('button', { name: /connect/i })).toBeNull()
  })

  it('shows what the server said, and never invents a connection', () => {
    mocks.data = response({
      connectors: twentyRows({
        state: 'connected',
        account: {
          id: 'ca_gmail',
          status: 'ACTIVE',
          status_reason: '',
          display_name: 'orders@bellview.example',
          created_at: '',
          toolkit: 'gmail'
        }
      })
    })
    renderSection()

    expect(screen.getByText('1 of 20 connected')).toBeTruthy()
    const gmail = tile('Gmail')
    expect(within(gmail).getByText('Connected')).toBeTruthy()
    expect(within(gmail).getByText('orders@bellview.example')).toBeTruthy()
  })

  it('keeps a pending tile waiting, with a check rather than a checkmark', () => {
    mocks.data = response({ connectors: twentyRows({ state: 'pending' }) })
    renderSection()

    const gmail = tile('Gmail')
    expect(within(gmail).getByText('Waiting')).toBeTruthy()
    expect(within(gmail).getByText('Waiting for sign-in')).toBeTruthy()
    expect(within(gmail).queryByText('Connected')).toBeNull()
    expect(within(gmail).getByRole('button', { name: /check gmail/i })).toBeTruthy()
  })

  it('opens the sign-in link and leaves the row pending until Composio says otherwise', async () => {
    renderSection()

    fireEvent.click(within(tile('Gmail')).getByRole('button', { name: /connect gmail/i }))

    await waitFor(() => expect(mocks.connectConnector).toHaveBeenCalledWith('gmail'))
    await waitFor(() => {
      expect(window.open).toHaveBeenCalledWith(
        'https://connect.composio.dev/link/abc',
        '_blank',
        'noopener,noreferrer'
      )
    })
    await waitFor(() =>
      expect(within(tile('Gmail')).getByRole('link', { name: /sign in/i })).toBeTruthy()
    )
    expect(within(tile('Gmail')).queryByText('Connected')).toBeNull()
  })

  it('asks before disconnecting', async () => {
    mocks.data = response({ connectors: twentyRows({ state: 'connected' }) })
    renderSection()

    fireEvent.click(within(tile('Gmail')).getByRole('button', { name: /disconnect gmail/i }))
    expect(screen.getByText(/Disconnect Gmail\?/)).toBeTruthy()
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^disconnect$/i }))

    await waitFor(() => expect(mocks.disconnectConnector).toHaveBeenCalledWith('gmail'))
  })

  it('states an account requirement without calling a managed connector setup', () => {
    renderSection()

    const facebook = tile('Facebook')
    expect(within(facebook).getByText(/Facebook Page/)).toBeTruthy()
    expect(within(facebook).queryByText('setup')).toBeNull()
  })

  it('shows the server’s error instead of a dead grid', () => {
    mocks.data = response({
      error: { code: 'bad_key', message: 'Composio refused the backend key.' },
      connectors: twentyRows({ can_connect: false, reason: 'Composio refused the backend key.' })
    })
    renderSection()

    expect(screen.getByText('Composio refused the backend key.')).toBeTruthy()
  })
})
