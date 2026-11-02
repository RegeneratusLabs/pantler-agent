/**
 * Previews — the one place that decides what a file reference *is* and how it may be shown.
 *
 * The design is the file-preview design. Three inputs reach this module and they are all the
 * same shape when they get here: an attachment the operator sent (an id, and the path the store
 * wrote), a path the agent read or wrote, and a URL. Everything that follows — which renderer,
 * which URL to fetch, whether a frame is allowed at all — is decided here rather than in the
 * components, for the same reason the reducer is one pure function: two screens that disagree
 * about what a file is have no way to tell which of them is right.
 *
 * The security decisions live here too, and they are the reason this file exists at all:
 *
 *   - **`isEmbeddableUrl`** refuses anything that is not an absolute `http(s)` URL on another
 *     origin. A frame is how untrusted bytes reach a browser, so the door is checked by the
 *     router and not by hope.
 *   - **`sanitizeSandbox`** is an *allowlist*, not a blocklist, and it drops unrecognised tokens
 *     case-insensitively. The lesson is the reference's (`sandboxed-frame.tsx`): the sandbox
 *     attribute is a case-insensitive token set, so `ALLOW-SAME-ORIGIN` sails past a
 *     case-sensitive check and the browser honours it. An allowlist cannot be spelled around.
 *   - **The server is the authority on what may be inline.** `render` and `inline` come from
 *     `/api/files/meta`; nothing here guesses a mime from a file name and then points an element
 *     at it.
 *
 * It is pure and it is tested, because the alternative is a component that is only exercised by
 * clicking it in a browser.
 */

import { formatBytes } from '@shared/attachments'
import { linkKind } from './markdown-parse'

/** How much of a text file the preview pane will show before it says "there is more". */
export const TEXT_PREVIEW_BYTES = 512 * 1024

/** The `render` words the BFF answers with. `html` is not one of them: see `PreviewMode`. */
export type PreviewRender = 'image' | 'pdf' | 'media' | 'text' | 'download'

/** What `/api/files/meta` (and `/api/attachments/{id}/meta`) answer with. */
export interface FileMeta {
  path: string
  name: string
  mime: string
  size: number
  size_human: string
  /** The upload-side vocabulary: image · document · text · archive · folder · url · other. */
  kind: string
  render: PreviewRender
  content_type: string
  disposition: string
  /** Whether an element may point at the byte route and have the browser render it. */
  inline: boolean
}

export interface AttachmentTarget {
  kind: 'attachment'
  id: string
  path: string
  name: string
  detail?: string
}

export interface FileTarget {
  kind: 'file'
  path: string
  name: string
  detail?: string
}

export interface SiteTarget {
  kind: 'site'
  url: string
  label?: string
}

export type PreviewTarget = AttachmentTarget | FileTarget | SiteTarget

// ------------------------------------------------------------------- targets

/** The name to show. A URL shows its host, because a full URL is not a name. */
export function targetName(target: PreviewTarget): string {
  if (target.kind === 'site') return target.label?.trim() || hostOf(target.url) || target.url
  return target.name || nameOf(target.path)
}

/** The second line: where it is, in the fewest characters that still identify it. */
export function targetDetail(target: PreviewTarget): string {
  if (target.kind === 'site') return hostOf(target.url) ?? ''
  return target.kind === 'attachment' ? (target.detail ?? '') : target.path
}

/** A stable key, so a React list can key on a target and the pane can notice it changed. */
export function targetKey(target: PreviewTarget): string {
  if (target.kind === 'site') return `site:${target.url}`
  if (target.kind === 'attachment') return `attachment:${target.id}`
  return `file:${target.path}`
}

export function fileTarget(path: string, detail?: string): FileTarget {
  return { kind: 'file', path, name: nameOf(path), detail }
}

export function attachmentTarget(input: {
  id: string
  path: string
  name: string
  detail?: string
}): AttachmentTarget {
  return { kind: 'attachment', id: input.id, path: input.path, name: input.name, detail: input.detail }
}

/**
 * A website target — and the one place "a site target is always an http(s) address" is kept.
 *
 * The callers all gate their own links today, which is exactly why this used to do nothing: an
 * invariant that lives only in callers is one new caller away from being false, and a
 * `javascript:` or protocol-relative address that reached the pane would be an address the frame
 * and the "open in a tab" link both trust. `linkKind` is the same classifier the markdown
 * renderer uses, so the two cannot disagree; `null` means the caller draws the words as text
 * instead (the internal security audit A19-WEB-3).
 */
export function siteTarget(url: string, label?: string): SiteTarget | null {
  const trimmed = (url ?? '').trim()
  if (linkKind(trimmed) !== 'site') return null
  return { kind: 'site', url: trimmed, label }
}

/** The last segment of a path, which is the only part a person reads. */
export function nameOf(path: string): string {
  const trimmed = (path ?? '').replace(/[\\/]+$/, '')
  if (!trimmed) return path ?? ''
  const parts = trimmed.split(/[\\/]/)
  return parts[parts.length - 1] || trimmed
}

export function hostOf(url: string): string | undefined {
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return undefined
  }
}

/**
 * A file name's extension, lower-cased, without the dot — used for an icon and for nothing else.
 * It is deliberately *not* used to decide whether something can be rendered: that answer comes
 * from the server, which read the bytes.
 */
export function extensionOf(name: string): string {
  const match = /\.([A-Za-z0-9]{1,8})$/.exec((name ?? '').trim())
  return match ? match[1].toLowerCase() : ''
}

// ---------------------------------------------------------------------- urls

const API = '/api'

/** The bytes, for an element to point at. An attachment is reached by id, a file by path. */
export function rawUrl(target: PreviewTarget): string {
  if (target.kind === 'attachment') {
    return `${API}/attachments/${encodeURIComponent(target.id)}/raw`
  }
  if (target.kind === 'file') {
    return `${API}/files/raw?path=${encodeURIComponent(target.path)}`
  }
  return target.url
}

/** The metadata, which is what says whether pointing an element at `rawUrl` is allowed. */

/** A download link. The same bytes as `rawUrl`; the disposition is the server's business. */
export function downloadUrl(target: PreviewTarget): string {
  return rawUrl(target)
}

// --------------------------------------------------------------------- plans

/**
 * What the preview pane will actually do.
 *
 * `html` is the one mode the server does not name: a page type is *always* a download on the
 * wire (`previews.py` is firm about that), and the pane is where an HTML file the operator
 * explicitly asked for becomes a document — rendered from `srcdoc` inside a frame with an opaque
 * origin, which is containment rather than a promise (the file-preview design §4 D5). The pane
 * opens on the rendered page; the source is one click away. Opening the file is the deliberate
 * act, so the page is never executed merely because it was scrolled past.
 *
 * `markdown` is the second: the server calls a `.md` file `render: "text"`, which is right — its
 * bytes are text — and the pane reads that name and the file's own name together and draws the
 * document rather than the punctuation (`markdown.ts`). Nothing about the serving rule changes;
 * the bytes still arrive as an octet-stream and are still never handed to the HTML parser.
 *
 * `csv` is the third: a table is the finished form of delimited data, so the pane draws it as
 * one (`csv.ts`). The bytes are still text; the parser never evaluates anything.
 */
export type PreviewMode =
  | 'image'
  | 'pdf'
  | 'media'
  | 'text'
  | 'markdown'
  | 'csv'
  | 'html'
  | 'download'

export interface PreviewPlan {
  mode: PreviewMode
  /** For `media`: which element plays it. */
  element?: 'audio' | 'video'
  /** For `csv`: the delimiter its own name or mime declares. */
  delimiter?: ',' | '\t'
  /** What the element should fetch. */
  url: string
  /** The sentence shown when the mode cannot show everything, or cannot show anything. */
  note?: string
  /** A sentence for a refusal, when the file exists but will not be rendered here. */
  reason?: string
}

/**
 * What to do with a file, given what the server said about it.
 *
 * `download` is not a failure — it is the honest answer for an office document, an archive, an
 * SVG, or an HTML file, and the note says which of those and why. The one thing this never does
 * is point an element at something the server will not inline and then blame the browser for an
 * empty frame.
 */
export function previewPlan(meta: FileMeta, url: string): PreviewPlan {
  if (meta.render === 'image' && meta.inline) {
    return { mode: 'image', url }
  }
  if (meta.render === 'pdf' && meta.inline) {
    return { mode: 'pdf', url }
  }
  if (meta.render === 'media' && meta.inline) {
    return { mode: 'media', element: meta.mime.startsWith('audio/') ? 'audio' : 'video', url }
  }
  if (isHtml(meta)) {
    // Opened rendered: opening the file is the operator's deliberate act, and the pane is the one
    // place a page becomes a document. The source is a click away, and the frame is still an
    // opaque-origin sandbox, so nothing about the containment changes.
    return {
      mode: 'html',
      url,
      reason: 'Rendered from the file’s own text in a sandboxed frame; the page is never served on this app’s origin.',
      note: 'The frame has its own origin, so it cannot reach this app, its records or its session. A relative asset beside it will not load.'
    }
  }
  if (isMarkdown(meta)) {
    const oversized = meta.size > TEXT_PREVIEW_BYTES
    return {
      mode: 'markdown',
      url,
      note: oversized
        ? `Showing the first ${formatBytes(TEXT_PREVIEW_BYTES)} of ${meta.size_human}. Download it for the rest.`
        : undefined
    }
  }
  if (meta.render === 'text') {
    const oversized = meta.size > TEXT_PREVIEW_BYTES
    const note = oversized
      ? `Showing the first ${formatBytes(TEXT_PREVIEW_BYTES)} of ${meta.size_human}. Download it for the rest.`
      : undefined
    if (isCsv(meta)) {
      return { mode: 'csv', delimiter: csvDelimiter(meta), url, note }
    }
    return { mode: 'text', url, note }
  }
  return { mode: 'download', url, reason: refusalFor(meta) }
}

/** Whether a file is a page — the one type the server will never serve inline. */
export function isHtml(meta: FileMeta): boolean {
  const mime = (meta.mime || '').toLowerCase()
  return (
    mime === 'text/html' ||
    mime === 'application/xhtml+xml' ||
    /\.x?html?$/i.test(meta.name || '')
  )
}

/**
 * Whether a text file is a *document* rather than source.
 *
 * The mime is the server's answer and it comes first; the extension is the fallback, because a
 * `.md` uploaded under an unusual name still arrives as `text/plain` often enough to matter. The
 * file is served as an octet-stream either way — this changes how the pane draws it and nothing
 * about the door it came through.
 */
export function isMarkdown(meta: FileMeta): boolean {
  const mime = (meta.mime || '').toLowerCase()
  if (mime === 'text/markdown' || mime === 'text/x-markdown') return true
  return /\.(md|markdown|mdown|mkd)$/i.test(meta.name || '')
}

/**
 * Whether a text file is delimited data whose finished form is a table.
 *
 * Deliberately narrow: CSV and TSV, by the mime the server sniffed or the name the file was
 * written under. A `.txt` with commas in it is prose, not a table.
 */
export function isCsv(meta: FileMeta): boolean {
  const mime = (meta.mime || '').toLowerCase()
  if (mime === 'text/csv' || mime === 'application/csv') return true
  if (mime === 'text/tab-separated-values') return true
  return /\.(csv|tsv|tab)$/i.test(meta.name || '')
}

/** The delimiter the file itself declares: a tab for TSV, a comma for everything else. */
export function csvDelimiter(meta: FileMeta): ',' | '\t' {
  const mime = (meta.mime || '').toLowerCase()
  if (mime === 'text/tab-separated-values') return '\t'
  return /\.(tsv|tab)$/i.test(meta.name || '') ? '\t' : ','
}

/** Why a file is not rendered here. Every one of these is a decision, so every one is explained. */
export function refusalFor(meta: FileMeta): string {
  const mime = (meta.mime || '').toLowerCase()
  const name = (meta.name || '').toLowerCase()

  if (mime === 'text/html' || mime === 'application/xhtml+xml' || /\.x?html?$/.test(name)) {
    return 'A page is rendered in the sandboxed preview, never served on this app’s origin. Download it to open it in a browser tab.'
  }
  if (mime === 'image/svg+xml' || name.endsWith('.svg')) {
    return 'An SVG can carry script, so it is never rendered here. Download it, or open it in a browser tab.'
  }
  if (mime.startsWith('image/')) {
    // A TIFF, a HEIC: a picture the browser will not paint.
    return `${meta.mime} is not a format the browser can paint, so this is a download.`
  }
  if (meta.kind === 'document' || mime.startsWith('application/vnd.')) {
    return 'This is a document, and rendering one would mean a converter we do not ship. Download it to open it.'
  }
  if (meta.kind === 'archive' || mime.includes('zip') || mime.includes('tar') || mime.includes('gzip')) {
    return 'This is an archive. Download it and unpack it.'
  }
  return `No inline preview for ${meta.mime || 'this type'}.`
}

// ------------------------------------------------------------------- frames

/**
 * Sandbox tokens a website frame may carry.
 *
 * An allowlist, and deliberately without `allow-top-navigation` in any spelling: a guest that
 * can navigate the app window is a guest that can replace the app with a login page. The
 * navigation and popup-to-escape family is absent for that reason; `allow-popups` is present
 * because a site that opens a link in a new tab is doing what a browser does.
 */
export const FRAME_SANDBOX_TOKENS: ReadonlySet<string> = new Set([
  'allow-scripts',
  'allow-same-origin',
  'allow-forms',
  'allow-popups',
  'allow-downloads',
  'allow-modals',
  'allow-presentation',
  'allow-orientation-lock',
  'allow-pointer-lock'
])

/** What a frame gets when nobody asked for more. */
export const FRAME_SANDBOX_DEFAULT = 'allow-scripts allow-same-origin allow-forms allow-popups'

/**
 * Keep only tokens from the allowlist, lower-cased, and never return an empty string.
 *
 * An empty result falls back to the default rather than to no attribute at all: a frame with no
 * `sandbox` is a fully privileged frame, which is the one outcome worse than a wrong token.
 */
export function sanitizeSandbox(value?: string): string {
  const tokens = (value ?? '')
    .split(/\s+/)
    .map(token => token.trim().toLowerCase())
    .filter(token => token && FRAME_SANDBOX_TOKENS.has(token))
  const unique = [...new Set(tokens)]
  return unique.length > 0 ? unique.join(' ') : FRAME_SANDBOX_DEFAULT
}

/**
 * The embeddable form of a URL, for the two hosts that both document and allow framing.
 *
 * A watch page refuses to be framed; its `/embed` endpoint does not. Rewriting the one into the
 * other is the difference between "a blank frame and an apology" and a video that plays, and it
 * is done by *rebuilding* the URL from a validated id rather than by string-munging the original
 * — the id is the only part of the input that survives.
 */
export function embedUrlFor(url: string): string {
  const parsed = parseHttpUrl(url)
  if (!parsed) return url
  const host = parsed.hostname.replace(/^www\./, '').toLowerCase()

  if (host === 'youtu.be' || host === 'youtube.com' || host === 'youtube-nocookie.com' || host === 'm.youtube.com') {
    const id = youtubeId(parsed)
    if (id) return `https://www.youtube-nocookie.com/embed/${id}`
  }
  if (host === 'vimeo.com' || host === 'player.vimeo.com') {
    const id = /(\d{6,})/.exec(parsed.pathname)
    if (id) return `https://player.vimeo.com/video/${id[1]}`
  }
  return url
}

function youtubeId(parsed: URL): string | undefined {
  const fromQuery = parsed.searchParams.get('v')
  const candidate = fromQuery ?? (parsed.hostname.endsWith('youtu.be') ? parsed.pathname.slice(1) : parsed.pathname.split('/').filter(Boolean).pop())
  return candidate && /^[A-Za-z0-9_-]{11}$/.test(candidate) ? candidate : undefined
}

export interface SitePlan {
  /** Whether the URL may be framed at all. */
  embeddable: boolean
  sandbox: string
  /** Why not, when it may not. Shown instead of an empty frame. */
  reason?: string
}

/**
 * Whether a URL may be put in a frame, and with what sandbox.
 *
 * Refused: anything that is not `http(s)`, anything without a host, anything carrying
 * credentials, and **anything on our own origin** — a frame of our own `/api` would be a
 * same-origin document with our session's reach, which is the whole thing the sandbox exists to
 * prevent. The origin check is the important one and it is why this takes `ownOrigin`.
 */
export function sitePlan(url: string, ownOrigin?: string): SitePlan {
  const plan: SitePlan = { embeddable: false, sandbox: FRAME_SANDBOX_DEFAULT }
  // The same gate `siteTarget` applies, kept here too: a plan can never be asked to frame
  // something that is not an address at all, whatever a caller passes
  // (the internal security audit A19-WEB-3).
  if (linkKind(url) !== 'site') {
    return { ...plan, reason: 'Only an http or https address can be shown in a frame.' }
  }
  const parsed = parseHttpUrl(url)
  if (!parsed) {
    return { ...plan, reason: 'Only an http or https address can be shown in a frame.' }
  }
  if (parsed.username || parsed.password) {
    return { ...plan, reason: 'That address carries credentials, which this will not embed.' }
  }
  if (ownOrigin && parsed.origin === ownOrigin) {
    return {
      ...plan,
      reason: 'That address is this app’s own origin, so it is opened in a browser tab instead.'
    }
  }
  return { embeddable: true, sandbox: FRAME_SANDBOX_DEFAULT }
}

function parseHttpUrl(url: string): URL | null {
  try {
    const parsed = new URL((url ?? '').trim())
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
    if (!parsed.hostname) return null
    return parsed
  } catch {
    return null
  }
}

/** The window's own origin, or undefined where there is no window (a test, a server render). */
export function ownOrigin(): string | undefined {
  return typeof window === 'undefined' ? undefined : window.location.origin
}

// -------------------------------------------------------------------- labels

/** The word on a card's action, which is also a promise about what will happen. */

/** A short type word for a chip or a card, from the server's own kind plus the mime. */
