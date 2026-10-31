import { Paperclip, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'

/**
 * The ATTACH menu.
 *
 * Five rows, in this order, because that is the reference (the attachment design §5): Files,
 * Folder, Images, Paste image, URL. The browser has no native dialog we can drive, so each
 * row owns a hidden input or a clipboard call — but the menu itself is the same menu, and it
 * is the only place the whole capability is discoverable.
 *
 * A row is disabled when its handler is missing, and never shown disabled-but-enabled-looking:
 * "Paste image" on a browser that will not answer `clipboard.read()` says so instead.
 */
export interface AttachMenuRow {
  id: string
  label: string
  icon: LucideIcon
  hint?: string
  onSelect: () => void
  disabled?: boolean
  disabledReason?: string
}

export function AttachMenu({
  rows,
  label = 'Attach'
}: {
  rows: AttachMenuRow[]
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  const usable = rows.filter(row => !row.disabled)

  const choose = (row: AttachMenuRow) => {
    if (row.disabled) return
    setOpen(false)
    trigger.current?.focus()
    row.onSelect()
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Only while the menu is showing: the wrapper also contains the trigger, and Enter on a
    // closed menu must open it (the button's own job) rather than activate a row nobody can see.
    if (!open) return
    if (event.key === 'Escape') {
      setOpen(false)
      trigger.current?.focus()
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (usable.length === 0) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      setFocused(current => (current + step + usable.length) % usable.length)
    }
    if (event.key === 'Enter' || event.key === ' ') {
      const row = usable[focused]
      if (row) {
        event.preventDefault()
        choose(row)
      }
    }
  }

  return (
    // The key handler belongs here, not on the popup: focus stays on the trigger (a sibling of
    // the popup), so a keydown on it never reaches a handler bound to the menu below. It also
    // only ever ran for a mouse, because `focused` moved on hover
    // (the internal audit WEB-7).
    <div ref={root} className="relative" onKeyDown={onKeyDown}>
      <Button
        variant="ghost"
        size="icon"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        title={label}
        onClick={() => setOpen(value => !value)}
      >
        <Paperclip className="size-4" />
      </Button>

      {open && (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            'absolute bottom-full left-0 z-30 mb-2 w-60 rounded-card border border-line',
            'bg-overlay p-1 shadow-xl'
          )}
        >
          <p className="text-display px-2.5 py-1.5 text-[0.625rem] text-ink-3">{label}</p>
          {rows.map(row => {
            const index = usable.indexOf(row)
            const Icon = row.icon
            return (
              <button
                key={row.id}
                type="button"
                role="menuitem"
                disabled={row.disabled}
                title={row.disabled ? row.disabledReason : row.hint}
                onMouseEnter={() => !row.disabled && setFocused(index)}
                onClick={() => choose(row)}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm',
                  'transition-colors disabled:opacity-45',
                  !row.disabled && (index === focused ? 'bg-hover text-ink' : 'text-ink-2 hover:bg-hover hover:text-ink')
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{row.label}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * The three pickers, as hidden inputs.
 *
 * `webkitdirectory` is not a standard attribute, and a browser that ignores it still opens a
 * file picker — which is the right degradation: the operator gets a file, not an error.
 */
export function AttachInputs({
  onFiles,
  inputs
}: {
  onFiles: (files: File[], options: { folder?: boolean }) => void
  inputs: (refs: {
    files: React.RefObject<HTMLInputElement | null>
    folder: React.RefObject<HTMLInputElement | null>
    images: React.RefObject<HTMLInputElement | null>
  }) => void
}) {
  const files = useRef<HTMLInputElement>(null)
  const folder = useRef<HTMLInputElement>(null)
  const images = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputs({ files, folder, images })
  }, [inputs])

  const take = (options: { folder?: boolean }) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(event.target.files ?? [])
    // Reset first: picking the same file twice must fire a change event twice.
    event.target.value = ''
    if (chosen.length > 0) onFiles(chosen, options)
  }

  return (
    <>
      <input ref={files} type="file" multiple hidden onChange={take({})} />
      <input
        ref={folder}
        type="file"
        multiple
        hidden
        // React types do not know this attribute, and it is the only folder picker on the web.
        {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
        onChange={take({ folder: true })}
      />
      <input
        ref={images}
        type="file"
        multiple
        hidden
        accept="image/png,image/jpeg,image/gif,image/webp,image/bmp,image/tiff"
        onChange={take({})}
      />
    </>
  )
}

/** A menu row's worth of small print, for the hint line under the composer. */
export function AttachHint({ children }: { children: ReactNode }) {
  return <span className="text-ink-3">{children}</span>
}
