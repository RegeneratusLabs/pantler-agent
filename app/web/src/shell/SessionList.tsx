import type { SessionSummary } from '@shared/wire'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Clock, MoreHorizontal, Pencil, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { SeamError, SeamUnreachable } from '../seam/client'
import { qk, useApp, useSessions } from '../state/app-context'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { ConfirmDialog, Dialog } from '../ui/dialog'
import { EmptyState } from '../ui/empty'
import { Field, Input } from '../ui/field'
import { Spinner } from '../ui/spinner'
import {
  describeDeleteFailure,
  describeWriteFailure,
  filterSessions,
  groupSessions,
  lastActive,
  sessionLabel,
  sessionSubtitle,
  shortAge,
  shortId
} from './sessions'

/**
 * The session rail — chat history, and the only way back into a conversation.
 *
 * Read from `GET /api/sessions`. The engine already computes the title, preview and
 * message count, so nothing here derives what the engine can tell us; we only group by
 * recency and filter.
 */
export function SessionList({ onNavigate }: { onNavigate?: () => void }) {
  const { data, isPending, error } = useSessions()
  const sessions = data?.sessions ?? []
  const { sessionId } = useParams()
  const [query, setQuery] = useState('')
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<SessionSummary | null>(null)
  const [deleting, setDeleting] = useState<SessionSummary | null>(null)

  const { client } = useApp()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const invalidate = () => queryClient.invalidateQueries({ queryKey: qk.sessions })

  /** The rail after a session is gone, however it went. */
  const forget = (id: string) => {
    setDeleting(null)
    // Deleting the session you are reading must not leave the transcript on screen.
    if (id === sessionId) navigate('/chat')
    void invalidate()
  }

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      client.patchSession(id, { title }),
    onSuccess: () => {
      setRenaming(null)
      void invalidate()
    }
  })

  const remove = useMutation({
    mutationFn: (id: string) => client.deleteSession(id),
    onSuccess: (_result, id) => forget(id),
    onError: (error, id) => {
      // 404 is "already gone" — deleted in another tab, or by a run tidying up after
      // itself. That is the state the operator asked for, so finish the job instead of
      // reporting a failure they can do nothing about.
      if (error instanceof SeamError && error.status === 404) forget(id)
    }
  })

  const pin = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      client.patchSession(id, { pinned }),
    onSuccess: () => void invalidate()
  })

  // A pin has no dialog to fail into, so its refusal is a line at the top of the rail.
  const pinTarget = sessions.find(session => session.id === pin.variables?.id)
  const pinLabel = pinTarget ? sessionLabel(pinTarget) : shortId(pin.variables?.id ?? '')

  const groups = useMemo(() => groupSessions(filterSessions(sessions, query)), [sessions, query])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-3 pb-2">
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-disabled"
          />
          <Input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Search sessions"
            aria-label="Search sessions"
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isPending && (
          <div className="px-3 py-4">
            <Spinner label="Loading sessions…" />
          </div>
        )}

        {error && (
          <p className="mx-2 rounded-lg border border-danger/40 px-3 py-2 text-xs text-danger">
            {error instanceof SeamUnreachable
              ? 'Could not list sessions — the engine is not answering.'
              : 'Could not list sessions. The engine is reachable — this route may not be.'}
          </p>
        )}

        {pin.error && (
          <p
            role="alert"
            className="mx-2 mb-1 rounded-lg border border-danger/40 px-3 py-2 text-xs text-danger"
          >
            {describeWriteFailure(
              pin.error,
              `${pin.variables?.pinned ? 'pin' : 'unpin'} “${pinLabel}”`
            )}
          </p>
        )}

        {!isPending && !error && sessions.length === 0 && (
          <EmptyState
            className="py-8"
            icon={<Clock className="size-5" />}
            title="No sessions yet"
          >
            Start one and it will appear here.
          </EmptyState>
        )}

        {!isPending && sessions.length > 0 && groups.length === 0 && (
          <p className="px-3 py-4 text-xs text-ink-3">Nothing matches “{query}”.</p>
        )}

        {groups.map(group => (
          <section key={group.key} className="mb-1">
            <h3 className="text-display sticky top-0 z-1 bg-surface/95 px-3 py-1.5 text-[0.68rem] text-ink-3 backdrop-blur-sm">
              {group.label}
            </h3>
            <ul className="flex flex-col gap-0.5">
              {group.sessions.map(session => (
                <SessionRow
                  key={session.id}
                  session={session}
                  active={session.id === sessionId}
                  menuOpen={menuFor === session.id}
                  onMenu={open => setMenuFor(open ? session.id : null)}
                  onNavigate={onNavigate}
                  onRename={() => {
                    setMenuFor(null)
                    // A refusal from a previous attempt must not greet the next dialog.
                    rename.reset()
                    setRenaming(session)
                  }}
                  onDelete={() => {
                    setMenuFor(null)
                    remove.reset()
                    setDeleting(session)
                  }}
                  pinning={pin.isPending && pin.variables?.id === session.id}
                  onPin={() => {
                    setMenuFor(null)
                    pin.reset()
                    // `!session.pinned` comes from the render row, so a second click before the
                    // rail refetches would send the same target value again and look like a
                    // switch that does nothing. The menu disables the item while it is in
                    // flight, which is what makes one click one write
                    // (the internal audit WEB-14).
                    pin.mutate({ id: session.id, pinned: !session.pinned })
                  }}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>

      {data?.hasMore && (
        // Not a "load more" button: the engine's window is what it is, and a rail that pages
        // would need a scroll-anchored list to be worth it. Saying which window is shown is the
        // honest half, and it is the half that stops the newest fifty reading as everything
        // (the internal audit CON-1).
        <p className="px-3 pb-3 text-[0.6875rem] leading-snug text-ink-3">
          Showing the newest {data.limit} conversations. Older ones are in the engine but not
          listed here yet.
        </p>
      )}

      {renaming && (
        <RenameDialog
          // A fresh instance per session, so the field seeds itself without an effect.
          key={renaming.id}
          session={renaming}
          busy={rename.isPending}
          error={
            rename.error
              ? describeWriteFailure(rename.error, `rename “${sessionLabel(renaming)}”`)
              : undefined
          }
          onCancel={() => {
            rename.reset()
            setRenaming(null)
          }}
          onSave={title => rename.mutate({ id: renaming.id, title })}
        />
      )}

      <ConfirmDialog
        open={Boolean(deleting)}
        destructive
        busy={remove.isPending}
        title="Delete this session?"
        description={
          deleting
            ? `“${sessionLabel(deleting)}” and its transcript are removed from the engine. This cannot be undone.`
            : undefined
        }
        // The refusal stays on screen with the dialog open, so a blocked delete reads as a
        // blocked delete rather than a dead button.
        error={
          remove.error && deleting
            ? describeDeleteFailure(remove.error, sessionLabel(deleting))
            : undefined
        }
        confirmLabel="Delete"
        onCancel={() => {
          remove.reset()
          setDeleting(null)
        }}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  )
}

function SessionRow({
  session,
  active,
  menuOpen,
  onMenu,
  onNavigate,
  onRename,
  onDelete,
  onPin,
  pinning
}: {
  session: SessionSummary
  active: boolean
  menuOpen: boolean
  onMenu: (open: boolean) => void
  onNavigate?: () => void
  onRename: () => void
  onDelete: () => void
  onPin: () => void
  /** True while this session's pin is being written. */
  pinning: boolean
}) {
  const subtitle = sessionSubtitle(session)
  const age = shortAge(lastActive(session))

  return (
    // The menu's keys live on the row: focus stays on the trigger (a sibling of the menu), so a
    // handler bound to the menu itself never saw Escape or an arrow key
    // (the internal audit WEB-14).
    <li
      className="group relative"
      onKeyDown={event => {
        if (event.key === 'Escape' && menuOpen) {
          event.stopPropagation()
          onMenu(false)
        }
      }}
    >
      <Link
        to={`/chat/${encodeURIComponent(session.id)}`}
        onClick={onNavigate}
        title={`${sessionLabel(session)} · ${session.id}`}
        className={cn(
          'flex flex-col gap-0.5 rounded-lg py-1.5 pr-8 pl-3 transition-colors',
          active ? 'bg-hover text-ink' : 'text-ink-2 hover:bg-hover hover:text-ink'
        )}
      >
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-[0.83rem] leading-5">
            {sessionLabel(session)}
          </span>
          <span className="shrink-0 font-mono text-[0.65rem] text-ink-disabled tabular-nums">
            {age}
          </span>
        </span>
        {subtitle && (
          <span className="truncate text-[0.72rem] leading-4 text-ink-3">{subtitle}</span>
        )}
        <span className="flex items-center gap-2 font-mono text-[0.62rem] text-ink-disabled">
          {session.pinned && <Pin aria-label="Pinned" className="size-2.5 shrink-0" />}
          <span className="truncate">{shortId(session.id)}</span>
          {typeof session.message_count === 'number' && session.message_count > 0 && (
            <span className="shrink-0">{session.message_count} msg</span>
          )}
        </span>
      </Link>

      <button
        type="button"
        aria-label={`Actions for ${sessionLabel(session)}`}
        aria-expanded={menuOpen}
        onClick={() => onMenu(!menuOpen)}
        className={cn(
          'absolute top-1.5 right-1.5 grid size-6 place-items-center rounded-md',
          'text-ink-3 hover:bg-canvas hover:text-ink focus-visible:opacity-100',
          menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
        )}
      >
        <MoreHorizontal className="size-3.5" />
      </button>

      {menuOpen && (
        <>
          {/* A full-bleed click-catcher: cheaper and more reliable than a document listener. */}
          <button
            type="button"
            aria-label="Close menu"
            className="fixed inset-0 z-20 cursor-default"
            onClick={() => onMenu(false)}
          />
          <div
            role="menu"
            aria-label={`Actions for ${sessionLabel(session)}`}
            className="animate-fade absolute top-8 right-1.5 z-30 flex w-40 flex-col rounded-lg border border-line-strong bg-overlay p-1 shadow-xl"
          >
            <MenuItem icon={<Pencil className="size-3.5" />} onClick={onRename}>
              Rename
            </MenuItem>
            <MenuItem
              icon={session.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
              onClick={onPin}
              disabled={pinning}
            >
              {session.pinned ? 'Unpin' : 'Pin'}
            </MenuItem>
            <MenuItem icon={<Trash2 className="size-3.5" />} onClick={onDelete} danger>
              Delete
            </MenuItem>
          </div>
        </>
      )}
    </li>
  )
}

function MenuItem({
  icon,
  onClick,
  danger,
  disabled,
  children
}: {
  icon: React.ReactNode
  onClick: () => void
  danger?: boolean
  /** True while this action is in flight: a second click would send the same target again. */
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-hover',
        'disabled:pointer-events-none disabled:opacity-50',
        danger ? 'text-danger' : 'text-ink-2 hover:text-ink'
      )}
    >
      {icon}
      {children}
    </button>
  )
}

function RenameDialog({
  session,
  busy,
  error,
  onCancel,
  onSave
}: {
  session: SessionSummary
  busy: boolean
  error?: string
  onCancel: () => void
  onSave: (title: string) => void
}) {
  const [value, setValue] = useState(() => session.title?.trim() ?? '')

  return (
    <Dialog
      open
      title="Rename session"
      error={error}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => onSave(value.trim())} disabled={busy}>
            Save
          </Button>
        </>
      }
    >
      <Field label="Title" hint="Shown in the rail. The engine keeps titles unique.">
        <Input
          value={value}
          autoFocus
          onChange={event => setValue(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') onSave(value.trim())
          }}
        />
      </Field>
    </Dialog>
  )
}
