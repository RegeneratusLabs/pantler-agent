import { useEffect, useRef, useState } from 'react'
import { backingScale } from './pdf'
import { ChevronLeft, ChevronRight, LoaderCircle } from 'lucide-react'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
// pdf.js 6 decodes JBIG2 (the compression a scanned page almost always uses) and JPEG 2000 with
// WebAssembly, and without the URL it gives up silently: the page draws, and it is blank. A
// scanned delivery docket is exactly the document this app is handed, so these are not optional.
import jbig2Wasm from 'pdfjs-dist/wasm/jbig2.wasm?url'
import openjpegWasm from 'pdfjs-dist/wasm/openjpeg.wasm?url'
import qcmsWasm from 'pdfjs-dist/wasm/qcms_bg.wasm?url'
import { canRenderPage, capNote, fitScale } from './pdf'

/**
 * The directory pdf.js's decoders live in.
 *
 * `wasmUrl` is a base, not a file, and Vite emits every imported asset into one directory — so the
 * directory of any one of them is the base for all of them. Built from the resolved URL rather
 * than from a string, so it is right in dev (`/node_modules/…`) and in a build (`/assets/…`).
 */
const WASM_BASE = new URL('.', new URL(jbig2Wasm, window.location.href)).href
void openjpegWasm
void qcmsWasm

/**
 * A PDF, drawn page by page.
 *
 * the file-preview design §4 D4 wanted the browser's own viewer in a frame. The spike falsified
 * it: a sandboxed frame around our own PDF rendered nothing, and which browsers do better is not
 * something this code can find out. So the pages are rasterised here with pdf.js — no frame, no
 * plugin, one code path — and the things that usually make that fragile are handled explicitly:
 *
 *   - **the worker is a URL, not a guess.** `?url` hands Vite the worker file, so it is emitted and
 *     served like any other asset; pdf.js runs on the main thread only if that fails.
 *   - **pages draw as they come into view**, so opening a 200-page scan shows page one immediately
 *     rather than freezing while it renders all of it.
 *   - **the count is capped** (`pdf.ts`), and past the cap the viewer *says so* and offers to keep
 *     going, because a viewer that silently stops at page 60 is a viewer that lied.
 *   - **the canvas is scaled by the device pixel ratio**, so a page is sharp on the screen it is
 *     actually being read on.
 *
 * The import is lazy: pdf.js is around a megabyte, and a conversation that never opens a PDF
 * should never pay for it.
 */
export function PdfView({ url }: { url: string; name?: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [pages, setPages] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [columnWidth, setColumnWidth] = useState(0)
  const [expanded, setExpanded] = useState(false)
  // How many distinct pages have ever been rasterised. A *ref*, not state: a page drawing must
  // not re-render the viewer, and the count has to survive every render in between.
  const renderedRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    let loading: PDFDocumentLoadingTask | undefined
    setDoc(null)
    setPages(0)
    setError(null)
    setPage(1)
    renderedRef.current = 0

    void (async () => {
      const pdfjs = await import('pdfjs-dist')
      pdfjs.GlobalWorkerOptions.workerSrc = workerSrc
      // The *loading task* is what owns the worker, so it is what teardown destroys — otherwise
      // closing the preview leaves a worker and a half-read document behind it.
      loading = pdfjs.getDocument({ url, wasmUrl: WASM_BASE })
      const loaded = await loading.promise
      if (cancelled) return
      setDoc(loaded)
      setPages(loaded.numPages)
    })().catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
    })

    return () => {
      cancelled = true
      void loading?.destroy().catch(() => {})
    }
  }, [url])

  // The column's width is what a page fits to, and it changes with the window.
  useEffect(() => {
    const node = containerRef.current
    if (!node) return
    const measure = () => setColumnWidth(node.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [doc])

  const note = capNote(pages)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-center gap-2 text-xs text-ink-3">
        <button
          type="button"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => setPage(value => Math.max(1, value - 1))}
          className="grid size-6 place-items-center rounded border border-line text-ink-2 hover:bg-hover disabled:opacity-40"
        >
          <ChevronLeft className="size-3.5" aria-hidden />
        </button>
        <span className="tabular-nums">
          {pages ? `${page} / ${pages}` : '—'}
        </span>
        <button
          type="button"
          aria-label="Next page"
          disabled={pages === 0 || page >= pages}
          onClick={() => setPage(value => Math.min(pages, value + 1))}
          className="grid size-6 place-items-center rounded border border-line text-ink-2 hover:bg-hover disabled:opacity-40"
        >
          <ChevronRight className="size-3.5" aria-hidden />
        </button>
      </div>

      <div
        ref={containerRef}
        className="max-h-[70vh] overflow-auto rounded-lg border border-line bg-canvas/40 p-2"
      >
        {error && (
          <p className="p-3 text-sm text-danger">
            This PDF could not be read here ({error}). Download it, or open it on the machine.
          </p>
        )}
        {!error && !doc && (
          <p className="flex items-center gap-2 p-3 text-sm text-ink-3">
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
            Reading the document…
          </p>
        )}
        {doc && (
          <div className="flex flex-col items-center gap-2">
            {Array.from({ length: pages }, (_, index) => (
              <PdfPage
                key={index + 1}
                doc={doc}
                pageNumber={index + 1}
                columnWidth={columnWidth}
                expanded={expanded}
                renderedRef={renderedRef}
              />
            ))}
          </div>
        )}
      </div>

      {note && (
        <p className="flex items-center gap-2 text-[0.68rem] text-ink-disabled">
          {note}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="text-ink-2 underline underline-offset-2 hover:text-ink"
          >
            Keep going
          </button>
        </p>
      )}
    </div>
  )
}

/**
 * One page: a canvas that draws when it is scrolled near, and stays drawn.
 *
 * `renderedRef` is the shared count of pages that have ever drawn, which is what the cap is
 * counted against — a page that scrolled away is not un-drawn, because re-drawing it on the way
 * back is worse than the memory it holds.
 */
function PdfPage({
  doc,
  pageNumber,
  columnWidth,
  expanded,
  renderedRef
}: {
  doc: PDFDocumentProxy
  pageNumber: number
  columnWidth: number
  expanded: boolean
  renderedRef: { current: number }
}) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [near, setNear] = useState(pageNumber <= 2)
  const [drawn, setDrawn] = useState(false)

  useEffect(() => {
    const node = wrapperRef.current
    if (!node || near || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(entry => entry.isIntersecting)) setNear(true)
      },
      { rootMargin: '600px 0px' }
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [near])

  useEffect(() => {
    if (!near || drawn) return
    if (!canRenderPage(renderedRef.current, doc.numPages, expanded)) return

    let cancelled = false
    let task: { promise: Promise<void>; cancel(): void } | undefined

    void (async () => {
      const page = await doc.getPage(pageNumber)
      const natural = page.getViewport({ scale: 1 })
      const scale = fitScale(natural.width, columnWidth)
      // The tested rule, called rather than re-implemented: `backingScale` guards against a
      // nonsense `devicePixelRatio` (0, NaN, infinity) and the inline copy did not
      // (the internal audit WEB-17).
      const ratio = backingScale(scale, typeof window === 'undefined' ? 1 : window.devicePixelRatio)
      const viewport = page.getViewport({ scale: scale * ratio })
      const canvas = canvasRef.current
      if (cancelled || !canvas) return

      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      canvas.style.width = `${Math.floor(viewport.width / ratio)}px`
      canvas.style.height = `${Math.floor(viewport.height / ratio)}px`

      task = page.render({ canvas, viewport })
      await task.promise
      if (cancelled) return
      renderedRef.current += 1
      setDrawn(true)
    })().catch((cause: unknown) => {
      if (!cancelled) console.warn('pdf page failed', pageNumber, cause)
    })

    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [near, drawn, doc, pageNumber, columnWidth, expanded, renderedRef])

  return (
    <div ref={wrapperRef} className="w-full">
      <canvas
        ref={canvasRef}
        aria-label={`Page ${pageNumber}`}
        className={drawn ? 'mx-auto rounded bg-white shadow-sm' : 'hidden'}
      />
      {!drawn && (
        <div className="mx-auto h-[60vh] w-full max-w-[52rem] animate-pulse rounded bg-hover/40" />
      )}
    </div>
  )
}
