import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { FileInput } from '../state/attachments'
import { cn } from '../ui/cn'

/**
 * Drag anything onto the conversation.
 *
 * A browser gives a drop handler `File` objects and nothing else — no path, and no way to ask
 * for one. So everything dropped is uploaded, which is the same rule the desktop follows when
 * its backend is on another machine, and it is why a dropped file works identically on a
 * laptop and on a phone.
 *
 * A dropped *folder* is walked with `webkitGetAsEntry`, because a folder has no bytes and the
 * operator's intent is obviously the tree inside it. The walk is bounded: nobody means to
 * attach their home directory by accident.
 */

const MAX_WALK_ENTRIES = 200

async function collect(entry: FileSystemEntry, prefix: string, into: FileInput[]): Promise<void> {
  if (into.length >= MAX_WALK_ENTRIES) return
  if (entry.isFile) {
    const file = await new Promise<File | null>(resolve =>
      (entry as FileSystemFileEntry).file(
        value => resolve(value),
        () => resolve(null)
      )
    )
    if (file) into.push({ file, relPath: `${prefix}${file.name}` })
    return
  }
  if (!entry.isDirectory) return
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  // readEntries answers in pages, and an empty page means the end.
  for (;;) {
    const page = await new Promise<FileSystemEntry[]>(resolve =>
      reader.readEntries(
        value => resolve(value),
        () => resolve([])
      )
    )
    if (page.length === 0) break
    for (const child of page) {
      await collect(child, `${prefix}${entry.name}/`, into)
      if (into.length >= MAX_WALK_ENTRIES) return
    }
  }
}

export interface DroppedPayload {
  inputs: FileInput[]
  /** True when anything dropped was a directory, so the whole drop lands as one folder. */
  folder: boolean
}

/** Read a drop synchronously where it must be, and asynchronously where it can be. */
export async function readDrop(transfer: DataTransfer): Promise<DroppedPayload> {
  const items = Array.from(transfer.items ?? [])
  const entries = items
    .filter(item => item.kind === 'file')
    .map(item => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))

  if (entries.some(entry => entry?.isDirectory)) {
    const inputs: FileInput[] = []
    for (const entry of entries) {
      if (entry) await collect(entry, '', inputs)
    }
    return { inputs, folder: true }
  }

  const files = Array.from(transfer.files ?? [])
  return { inputs: files.map(file => ({ file })), folder: false }
}

export function useAttachmentDrop(onFiles: (payload: DroppedPayload) => void) {
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)

  const reset = useCallback(() => {
    depth.current = 0
    setDragging(false)
  }, [])

  // Escape abandons a drag in progress: the overlay goes, and the drop that would have
  // followed it is swallowed rather than attaching something the operator just cancelled.
  useEffect(() => {
    if (!dragging) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') reset()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [dragging, reset])

  return {
    dragging,
    reset,
    handlers: {
      onDragEnter: (event: React.DragEvent) => {
        if (!Array.from(event.dataTransfer?.types ?? []).includes('Files')) return
        event.preventDefault()
        depth.current += 1
        setDragging(true)
      },
      onDragOver: (event: React.DragEvent) => {
        if (!Array.from(event.dataTransfer?.types ?? []).includes('Files')) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      },
      onDragLeave: () => {
        depth.current = Math.max(0, depth.current - 1)
        if (depth.current === 0) setDragging(false)
      },
      onDrop: (event: React.DragEvent) => {
        event.preventDefault()
        // The transfer detaches when this handler returns, so it is read before any await.
        const transfer = event.dataTransfer
        reset()
        void readDrop(transfer).then(onFiles)
      }
    }
  }
}

/** The full-bleed sheet the reference shows over the conversation while a drag is live. */
export function AttachmentDropOverlay({ label }: { label: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        'pointer-events-none absolute inset-0 z-40 grid place-items-center',
        'bg-canvas/70 backdrop-blur-sm'
      )}
    >
      <div className="rounded-card border border-dashed border-line-strong bg-overlay/80 px-6 py-8">
        <p className="text-display text-[11px] text-ink-2">{label}</p>
      </div>
    </div>
  )
}

/** Wraps the conversation so a drop lands anywhere on it, not only on the composer. */
export function AttachmentDropZone({
  onFiles,
  label = 'Drop files to attach',
  children,
  className
}: {
  onFiles: (payload: DroppedPayload) => void
  label?: string
  children: ReactNode
  className?: string
}) {
  const { dragging, handlers } = useAttachmentDrop(onFiles)
  return (
    <div {...handlers} className={cn('relative flex min-h-0 flex-1 flex-col', className)}>
      {children}
      {dragging && <AttachmentDropOverlay label={label} />}
    </div>
  )
}
