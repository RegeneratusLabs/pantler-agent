/**
 * The attachment turn format — and its parser.
 *
 * This file is one half of a frozen contract. `app/server/attachments.py` writes the format;
 * this file reads it back, because the engine stores only the composed text. After a reload
 * the transcript has nothing but that text to tell it which files a turn carried, so the
 * parse has to work on the *persisted* message exactly as it worked on the live one.
 *
 * The rules the parser may rely on (the attachment design §4):
 *
 *   - the block starts at the LAST line matching `Attached files (N):`, preceded by a blank
 *     line (or the start of the message);
 *   - an entry is `N. <name> — <detail>` followed by `   Path: <absolute path>`;
 *   - the block ends at the first line that is neither an entry nor an entry's Path;
 *   - everything the parser does not understand stays in the message.
 *
 * That last rule is the important one. A wire format this parser cannot read degrades to
 * showing the text verbatim, never to a dropped turn.
 */

export type AttachmentKind =
  | 'image'
  | 'document'
  | 'text'
  | 'archive'
  | 'folder'
  | 'url'
  | 'other'

/** What the BFF answers with. Snake case, because it is the server's shape, not React's. */
export interface WireAttachment {
  id: string
  session: string
  name: string
  mime: string
  size: number
  size_human: string
  kind: AttachmentKind
  created_at: number
  path: string
  rel_path: string | null
  source_url: string | null
  file_count: number
  files: Array<{ rel_path: string; size: number; sha256?: string; mime?: string }>
}

/** One attachment as it appears in a turn's text. */
export interface AttachmentRef {
  /** The store id, when the path names one — which is what makes a thumbnail possible. */
  id?: string
  name: string
  detail: string
  path: string
  image: boolean
}

export interface ParsedTurn {
  /** What the operator typed. */
  text: string
  attachments: AttachmentRef[]
  /** The listing's tail — the hint and any inlined file contents. Kept, not hidden. */
  context: string
  /** False when the block is absent or malformed: the caller shows `text` as it stands. */
  recognised: boolean
}

export const BLOCK_HEADER = (count: number) => `Attached files (${count}):`
export const BLOCK_HINT = 'Read a document with read_file; look at an image with vision_analyze.'

const HEADER_RE = /^Attached files \((\d+)\):$/
// Greedy, so the separator is the *last* " — " on the line: a real file name may contain one
// ("Invoice — March.pdf"), and a lazy group truncated the name to "Invoice" and pushed the rest
// into the detail (the internal audit CON-7).
const ENTRY_RE = /^(\d+)\. (.+) — (.+)$/
const PATH_RE = /^ {3}Path: (.+)$/
const ID_SEGMENT_RE = /^[0-9a-f]{12}$/

/**
 * The store's id, from the path the listing prints.
 *
 * The layout is `<root>/<session>/<id>/<name>` — and `<name>` may itself be a folder path — so the
 * id is the nearest twelve-hex directory above the file. Matching the *first* twelve-hex segment
 * anywhere in the path (the previous rule) reported a session directory named `abcdef123456` as
 * the attachment id, and the thumbnail then 404'd
 * (the internal audit CON-6).
 */
export function attachmentIdFromPath(path: string): string | undefined {
  const parts = path.split('/').filter(Boolean)
  for (let index = parts.length - 2; index >= 0; index--) {
    if (ID_SEGMENT_RE.test(parts[index])) return parts[index]
  }
  return undefined
}

export function parseTurn(input: string): ParsedTurn {
  const fallback: ParsedTurn = { text: input, attachments: [], context: '', recognised: false }
  if (!input) return fallback

  const lines = input.split('\n')

  // The last occurrence, not the first: a later block is the one this turn appended, and an
  // operator's own prose could plausibly contain the earlier spelling of the header.
  let header = -1
  for (let index = lines.length - 1; index >= 0; index--) {
    if (HEADER_RE.test(lines[index]) && (index === 0 || lines[index - 1].trim() === '')) {
      header = index
      break
    }
  }
  if (header === -1) return fallback

  const attachments: AttachmentRef[] = []
  let cursor = header + 1

  while (cursor < lines.length) {
    const entry = ENTRY_RE.exec(lines[cursor])
    if (!entry) break
    const path = PATH_RE.exec(lines[cursor + 1] ?? '')
    if (!path) break

    const detail = entry[3]
    attachments.push({
      id: attachmentIdFromPath(path[1]),
      name: entry[2],
      detail,
      path: path[1],
      image: detail.startsWith('image/')
    })
    cursor += 2
  }

  if (attachments.length === 0) return fallback

  return {
    text: lines.slice(0, header).join('\n').trim(),
    attachments,
    context: lines.slice(cursor).join('\n').trim(),
    recognised: true
  }
}

export function attachmentRawUrl(id: string): string {
  return `/api/attachments/${encodeURIComponent(id)}/raw`
}

/** Bytes, as a person would say them. Mirrors `human_size` in app/server/attachments.py. */
export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  let value = size
  for (const unit of ['KB', 'MB', 'GB']) {
    value /= 1024
    if (value < 1024 || unit === 'GB') {
      return value >= 100 ? `${value.toFixed(0)} ${unit}` : `${value.toFixed(1)} ${unit}`
    }
  }
  return `${size} B`
}

/** The icon a kind gets, kept here so the chip and the turn agree on one answer. */
export function kindLabel(kind: AttachmentKind): string {
  switch (kind) {
    case 'image':
      return 'Image'
    case 'document':
      return 'Document'
    case 'text':
      return 'Text'
    case 'archive':
      return 'Archive'
    case 'folder':
      return 'Folder'
    case 'url':
      return 'Page'
    default:
      return 'File'
  }
}
