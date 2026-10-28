import { Download, Eye, FileText, Image as ImageIcon, Package } from 'lucide-react'
import { extensionOf, fileTarget, type FileTarget } from './preview'
import { usePreview } from './preview-context'
import { cn } from '../ui/cn'

/**
 * A file the assistant named, as a small card.
 *
 * This is the shape the file-preview design §4 D3 asks for: the *card* is what belongs in a
 * message, and the live thing lives one click away in the preview pane. It is deliberately not a
 * thumbnail or a frame — a turn that wrote six files should not load six documents — and it is
 * deliberately quiet, because it sits behind an activity line and the line is the record.
 *
 * The name is the link, the whole row is clickable, and the download anchor is the one action
 * that does not need the pane. Which renderer a file gets is not decided here: the pane asks
 * the server (`PreviewMeta.render`), which is the only place that answer exists.
 */
export function FileCard({
  path,
  name,
  detail,
  className
}: {
  path: string
  name?: string
  detail?: string
  className?: string
}) {
  const { open } = usePreview()
  const target: FileTarget = fileTarget(path, detail)
  const label = name ?? target.name
  const Icon = iconFor(label)

  return (
    <span
      className={cn(
        'group/file inline-flex max-w-full items-center gap-1.5 rounded-md border border-line',
        'bg-raised/60 py-0.5 pr-1 pl-1.5 align-middle',
        className
      )}
    >
      <Icon className="size-3.5 shrink-0 text-ink-disabled" aria-hidden />
      <button
        type="button"
        onClick={() => open(target)}
        title={`Preview ${path}`}
        className="min-w-0 truncate text-left text-xs text-ink-2 underline decoration-line-strong underline-offset-2 hover:text-ink hover:decoration-ink-3"
      >
        {label}
      </button>
      <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover/file:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          aria-label={`Preview ${label}`}
          onClick={() => open(target)}
          className="grid size-5 place-items-center rounded text-ink-disabled hover:bg-hover hover:text-ink"
        >
          <Eye className="size-3" aria-hidden />
        </button>
        <a
          aria-label={`Download ${label}`}
          href={`/api/files/raw?path=${encodeURIComponent(path)}`}
          download={label}
          className="grid size-5 place-items-center rounded text-ink-disabled hover:bg-hover hover:text-ink"
        >
          <Download className="size-3" aria-hidden />
        </a>
      </span>
    </span>
  )
}

function iconFor(name: string) {
  const extension = extensionOf(name)
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'heic', 'svg'].includes(extension)) {
    return ImageIcon
  }
  if (['zip', 'gz', 'tar', '7z', 'rar'].includes(extension)) return Package
  return FileText
}
