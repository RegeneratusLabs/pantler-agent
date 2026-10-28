import {
  AlertCircle,
  FileText,
  FolderOpen,
  Globe,
  Image as ImageIcon,
  LoaderCircle,
  Package,
  X
} from 'lucide-react'
import { useState } from 'react'
import type { AttachmentKind, AttachmentRef } from '@shared/attachments'
import { attachmentRawUrl, formatBytes } from '@shared/attachments'
import { cn } from '../ui/cn'
import { attachmentTarget, fileTarget, type PreviewTarget } from './preview'
import { usePreview } from './preview-context'
import type { DraftAttachment } from '../state/attachments'

/**
 * The chips.
 *
 * Two shapes, one look. Before send they carry a draft's state — uploading, ready, failed —
 * and can be removed. After send they are a record of what the turn carried, parsed back out
 * of the message text, and can be opened.
 *
 * The image tile is the point of the whole thing: a photograph the operator attached should
 * be recognisable at a glance, not a filename they have to read.
 *
 * **One click, one sheet.** Both shapes open the same preview surface
 * (the file-preview design §4 D3), so a PDF attached yesterday behaves exactly like a PDF
 * attached a moment ago — and a reloaded turn's chip is no longer inert, which it was.
 */

const ICONS: Record<AttachmentKind, typeof FileText> = {
  image: ImageIcon,
  document: FileText,
  text: FileText,
  archive: Package,
  folder: FolderOpen,
  url: Globe,
  other: FileText
}

export function AttachChips({
  drafts,
  onRemove
}: {
  drafts: DraftAttachment[]
  onRemove: (key: string) => void
}) {
  const { open } = usePreview()
  if (drafts.length === 0) return null

  return (
    <ul className="flex max-w-full flex-wrap gap-1.5 px-1 pt-1" data-slot="composer-attachments">
      {drafts.map(draft => {
        const Icon = ICONS[draft.kind] ?? FileText
        // A folder is a tree, not a document, and an upload in flight has no id yet.
        const openable = Boolean(draft.record) && draft.kind !== 'folder'
        const target: PreviewTarget | null =
          openable && draft.record
            ? attachmentTarget({
                id: draft.record.id,
                path: draft.record.path,
                name: draft.name,
                detail: `${draft.record.mime} · ${formatBytes(draft.record.size)}`
              })
            : null
        return (
          <li key={draft.key} className="group/chip relative">
            <button
              type="button"
              aria-busy={draft.status === 'uploading'}
              aria-label={openable ? `Preview ${draft.name}` : draft.name}
              disabled={!openable}
              onClick={() => target && open(target)}
              title={draft.error ?? draft.record?.path ?? draft.name}
              className={cn(
                'flex max-w-56 items-center gap-2 rounded-lg border bg-raised py-1 pr-5 pl-1 text-left',
                'transition-colors',
                draft.status === 'error'
                  ? 'border-danger/50'
                  : 'border-line hover:border-line-strong',
                openable && 'cursor-pointer'
              )}
            >
              <span className="relative grid size-8 shrink-0 place-items-center overflow-hidden rounded-md bg-hover">
                {draft.previewUrl ? (
                  <img
                    src={draft.previewUrl}
                    alt=""
                    draggable={false}
                    className="size-8 object-cover"
                  />
                ) : (
                  <Icon className="size-4 text-ink-3" aria-hidden />
                )}
                {draft.status === 'uploading' && (
                  <span className="absolute inset-0 grid place-items-center bg-canvas/70">
                    <LoaderCircle className="size-4 animate-spin text-ink-2" aria-hidden />
                  </span>
                )}
                {draft.status === 'error' && (
                  <span className="absolute inset-0 grid place-items-center bg-canvas/70">
                    <AlertCircle className="size-4 text-danger" aria-hidden />
                  </span>
                )}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[0.72rem] font-medium text-ink">{draft.name}</span>
                <span className="truncate text-[0.62rem] text-ink-3">
                  {draft.status === 'uploading'
                    ? 'Attaching…'
                    : draft.status === 'error'
                      ? (draft.error ?? 'Could not attach')
                      : draft.kind === 'folder'
                        ? `folder · ${formatBytes(draft.size)}`
                        : formatBytes(draft.size)}
                </span>
              </span>
            </button>
            <button
              type="button"
              aria-label={`Remove ${draft.name}`}
              onClick={() => onRemove(draft.key)}
              className={cn(
                'absolute -top-1 -right-1 grid size-3.5 place-items-center rounded-full',
                'border border-line-strong bg-overlay text-ink-2 opacity-0 transition-opacity',
                'group-hover/chip:opacity-100 focus-visible:opacity-100 hover:text-ink'
              )}
            >
              <X className="size-2.5" aria-hidden />
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** The same chips, rebuilt from a persisted turn's text. */
export function TurnAttachments({ attachments }: { attachments: AttachmentRef[] }) {
  if (attachments.length === 0) return null
  return (
    <ul className="flex max-w-full flex-wrap gap-1.5">
      {attachments.map((ref, index) => (
        <TurnChip key={`${ref.path}-${index}`} attachment={ref} />
      ))}
    </ul>
  )
}

function TurnChip({ attachment }: { attachment: AttachmentRef }) {
  const { open } = usePreview()
  // A file whose chip was removed before send, or whose attachment was swept after 90 days,
  // still has to render: the words stay, the thumbnail falls back to its type icon.
  const [broken, setBroken] = useState(false)
  const Icon = attachment.image ? ImageIcon : FileText
  const showImage = attachment.image && Boolean(attachment.id) && !broken

  // The id is what the store is addressed by, and the frozen format is where it comes from.
  // Without one — an older turn, a file that never reached the store — the path is still worth
  // trying: it is the other door onto the same bytes, and the sheet will say so if it is closed.
  const target: PreviewTarget = attachment.id
    ? attachmentTarget({
        id: attachment.id,
        path: attachment.path,
        name: attachment.name,
        detail: attachment.detail
      })
    : fileTarget(attachment.path, attachment.detail)

  return (
    <li className="max-w-56">
      <button
        type="button"
        onClick={() => open(target)}
        aria-label={`Preview ${attachment.name}`}
        title={attachment.path}
        className={cn(
          'flex w-full items-center gap-2 rounded-lg border border-line bg-raised py-1 pr-2.5 pl-1',
          'text-left transition-colors hover:border-line-strong'
        )}
      >
        <span className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-md bg-hover">
          {showImage ? (
            <img
              src={attachmentRawUrl(attachment.id as string)}
              alt=""
              loading="lazy"
              draggable={false}
              onError={() => setBroken(true)}
              className="size-8 object-cover"
            />
          ) : (
            <Icon className="size-4 text-ink-3" aria-hidden />
          )}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[0.72rem] font-medium text-ink">{attachment.name}</span>
          <span className="truncate text-[0.62rem] text-ink-3">{attachment.detail}</span>
        </span>
      </button>
    </li>
  )
}

/** The block the assistant was actually given, one disclosure down. */
export function TurnAttachmentContext({ context }: { context: string }) {
  if (!context.trim()) return null
  return (
    <details className="max-w-[85%] self-end rounded-card border border-line bg-surface/40 px-3 py-2">
      <summary className="text-display cursor-pointer list-none text-[0.68rem] text-ink-3 select-none">
        What the assistant was given
      </summary>
      <pre className="mt-2 max-h-72 overflow-auto font-mono text-[0.7rem] whitespace-pre-wrap text-ink-3">
        {context}
      </pre>
    </details>
  )
}
