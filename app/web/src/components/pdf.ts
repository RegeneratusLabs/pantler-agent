/**
 * PDF rendering — the two decisions that are worth testing on their own.
 *
 * the file-preview design §4 D4 chose the browser's own viewer, in a frame, on the argument that
 * the least code is the least code. That decision was then falsified by the only test that
 * matters: a sandboxed frame around our own PDF answered with a blank surface. Rather than ship a
 * frame whose behaviour depends on which browser and which plugin happened to be installed, the
 * sheet renders the pages itself with **pdf.js** — a canvas per page, no frame, no plugin, and the
 * same result on a desktop and on a phone.
 *
 * That moves the questions from "does the browser do it?" to two arithmetic ones, and those are
 * here rather than inside the component so they can be asserted:
 *
 *   - how wide a page draws, given the column it is in;
 *   - when a page is allowed to draw at all, because a 600-page document would otherwise put 600
 *     canvases in memory as the operator scrolls.
 */

/**
 * The most pages that may be rasterised before the viewer asks.
 *
 * A cap rather than a window: pages render as they come into view, and this is the ceiling on how
 * many *distinct* pages may ever be drawn. Past it the viewer offers to keep going, which is a
 * decision the operator makes with a number in front of them instead of a tab that quietly eats a
 * gigabyte.
 */
export const PAGE_RENDER_CAP = 60

/** A page never draws wider than this multiple of its natural size: past it, pixels are wasted. */
const MAX_SCALE = 2

/** Nor narrower: a page scaled to a sliver is not a preview. */
const MIN_SCALE = 0.15

/**
 * The scale that fits one page's width into the column, within reason.
 *
 * `viewportWidth` is the page's own width at scale 1; `columnWidth` is what is available. A
 * zero-width column — the first paint, before layout — is not a scale of zero, it is "not yet", so
 * this answers the minimum rather than producing an invisible canvas.
 */
export function fitScale(viewportWidth: number, columnWidth: number, maxScale = MAX_SCALE): number {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return 1
  if (!Number.isFinite(columnWidth) || columnWidth <= 0) return MIN_SCALE
  const scale = columnWidth / viewportWidth
  return Math.min(Math.max(scale, MIN_SCALE), Math.max(maxScale, MIN_SCALE))
}

/**
 * How much larger than its natural size a page may draw before the operator asked for it.
 *
 * The device pixel ratio is the reason this exists: a canvas drawn at scale 1 on a 2× screen is
 * blurry, so the *backing store* is multiplied by the ratio while the CSS size is not.
 */
export function backingScale(scale: number, devicePixelRatio = 1): number {
  const ratio = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? Math.min(devicePixelRatio, 3) : 1
  return scale * ratio
}

/**
 * Whether a page may be rasterised yet.
 *
 * True while the document is small enough to draw, or once the operator has said to keep going.
 * This is checked at draw time rather than at render time so that a document that is under the cap
 * behaves exactly as it would with no cap at all.
 */
export function canRenderPage(
  renderedCount: number,
  totalPages: number,
  expanded: boolean,
  cap = PAGE_RENDER_CAP
): boolean {
  if (expanded) return true
  if (totalPages <= cap) return true
  return renderedCount < cap
}

/** The sentence the viewer shows instead of silently stopping. */
export function capNote(totalPages: number, cap = PAGE_RENDER_CAP): string | undefined {
  if (totalPages <= cap) return undefined
  return `Showing the first ${cap} pages as you scroll. This document has ${totalPages}.`
}
