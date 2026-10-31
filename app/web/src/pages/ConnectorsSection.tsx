import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, PlugZap, RefreshCw, Unplug } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { ConnectorStatus } from '@shared/wire'
import { qk, useApp, useConnectors } from '../state/app-context'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { ConfirmDialog } from '../ui/dialog'
import {
  CONNECTORS,
  CONNECTOR_CATEGORIES,
  CONNECTOR_PLATFORM,
  safeConnectUrl,
  tintOf,
  type Connector
} from './connectors'

/**
 * Connectors — the apps outside this machine, in a compact grouped list.
 *
 * The section used to be ten large cards plus a platform card and an API-key form. The key is not
 * the operator's job — it is provisioned on the backend — and ten cards became twenty, so this is
 * a dense list: a mark, a name, a state, one line and one action. The five groups are the
 * categories a food business thinks in, not an alphabetical dump.
 *
 * The rules that survived the compression:
 *
 *   - **A row says what the service says.** `connected` is only Composio's `ACTIVE`; clicking
 *     Connect opens a sign-in tab and changes nothing else. No optimistic checkmark.
 *   - **No key, anywhere.** The page never renders a password input, never calls the settings
 *     write, and never asks the operator for a key. If the backend has none, it says so once.
 *   - **The limits are stated before the click.** The BFF's `managed_oauth` and `note` decide
 *     whether a row carries a small “setup” tag; the server repeats the reason if the click gets
 *     that far.
 *   - **Nothing is a switch.** Connecting is an account decision, not a capability toggle, so the
 *     section still draws no `<input type=checkbox>`.
 */
export function ConnectorsSection() {
  const { bff } = useApp()
  const queryClient = useQueryClient()
  const { data, isPending, error: queryError } = useConnectors()
  const [offers, setOffers] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<Record<string, boolean>>({})
  const [notice, setNotice] = useState<string | null>(null)
  const [disconnectTarget, setDisconnectTarget] = useState<ConnectorStatus | null>(null)

  const connect = useMutation({
    mutationFn: (id: string) => bff.connectConnector(id),
    onSuccess: result => {
      const connectUrl = safeConnectUrl(result.connect_url)
      if (connectUrl) {
        setOffers(previous => ({ ...previous, [result.connector]: connectUrl }))
        queryClient.setQueryData(qk.connectors, (previous: unknown) => {
          const typed = previous as { connectors?: ConnectorStatus[] } | undefined
          if (!typed?.connectors) return previous
          return {
            ...typed,
            connectors: typed.connectors.map(connector =>
              connector.id === result.connector
                ? { ...connector, state: result.state, can_connect: true, reason: null }
                : connector
            )
          }
        })
        // Best effort in the click's own gesture; the row keeps a real anchor if a popup
        // blocker refuses it, which is the only honest way to draw this.
        window.open(connectUrl, '_blank', 'noopener,noreferrer')
      } else if (result.connect_url) {
        setNotice('The connector service returned a sign-in link this page will not open.')
      }
      if (result.state === 'pending') {
        setPending(previous => ({ ...previous, [result.connector]: true }))
      }
      setNotice(
        result.state === 'connected'
          ? 'That app is already connected.'
          : 'Finish the sign-in in the browser tab. This page catches up on its own.'
      )
      void queryClient.invalidateQueries({ queryKey: qk.connectors })
    }
  })

  const disconnect = useMutation({
    mutationFn: (id: string) => bff.disconnectConnector(id),
    onSuccess: result => {
      setOffers(previous => {
        const next = { ...previous }
        delete next[result.connector]
        return next
      })
      setPending(previous => {
        const next = { ...previous }
        delete next[result.connector]
        return next
      })
      setNotice(
        result.disconnected > 0
          ? 'Disconnected. The assistant no longer has access to that app.'
          : 'That app was not connected.'
      )
      setDisconnectTarget(null)
      void queryClient.invalidateQueries({ queryKey: qk.connectors })
    }
  })

  const statuses = new Map<string, ConnectorStatus>(
    (data?.connectors ?? []).map(status => [status.id, status])
  )
  const configured = data?.configured === true
  const connected = (data?.connectors ?? []).filter(status => status.state === 'connected').length
  const serviceError = data?.error?.message ?? (queryError ? messageOf(queryError) : null)

  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="text-sm text-ink">
            {isPending
              ? 'Checking the connections…'
              : queryError
                ? 'Could not read the connections.'
                : configured
                  ? `${connected} of ${CONNECTORS.length} connected`
                  : 'Connectors are not set up on this machine.'}
          </p>
          <p className="text-[0.68rem] leading-relaxed text-ink-3">{CONNECTOR_PLATFORM.blurb}</p>
        </div>
        <a
          href={CONNECTOR_PLATFORM.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-xs text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent/70"
        >
          How it works
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
      </header>

      {!configured && !isPending && !queryError && (
        <p className="rounded-lg border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-ink-2">
          The connector service has no Composio project key. The backend provides it; this page
          never asks for one. The catalogue is shown so you can see what is available.
        </p>
      )}

      {serviceError && (
        <p className="rounded-lg border border-danger/40 bg-danger/[0.06] px-3 py-2 text-xs leading-relaxed text-danger">
          {serviceError}
        </p>
      )}

      {notice && (
        <p className="rounded-lg border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-ink-2">
          {notice}
        </p>
      )}

      <div className="flex flex-col gap-2.5">
        {CONNECTOR_CATEGORIES.map(category => {
          const rows = CONNECTORS.filter(connector => connector.category === category.id)
          if (rows.length === 0) return null
          return (
            <Card key={category.id} className="gap-0 overflow-hidden p-0">
              <div className="border-b border-line/60 px-3 py-1.5">
                <h3 className="text-display text-[0.65rem] text-ink-3">{category.label}</h3>
              </div>
              <ul className="grid sm:grid-cols-2">
                {rows.map(connector => {
                  const status = statuses.get(connector.id)
                  return (
                    <ConnectorRow
                      key={connector.id}
                      connector={connector}
                      status={status}
                      configured={configured}
                      loading={isPending}
                      offer={offers[connector.id]}
                      locallyPending={pending[connector.id] === true}
                      connecting={connect.isPending && connect.variables === connector.id}
                      connectError={
                        connect.isError && connect.variables === connector.id
                          ? messageOf(connect.error)
                          : null
                      }
                      onConnect={() => connect.mutate(connector.id)}
                      onCheck={() => void queryClient.invalidateQueries({ queryKey: qk.connectors })}
                      onDisconnect={status ? () => setDisconnectTarget(status) : undefined}
                    />
                  )
                })}
              </ul>
            </Card>
          )
        })}
      </div>

      <ConfirmDialog
        open={disconnectTarget !== null}
        title={`Disconnect ${disconnectTarget?.name ?? 'this app'}?`}
        description="The assistant loses access to it immediately. You can connect it again later, and the app's own account is not changed."
        confirmLabel="Disconnect"
        destructive
        busy={disconnect.isPending}
        error={disconnect.isError ? messageOf(disconnect.error) : undefined}
        onConfirm={() => {
          if (disconnectTarget) disconnect.mutate(disconnectTarget.id)
        }}
        onCancel={() => setDisconnectTarget(null)}
      />
    </section>
  )
}

function ConnectorRow({
  connector,
  status,
  configured,
  loading,
  offer,
  locallyPending,
  connecting,
  connectError,
  onConnect,
  onCheck,
  onDisconnect
}: {
  connector: Connector
  status: ConnectorStatus | undefined
  configured: boolean
  loading: boolean
  offer: string | undefined
  locallyPending: boolean
  connecting: boolean
  connectError: string | null
  onConnect: () => void
  onCheck: () => void
  onDisconnect?: () => void
}) {
  const state: ConnectorStatus['state'] =
    status?.state && status.state !== 'not_connected'
      ? status.state
      : locallyPending
        ? 'pending'
        : status?.state ?? 'not_connected'
  const unavailable = status?.available === false
  const needsSetup = configured && status?.managed_oauth === false && state !== 'connected'
  const canConnect = configured && !unavailable && (status?.can_connect ?? false)

  const secondary = (() => {
    if (!configured && !loading) return connector.kind
    if (loading && !status) return 'Checking…'
    if (state === 'connected') return status?.account?.display_name || 'Connected'
    if (state === 'pending') return 'Waiting for sign-in'
    if (state === 'needs_attention') {
      return status?.account?.status_reason || 'Needs re-authorising'
    }
    if (unavailable) return status?.note || 'Not available through Composio'
    if (needsSetup) return status?.note || 'Needs our own auth config'
    if (status?.note && state === 'not_connected') return status.note
    return connector.kind
  })()

  return (
    <li className="flex flex-col gap-1 border-b border-line/50 px-3 py-2 last:border-b-0 sm:border-r sm:[&:nth-child(2n)]:border-r-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
      <div className="flex items-center gap-2">
        <ConnectorMark id={connector.id} color={connector.color} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-xs text-ink">{connector.name}</span>
            <StateBadge state={state} configured={configured} loading={loading && !status} />
            {needsSetup && (
              <Badge tone="warn" className="px-1 text-[0.58rem]" title={status?.note}>
                setup
              </Badge>
            )}
          </span>
          <span className="truncate text-[0.65rem] leading-relaxed text-ink-disabled">
            {secondary}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {!configured || unavailable ? null : state === 'connected' ? (
            onDisconnect && (
              <Button size="sm" variant="quiet" onClick={onDisconnect} aria-label={`Disconnect ${connector.name}`}>
                <Unplug className="size-3.5" aria-hidden />
                Disconnect
              </Button>
            )
          ) : state === 'pending' ? (
            <>
              {offer && (
                <a
                  href={offer}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex h-7 items-center gap-1 rounded-lg bg-accent px-2 text-[0.68rem] font-medium text-accent-ink hover:brightness-110"
                >
                  Sign in
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
              <Button size="sm" variant="quiet" onClick={onCheck} aria-label={`Check ${connector.name}`}>
                <RefreshCw className="size-3.5" aria-hidden />
                Check
              </Button>
              {onDisconnect && (
                <Button size="sm" variant="ghost" onClick={onDisconnect}>
                  Cancel
                </Button>
              )}
            </>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={onConnect}
              disabled={!canConnect || connecting}
              aria-label={`${state === 'needs_attention' ? 'Reconnect' : 'Connect'} ${connector.name}`}
            >
              <PlugZap className="size-3.5" aria-hidden />
              {connecting ? 'Opening…' : state === 'needs_attention' ? 'Reconnect' : 'Connect'}
            </Button>
          )}
        </div>
      </div>
      {connectError && (
        <p className="pl-7 text-[0.65rem] leading-relaxed text-danger">{connectError}</p>
      )}
    </li>
  )
}

function StateBadge({
  state,
  configured,
  loading
}: {
  state: ConnectorStatus['state']
  configured: boolean
  loading: boolean
}) {
  if (loading) return <Badge className="px-1.5 text-[0.58rem]">Checking…</Badge>
  if (!configured) return <Badge className="px-1.5 text-[0.58rem]">Not set up</Badge>
  if (state === 'connected') return <Badge tone="ok" className="px-1.5 text-[0.58rem]">Connected</Badge>
  if (state === 'pending') return <Badge tone="warn" className="px-1.5 text-[0.58rem]">Waiting</Badge>
  if (state === 'needs_attention') {
    return <Badge tone="warn" className="px-1.5 text-[0.58rem]">Re-auth</Badge>
  }
  if (state === 'inactive') return <Badge className="px-1.5 text-[0.58rem]">Paused</Badge>
  if (state === 'unavailable') return <Badge className="px-1.5 text-[0.58rem]">Unavailable</Badge>
  return <Badge className="px-1.5 text-[0.58rem]">Not connected</Badge>
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** A connector's mark: its own glyph, in its own colour, on a tint of it. */
function ConnectorMark({ id, color }: { id: string; color: string }) {
  const mark = MARKS[id] ?? { stroke: <circle cx="12" cy="12" r="5" /> }

  return (
    <span
      aria-hidden
      className="grid size-7 shrink-0 place-items-center rounded-md border border-line/60"
      style={{ backgroundColor: tintOf(color), color }}
    >
      <svg
        viewBox="0 0 24 24"
        className="size-4"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.7}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {mark.stroke}
        {mark.fill}
      </svg>
    </span>
  )
}

/**
 * The glyphs. Simple strokes rather than traced logos: a row mark is 28 px, the name is written
 * beside it, and a mark that is recognisable at that size beats one that is faithful at 200.
 */
const MARKS: Record<string, { stroke?: ReactNode; fill?: ReactNode }> = {
  // A bag, because that is what a shop is.
  shopify: {
    stroke: (
      <>
        <path d="M5.8 8h12.4l-1.1 11.4H6.9L5.8 8Z" />
        <path d="M9.2 8V6.4a2.8 2.8 0 0 1 5.6 0V8" />
      </>
    )
  },
  // A square with a square in it, which is the whole of the logo.
  square: {
    stroke: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="3.6" />
        <rect x="9.3" y="9.3" width="5.4" height="5.4" rx="1.3" />
      </>
    )
  },
  // A card with the stripe.
  stripe: {
    stroke: (
      <>
        <rect x="3" y="5.5" width="18" height="13" rx="2.2" />
        <path d="M3 10h18" />
        <path d="M12.5 14.8c.8.5 1.8.6 2.7.2 1.6-.6 1.5-2.6-.6-2.9-2.6-.4-2.3-3 .4-3.1.8 0 1.5.2 2 .5" />
      </>
    )
  },
  // Two Ps, the second offset, as the mark reads at a glance.
  paypal: {
    stroke: (
      <>
        <path d="M7.5 20 10 4h5.2a4 4 0 0 1 .4 8H11" />
        <path d="M11.5 16h3.2a4 4 0 0 0 .4-8" opacity="0.55" />
      </>
    )
  },
  xero: {
    stroke: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" />
      </>
    )
  },
  // A ledger circle with a tick.
  quickbooks: {
    stroke: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M8 12.3l3 3 5-6" />
      </>
    )
  },
  gmail: {
    stroke: (
      <>
        <rect x="2.8" y="5.2" width="18.4" height="13.6" rx="2.2" />
        <path d="M3.4 6.8 12 13.2l8.6-6.4" />
      </>
    )
  },
  // A calendar page with a tick, for the Microsoft side.
  outlook: {
    stroke: (
      <>
        <rect x="4" y="5" width="16" height="15" rx="2.2" />
        <path d="M4 9.2h16M8 3v4M16 3v4" />
        <path d="M9 14l2 2 4-5" />
      </>
    )
  },
  // A folder, because that is what Drive is to the person using it.
  gdrive: {
    stroke: <path d="M3.4 6.6a1.8 1.8 0 0 1 1.8-1.8h3.4l1.9 2.6h8.3a1.8 1.8 0 0 1 1.8 1.8v8.2a1.8 1.8 0 0 1-1.8 1.8H5.2a1.8 1.8 0 0 1-1.8-1.8Z" />
  },
  // A page with a folded corner.
  gdocs: {
    stroke: (
      <>
        <path d="M6 3h8l4 4v14H6Z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6M9 16h6" />
      </>
    )
  },
  // A grid, because that is what a spreadsheet is.
  gsheets: {
    stroke: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M4 10h16M4 15h16M10 4v16M15 4v16" />
      </>
    )
  },
  gcal: {
    stroke: (
      <>
        <rect x="3.6" y="4.6" width="16.8" height="15.8" rx="2.4" />
        <path d="M3.6 9.4h16.8M8.4 4.6v4.8M15.6 4.6v4.8" />
        <path d="M9.4 13.6h2.2v3.4" />
      </>
    )
  },
  // A megaphone: a campaign, which is what a newsletter list is for.
  mailchimp: {
    stroke: (
      <>
        <path d="M4 10.4v3.2l11.4 4.6V5.8L4 10.4Z" />
        <path d="M15.4 8.6a4.2 4.2 0 0 1 0 6.8" />
        <path d="M6.6 15.1v3.5a1.4 1.4 0 0 0 2.8 0v-2.4" />
      </>
    )
  },
  facebook: {
    stroke: <circle cx="12" cy="12" r="9" />,
    fill: (
      <path
        d="M13.5 20v-6.3h2.1l.4-2.6h-2.5V9.4c0-.75.2-1.26 1.3-1.26h1.35V5.8c-.96-.1-1.9-.14-2.4.02-1.4.44-2.2 1.5-2.2 3.2v2.08H9.4v2.6h2.15V20h1.95Z"
        stroke="none"
        fill="currentColor"
      />
    )
  },
  instagram: {
    stroke: (
      <>
        <rect x="3.8" y="3.8" width="16.4" height="16.4" rx="4.6" />
        <circle cx="12" cy="12" r="3.9" />
      </>
    ),
    fill: <circle cx="16.9" cy="7.1" r="1.05" stroke="none" fill="currentColor" />
  },
  // A pen, for the things a menu is made with.
  canva: {
    stroke: (
      <>
        <path d="M4 20l1-4 10-10 3 3L8 19l-4 1Z" />
        <path d="M13 5l3 3" />
      </>
    )
  },
  // A speech bubble with a handset in it.
  whatsapp: {
    stroke: (
      <>
        <path d="M4 20l1.2-4A8 8 0 1 1 8 19l-4 1Z" />
        <path d="M9 9c.5 3 2.5 5 5.5 5.5l1-1.5-2-1-1 1c-1-.6-1.8-1.4-2.4-2.4l1-1-1-2L9 9Z" />
      </>
    )
  },
  // A ticket, for a market or a workshop.
  eventbrite: {
    stroke: (
      <>
        <path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4Z" />
        <path d="M12 6v12" />
      </>
    )
  },
  // A calendar with a clock, for a booking.
  calendly: {
    stroke: (
      <>
        <rect x="3.5" y="5" width="17" height="15" rx="2.2" />
        <path d="M3.5 9.2h17M8 3v4M16 3v4" />
        <circle cx="12" cy="14.2" r="2.3" />
      </>
    )
  },
  // A parcel, for a box going out.
  shippo: {
    stroke: (
      <>
        <path d="M4 7l8-3 8 3v10l-8 3-8-3Z" />
        <path d="M4 7l8 3 8-3M12 10v10" />
      </>
    )
  },
  // A ledger with a Z, for the second set of books.
  zoho_books: {
    stroke: (
      <>
        <path d="M5 4h14v16H5Z" />
        <path d="M9 8h6l-6 8h6" />
      </>
    )
  },
  // A hub with its spokes.
  hubspot: {
    stroke: (
      <>
        <circle cx="12" cy="12" r="3" />
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4v5M12 15v5M4 12h5M15 12h5" />
      </>
    )
  },
  // A pin, for a place on a delivery round.
  google_maps: {
    stroke: (
      <>
        <path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11Z" />
        <circle cx="12" cy="10" r="2.5" />
      </>
    )
  }
}
