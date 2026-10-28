import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, ExternalLink, FileSearch, LoaderCircle, RotateCcw, X } from 'lucide-react'
import type { PreviewMeta } from '@shared/wire'
import { useApp } from '../state/app-context'
import { cn } from '../ui/cn'
import { PdfView } from './PdfView'
import { Markdown } from './Markdown'
import { CSV_MAX_ROWS, parseDelimited } from './csv'
import {
  TEXT_PREVIEW_BYTES,
  downloadUrl,
  embedUrlFor,
  extensionOf,
  ownOrigin,
  previewPlan,
  rawUrl,
  sanitizeSandbox,
  sitePlan,
  targetDetail,
  targetKey,
  targetName,
  type PreviewPlan,
  type PreviewTarget,
  type SiteTarget
} from './preview'
import { currentTarget, type PreviewStack } from './preview-stack'

/**
 * The preview sidebar — the one surface a file or a page is looked at in.
 *
 * the file-preview design §4 D3. It is a column on the right of the conversation, not a modal over
 * it: a document is something to read *while* talking about it, and a `<dialog>` makes the chat
 * underneath unreachable exactly when the operator wants to ask about what they are looking at.
 * The pane sits inside the chat, beside the transcript and the composer, so both stay live.
 *
 * What it remembers is `preview-stack.ts`: everything opened in this conversation, longest-standing
 * last, with the one in front on show. Below the `md` breakpoint there is no room for two columns,
 * so the same pane covers the conversation instead — one component, two widths.
 *
 * Everything it knows comes from the server. It asks `/meta` first — one small request — and then
 * does what the answer says, which is what keeps a TIFF from being pointed at an `<img>` and a
 * `.docx` from being pointed at a frame. When the server refuses, its own sentence is shown,
 * because a refusal that arrived with a reason should not be replaced by a generic one.
 *
 * Three states, always: loading, a plan, or a failure. A frame that failed to load never gets to
 * look like a frame that loaded an empty document (invariant 3).
 */
export function PreviewSidebar({
  stack,
  onShow,
  onDismiss,
  onClose
}: {
  stack: PreviewStack
  onShow: (target: PreviewTarget) => void
  onDismiss: (target: PreviewTarget) => void
  onClose: () => void
}) {
  const { bff } = useApp()
  const target = currentTarget(stack)
  const [meta, setMeta] = useState<PreviewMeta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const key = target ? targetKey(target) : ''

  // The pane takes the focus when it opens, which is what makes the keyboard work in it: the
  // arrow keys and Page Down scroll the document, and Escape (below) closes what is being read.
  // Without this, focus would still be on the chip that was clicked and neither would reach here.
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bodyRef.current?.focus()
  }, [])

  // Ask what this is, every time the target changes. `attempt` is the Retry button.
  useEffect(() => {
    if (!target || target.kind === 'site') {
      setMeta(null)
      setError(null)
      setLoading(false)
      return
    }
    let live = true
    setLoading(true)
    setError(null)
    setMeta(null)
    const request =
      target.kind === 'attachment'
        ? bff.attachmentMeta(target.id)
        : bff.fileMeta(target.path)
    request
      .then(result => {
        if (live) setMeta(result)
      })
      .catch((cause: unknown) => {
        if (live) setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
    // `key` rather than `target`: the identity of a target is its key, and a new object with the
    // same path must not buy a second request.
  }, [key, attempt, bff])

  const plan = useMemo(
    () => (meta && target ? previewPlan(meta, rawUrl(target)) : null),
    [meta, target]
  )

  return (
    <aside
      aria-label="Previews"
      // Escape closes the pane, but only when the focus is inside it: a global handler would take
      // the key away from the composer, the activity disclosures and every dialog in the app.
      onKeyDown={event => {
        if (event.key === 'Escape') onClose()
      }}
      className={cn(
        'absolute inset-0 z-30 flex min-h-0 flex-col border-l border-line bg-surface',
        'md:relative md:inset-auto md:w-[min(24rem,40vw)] lg:w-[min(28rem,34vw)]'
      )}
    >
      <header className="flex shrink-0 items-start gap-2 border-b border-line px-3 py-2.5">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h2 className="text-display truncate text-sm text-ink">
            {target ? targetName(target) : 'Previews'}
          </h2>
          <span
            className="truncate font-mono text-[0.68rem] text-ink-3"
            title={target ? targetDetail(target) : undefined}
          >
            {target ? targetDetail(target) : 'Files, documents and pages open here'}
          </span>
        </div>
        <button
          type="button"
          aria-label="Hide previews"
          title="Hide previews"
          onClick={onClose}
          className="grid size-7 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-hover hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </header>

      {stack.items.length > 1 && (
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line px-2 py-1.5">
          {stack.items.map(item => {
            const itemKey = targetKey(item)
            const active = itemKey === key
            return (
              <span
                key={itemKey}
                className={cn(
                  'flex shrink-0 items-center gap-0.5 rounded-md border pr-0.5',
                  active ? 'border-line-strong bg-raised' : 'border-transparent hover:bg-hover'
                )}
              >
                <button
                  type="button"
                  onClick={() => onShow(item)}
                  title={targetDetail(item) || targetName(item)}
                  className={cn(
                    'max-w-[9rem] truncate px-1.5 py-0.5 text-left text-xs',
                    active ? 'text-ink' : 'text-ink-3 hover:text-ink-2'
                  )}
                >
                  {targetName(item)}
                </button>
                <button
                  type="button"
                  aria-label={`Close ${targetName(item)}`}
                  onClick={() => onDismiss(item)}
                  className="grid size-4 place-items-center rounded text-ink-disabled hover:bg-hover hover:text-ink"
                >
                  <X className="size-2.5" aria-hidden />
                </button>
              </span>
            )
          })}
        </div>
      )}

      <div
        ref={bodyRef}
        tabIndex={-1}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3"
      >
        {!target && <Empty />}
        {target && loading && <Busy />}
        {target && !loading && error && (
          <Failure message={error} onRetry={() => setAttempt(value => value + 1)} />
        )}
        {target && !loading && !error && target.kind === 'site' && <SiteView target={target} />}
        {target && !loading && !error && plan && meta && <Body plan={plan} meta={meta} target={target} />}
      </div>

      {/* A file that could not be read gets no download button: the failure above carries its own
          retry, and offering the bytes a second way when the first said "no such file" is a promise
          the pane cannot keep. A site has no such state — its footer is the way out. */}
      {target && !error && (
        <footer className="flex shrink-0 items-center justify-between gap-2 border-t border-line px-3 py-2">
          <span className="truncate font-mono text-[0.65rem] text-ink-3">
            {meta ? `${meta.mime} · ${meta.size_human}` : ''}
          </span>
          {target.kind === 'site' ? (
            <a
              href={target.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-line-strong px-2 text-xs text-ink hover:bg-hover"
            >
              <ExternalLink className="size-3.5" aria-hidden />
              Open in a tab
            </a>
          ) : (
            <a
              href={downloadUrl(target)}
              download={targetName(target)}
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-line-strong px-2 text-xs text-ink hover:bg-hover"
            >
              <Download className="size-3.5" aria-hidden />
              Download
            </a>
          )}
        </footer>
      )}
    </aside>
  )
}

/** Nothing open: the pane explains itself rather than sitting blank. */
function Empty() {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <FileSearch className="size-6 text-ink-disabled" aria-hidden />
      <p className="text-sm text-ink-2">Nothing open.</p>
      <p className="text-xs text-ink-3">
        A file name, an attachment chip or a link in the conversation opens here, beside what was
        said about it — and it stays open while you keep talking.
      </p>
    </div>
  )
}

function Busy() {
  return (
    <p className="flex items-center gap-2 py-10 text-sm text-ink-3">
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      Reading the file…
    </p>
  )
}

function Failure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2.5">
      <p className="text-sm text-danger">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 text-xs text-ink-2 underline underline-offset-2 hover:text-ink"
      >
        <RotateCcw className="size-3.5" aria-hidden />
        Try again
      </button>
    </div>
  )
}

function Body({
  plan,
  meta,
  target
}: {
  plan: PreviewPlan
  meta: PreviewMeta
  target: PreviewTarget
}) {
  if (plan.mode === 'image') {
    return (
      <figure className="flex items-start justify-center rounded-lg bg-canvas/40 p-1.5">
        <img
          src={plan.url}
          alt={meta.name}
          draggable={false}
          className="max-w-full rounded object-contain"
        />
      </figure>
    )
  }

  if (plan.mode === 'pdf') {
    // Rendered here, page by page, rather than framed: a frame around a PDF depends on a browser
    // plugin that is not in every browser, and the sandbox test that would have justified it
    // answered with a blank surface (the file-preview design §4 D4).
    return <PdfView url={plan.url} name={meta.name} />
  }

  if (plan.mode === 'media') {
    return (
      <div className="rounded-lg bg-black/60 p-1.5">
        {plan.element === 'audio' ? (
          <audio src={plan.url} controls preload="metadata" className="w-full" />
        ) : (
          <video
            src={plan.url}
            controls
            preload="metadata"
            playsInline
            className="max-h-[60vh] w-full rounded"
          />
        )}
      </div>
    )
  }

  if (plan.mode === 'html') {
    return <HtmlBody target={target} reason={plan.reason} note={plan.note} />
  }

  if (plan.mode === 'markdown') {
    return <MarkdownBody target={target} note={plan.note} />
  }

  if (plan.mode === 'csv') {
    return <CsvBody target={target} delimiter={plan.delimiter ?? ','} note={plan.note} />
  }

  if (plan.mode === 'text') {
    return <TextBody target={target} note={plan.note} />
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface/40 px-3 py-3">
      <p className="text-sm text-ink-2">{plan.reason ?? plan.note}</p>
      <p className="text-[0.68rem] text-ink-disabled">
        {extensionOf(meta.name).toUpperCase() || meta.mime} · {meta.size_human}
      </p>
    </div>
  )
}

/**
 * A text file's bytes, as text. Every text-shaped body shares this — the text view, the rendered
 * markdown view, the HTML frame, the CSV table, and each one's source view — because the fetch
 * and its three states are identical and only the drawing differs.
 */
function useTextPreview(target: PreviewTarget) {
  const { bff } = useApp()
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    setText(null)
    setError(null)
    bff
      .textPreview(rawUrl(target), TEXT_PREVIEW_BYTES)
      .then(value => live && setText(value))
      .catch(
        (cause: unknown) => live && setError(cause instanceof Error ? cause.message : String(cause))
      )
    return () => {
      live = false
    }
  }, [bff, target, attempt])

  return { text, error, retry: () => setAttempt(value => value + 1) }
}

/**
 * An HTML file: the rendered page first, with its source one click away.
 *
 * The frame is `srcdoc` with `sandbox="allow-scripts allow-forms allow-downloads"` and no
 * `allow-same-origin`, which gives the document an *opaque* origin: its scripts are contained,
 * and it cannot read this app's storage, call its API with the operator's session, or reach the
 * DOM around it. That is containment by construction rather than by sanitising, which is why this
 * is the one place a page may be rendered at all (the file-preview design §4 D5).
 *
 * It opens rendered rather than on its source because opening the file is the operator's
 * deliberate act: a produced document is here to be read, and a `Show the source` toggle keeps
 * the bytes available without making the source the first thing seen. The rule that matters is
 * unchanged — the page is never executed merely because the transcript was scrolled past.
 */
export function HtmlBody({
  target,
  reason,
  note
}: {
  target: PreviewTarget
  reason?: string
  note?: string
}) {
  const [rendered, setRendered] = useState(true)
  const { text: source, error, retry } = useTextPreview(target)

  if (error) return <Failure message={error} onRetry={retry} />
  if (source === null) return <Busy />

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
        <span>{reason}</span>
        <button
          type="button"
          onClick={() => setRendered(value => !value)}
          className="text-ink-2 underline underline-offset-2 hover:text-ink"
        >
          {rendered ? 'Show the source' : 'Show the rendered page'}
        </button>
      </div>

      {rendered ? (
        <iframe
          // No `src`, so no request of ours is involved: the document is the file's own text.
          srcDoc={source}
          title={targetName(target)}
          sandbox={sanitizeSandbox('allow-scripts allow-forms allow-downloads')}
          referrerPolicy="no-referrer"
          className="h-[60vh] min-h-72 w-full rounded-lg border border-line bg-white"
        />
      ) : (
        <pre className="overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono text-[0.72rem] whitespace-pre-wrap text-ink-2">
          {source}
        </pre>
      )}
      {note && <p className="text-[0.68rem] text-ink-disabled">{note}</p>}
    </div>
  )
}

/** A text file: fetched as bytes, drawn as text. Never framed, never injected as HTML. */
function TextBody({ target, note }: { target: PreviewTarget; note?: string }) {
  const { text, error, retry } = useTextPreview(target)

  if (error) return <Failure message={error} onRetry={retry} />
  if (text === null) return <Busy />

  return (
    <div className="flex flex-col gap-1.5">
      <pre className="overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono text-[0.72rem] leading-relaxed whitespace-pre-wrap text-ink-2">
        {text}
      </pre>
      {note && <p className="text-[0.68rem] text-ink-disabled">{note}</p>}
    </div>
  )
}

/**
 * A CSV or TSV file: the table first, with its source one click away.
 *
 * A comma-separated file drawn as comma-separated text is the same failure as a markdown file
 * drawn as asterisks: the operator asked to look at the data, not at its punctuation. The parser
 * is `csv.ts` — a tolerant reader for quoted fields, embedded commas/newlines and CRLF, no
 * dependency and no evaluation. The header is the first row, which is what every file we write
 * has; a large file says how many rows it is not showing, and the source is still there.
 */
export function CsvBody({
  target,
  delimiter,
  note
}: {
  target: PreviewTarget
  delimiter: ',' | '\t'
  note?: string
}) {
  const [source, setSource] = useState(false)
  const { text, error, retry } = useTextPreview(target)
  const table = useMemo(() => parseDelimited(text ?? '', delimiter), [text, delimiter])

  if (error) return <Failure message={error} onRetry={retry} />
  if (text === null) return <Busy />

  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setSource(value => !value)}
          className="text-[0.68rem] text-ink-3 underline underline-offset-2 hover:text-ink"
        >
          {source ? 'Show the table' : 'Show the source'}
        </button>
      </div>

      {source ? (
        <pre className="overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono text-[0.72rem] leading-relaxed whitespace-pre-wrap text-ink-2">
          {text}
        </pre>
      ) : table.header.length === 0 ? (
        <p className="text-sm text-ink-2">This file has no rows.</p>
      ) : (
        <>
          <div className="max-h-[60vh] overflow-auto rounded-lg border border-line">
            <table className="w-max min-w-full border-collapse text-sm">
              <thead className="sticky top-0 z-10 bg-raised">
                <tr>
                  {table.header.map((cell, index) => (
                    <th
                      key={index}
                      scope="col"
                      className="border-b border-line px-2.5 py-1.5 text-left font-semibold whitespace-nowrap text-ink"
                    >
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="border-b border-line/50 last:border-0">
                    {table.header.map((_, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="max-w-[24rem] px-2.5 py-1.5 align-top whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere]"
                      >
                        {row[cellIndex] ?? ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {table.truncated && (
            <p className="text-[0.68rem] text-ink-disabled">
              Showing the first {CSV_MAX_ROWS} rows of {table.totalRows}. Download it for the
              rest.
            </p>
          )}
          {table.rows.length === 0 && (
            <p className="text-[0.68rem] text-ink-disabled">The file has a header but no data rows.</p>
          )}
        </>
      )}

      {note && <p className="text-[0.68rem] text-ink-disabled">{note}</p>}
    </div>
  )
}

/**
 * A markdown file: the document, with its own source one click away.
 *
 * the file-preview design refused this until now, on the argument that showing the source is
 * honest — and it is, for a file whose formatting nobody asked to see. What changed is the
 * request: a `.md` delivered in a conversation is a document someone wants to *read*, and
 * `**bold**` printed as asterisks is the renderer failing at the one thing it was opened for.
 *
 * The source stays, in the same shape the HTML and CSV bodies use: the document shows first, and
 * the source is one click away. Rendering is `Markdown.tsx`: React elements parsed from the text,
 * no HTML, no injection — so a `.md` full of markup shows that markup as words, exactly as
 * `previews.py` intends a text file to.
 */
function MarkdownBody({ target, note }: { target: PreviewTarget; note?: string }) {
  const [source, setSource] = useState(false)
  const { text, error, retry } = useTextPreview(target)

  if (error) return <Failure message={error} onRetry={retry} />
  if (text === null) return <Busy />

  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setSource(value => !value)}
          className="text-[0.68rem] text-ink-3 underline underline-offset-2 hover:text-ink"
        >
          {source ? 'Show the formatted document' : 'Show the source'}
        </button>
      </div>

      {source ? (
        <pre className="overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono text-[0.72rem] leading-relaxed whitespace-pre-wrap text-ink-2">
          {text}
        </pre>
      ) : (
        <Markdown text={text} />
      )}

      {note && <p className="text-[0.68rem] text-ink-disabled">{note}</p>}
    </div>
  )
}

/**
 * A website, after a click.
 *
 * Nothing is requested from the site until the operator asks for it: the facade is the privacy
 * gate, and it is also the honest one, because most of the web refuses to be framed at all
 * (`X-Frame-Options`, `frame-ancestors`). A frame cannot be introspected cross-origin, so the
 * fallback is always offered rather than guessed at — and when a site does refuse, the snapshot
 * the BFF already knows how to take is one click away.
 */
function SiteView({ target }: { target: SiteTarget }) {
  const { bff } = useApp()
  const [loaded, setLoaded] = useState(false)
  const [snapshot, setSnapshot] = useState<string | null>(null)
  const [snapshotError, setSnapshotError] = useState<string | null>(null)
  const [taking, setTaking] = useState(false)
  // The snapshot is a network fetch like every other one in this file: it says it is working, it
  // cannot land after the pane is gone, and a second click while it is in flight is ignored
  // (the internal audit WEB-17).
  const alive = useRef(true)
  useEffect(() => () => {
    alive.current = false
  }, [])
  const plan = useMemo(() => sitePlan(target.url, ownOrigin()), [target.url])
  // A watch page refuses to be framed and its embed endpoint does not; the two hosts that both
  // document and allow it are rewritten here, and everything else is left exactly as written.
  const embed = useMemo(() => embedUrlFor(target.url), [target.url])

  if (!plan.embeddable) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface/40 px-3 py-3">
        <p className="text-sm text-ink-2">{plan.reason}</p>
        <a
          href={target.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex w-fit items-center gap-1.5 text-xs break-all text-accent underline underline-offset-2"
        >
          <ExternalLink className="size-3.5 shrink-0" aria-hidden />
          {target.url}
        </a>
      </div>
    )
  }

  if (!loaded) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-line bg-surface/40 px-3 py-3">
        <p className="text-sm text-ink-2">
          Loading this page means your browser contacting {targetName(target)}. Nothing has been
          requested yet.
        </p>
        <button
          type="button"
          onClick={() => setLoaded(true)}
          className="inline-flex h-8 items-center gap-2 rounded-lg border border-line-strong px-3 text-xs text-ink hover:bg-hover"
        >
          <ExternalLink className="size-3.5" aria-hidden />
          Load {targetName(target)}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <iframe
        src={embed}
        title={targetName(target)}
        sandbox={sanitizeSandbox(plan.sandbox)}
        referrerPolicy="no-referrer"
        loading="lazy"
        className="h-[60vh] min-h-72 w-full rounded-lg border border-line bg-white"
      />
      <div className="flex flex-wrap items-center gap-2 text-[0.68rem] text-ink-disabled">
        <span>
          A blank frame usually means the site refuses to be embedded. It cannot tell us why, so:
        </span>
        <button
          type="button"
          disabled={taking}
          onClick={() => {
            if (taking) return
            setTaking(true)
            setSnapshotError(null)
            bff
              .urlSnapshot(target.url)
              .then(result => {
                if (!alive.current) return
                setSnapshot(result.text?.trim() ? result.text : 'That page had no readable text.')
              })
              .catch((cause: unknown) => {
                if (!alive.current) return
                setSnapshotError(cause instanceof Error ? cause.message : String(cause))
              })
              .finally(() => {
                if (alive.current) setTaking(false)
              })
          }}
          className="text-ink-2 underline underline-offset-2 hover:text-ink disabled:opacity-60"
        >
          {taking ? 'reading the page…' : 'show the page’s text'}
        </button>
        <a
          href={target.url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-ink-2 underline underline-offset-2 hover:text-ink"
        >
          open in a tab
        </a>
      </div>
      {snapshotError && <p className="text-xs text-danger">{snapshotError}</p>}
      {snapshot && (
        <pre className="max-h-72 overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono text-[0.7rem] whitespace-pre-wrap text-ink-2">
          {snapshot}
        </pre>
      )}
    </div>
  )
}
