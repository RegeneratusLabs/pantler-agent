/**
 * A file the assistant handed over with `MEDIA:` — painted in the turn when it is an image.
 *
 * The engine's own desktop does this and the operator asked for it here: a card the assistant
 * made is something to *look at* while you talk about it, not a path to copy into a file
 * manager. So a raster image renders inline, click to open it larger in the preview pane, with
 * a download that needs no pane at all — and everything else stays a card, because a `.docx`
 * inlined would be a lie about what a browser can show.
 *
 * **The server decides, not the file name.** The card is drawn after `/api/files/meta` answers,
 * so a `.png` that is really a TIFF, a path outside the read roots, or a file that has been
 * deleted since the turn all fall back to the card with the server's own sentence. That is the
 * same rule the preview pane follows (`preview.ts`), and it is why this component has three
 * states rather than one.
 *
 * It is deliberately the *whole* of the inline case: the image is capped so a tall card cannot
 * push the answer off the screen, it never upscales past its own size, and it is inert — no
 * script surface, no frame, nothing but a bitmap the server already agreed to serve inline
 * (the file-preview design §4 D3/D4).
 */

import { Download, Image as ImageIcon, LoaderCircle, Maximize2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { PreviewMeta } from '@shared/wire'
import { useApp } from '../state/app-context'
import { cn } from '../ui/cn'
import { FileCard } from './FileCard'
import { fileTarget, nameOf, rawUrl } from './preview'
import { usePreview } from './preview-context'

export function MediaFigure({ path, className }: { path: string; className?: string }) {
  const { bff } = useApp()
  const { open } = usePreview()
  const [meta, setMeta] = useState<PreviewMeta | null>(null)
  const [failed, setFailed] = useState(false)
  const [broken, setBroken] = useState(false)

  // Ask once per path what this is. The answer is the only thing that may put an `<img>` on
  // screen: `render: "image"` and `inline: true`, or nothing at all.
  useEffect(() => {
    let live = true
    setMeta(null)
    setFailed(false)
    setBroken(false)
    bff
      .fileMeta(path)
      .then(result => {
        if (live) setMeta(result)
      })
      .catch(() => {
        // The server's refusal is a sentence for the pane; here the card is the honest answer,
        // because a turn is not the place to argue about a path.
        if (live) setFailed(true)
      })
    return () => {
      live = false
    }
  }, [bff, path])

  const target = fileTarget(path)
  const name = meta?.name ?? nameOf(path)

  // While the answer is in flight there is nothing honest to draw but the fact that a file is
  // coming. A skeleton the size of a thumbnail would promise a shape this may not have.
  if (!meta && !failed) {
    return (
      <div
        className={cn(
          'flex w-fit max-w-full items-center gap-2 rounded-card border border-line',
          'bg-raised/60 px-3 py-2 text-xs text-ink-3',
          className
        )}
      >
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
        <span className="truncate">{name}</span>
      </div>
    )
  }

  // Not an image, not servable inline, or not there: a card is what the design asks for, and it
  // carries the same two actions without pretending the bytes are showable here.
  if (!meta || meta.render !== 'image' || !meta.inline) {
    return <FileCard path={path} name={name} className={className} />
  }

  const src = rawUrl(target)

  return (
    <figure className={cn('flex w-fit max-w-full flex-col gap-1.5', className)}>
      <button
        type="button"
        onClick={() => open(target)}
        title={`Open ${name} larger`}
        aria-label={`Open ${name} larger`}
        className={cn(
          'group/media relative block overflow-hidden rounded-card border border-line bg-raised',
          'transition-colors hover:border-line-strong'
        )}
      >
        {broken ? (
          // The server said this was an image and the browser could not paint it. Saying so is
          // the only honest option — a broken-image glyph reads as our bug rather than a file's.
          <span className="flex items-center gap-2 px-3 py-2 text-xs text-ink-3">
            <ImageIcon className="size-3.5" aria-hidden />
            {name} could not be shown here. Open it to try again.
          </span>
        ) : (
          <img
            src={src}
            alt={name}
            // Not `object-cover`: a card that crops the thing the operator is judging is worse
            // than one that shows all of it. The box caps the height, the image keeps its shape.
            className="block max-h-[28rem] w-auto max-w-full object-contain"
            onError={() => setBroken(true)}
          />
        )}
        {!broken && (
          <span
            aria-hidden
            className={cn(
              'absolute top-1.5 right-1.5 grid size-6 place-items-center rounded-md',
              'border border-line bg-overlay/90 text-ink-3 opacity-0 transition-opacity',
              'group-hover/media:opacity-100 group-focus-visible/media:opacity-100'
            )}
          >
            <Maximize2 className="size-3" />
          </span>
        )}
      </button>

      <figcaption className="flex items-center gap-2 text-[0.68rem] text-ink-3">
        <span className="min-w-0 truncate" title={path}>
          {name}
        </span>
        {meta.size_human && <span className="shrink-0 text-ink-disabled">{meta.size_human}</span>}
        <a
          href={rawUrl(target)}
          download={name}
          aria-label={`Download ${name}`}
          title={`Download ${name}`}
          className="ml-auto flex shrink-0 items-center gap-1 text-ink-disabled underline underline-offset-2 hover:text-ink-3"
        >
          <Download className="size-3" aria-hidden />
          Download
        </a>
      </figcaption>
    </figure>
  )
}

/**
 * Every file a turn handed over, in the order it named them.
 *
 * A `MEDIA:` directive is the assistant saying "here, take this", so the files belong *with the
 * answer* rather than buried in the activity that produced them — the same reasoning that puts
 * `producedFiles` beside the answer rather than inside a fold (`components/activity.ts`).
 */
export function MediaFigures({ paths, className }: { paths: readonly string[]; className?: string }) {
  if (paths.length === 0) return null

  return (
    <div className={cn('flex flex-col gap-3', className)} data-slot="turn-media">
      {paths.map(path => (
        <MediaFigure key={path} path={path} />
      ))}
    </div>
  )
}
