/**
 * Markdown, parsed into a tree — the one place a `.md` file or an assistant answer stops being
 * source.
 *
 * The same parser serves two surfaces. the file-preview design D4 refuses an HTML file as a page
 * and shows its source, so a `.md` file the operator opened is a document to read, not source to
 * display. The assistant's answer is the other surface: the chat renders it as markdown rather
 * than showing `**bold**` as asterisks (the front-end design §4). Neither changes the
 * authority rule — the tool card underneath is still the record. Both obey the three rules this
 * module owns:
 *
 *   1. **No HTML, ever.** The output is a tree of typed nodes and `Markdown.tsx` draws React
 *      elements from it. There is no `dangerouslySetInnerHTML` anywhere in this path, and a raw
 *      HTML block is shown as literal text — which is also exactly what a `.md` file full of
 *      HTML deserves (`previews.py` says as much about text files).
 *   2. **A link is never guessed into an action.** Only an absolute `http(s)` address becomes a
 *      link that opens; `mailto:` is a mail link; a relative path and a `#anchor` stay words,
 *      because the transcript and the pane have no working directory (D8 refuses relative paths
 *      for the same reason); a `javascript:` address is not a link at all.
 *   3. **Nothing is fetched to render.** `![chart](https://…)` is drawn as its alt text with a
 *      link beside it rather than as an `<img>`: neither a preview nor a chat answer is allowed
 *      to report reading something from the network that the operator did not ask it to open.
 *
 * The subset is what a README or a model reply actually uses — ATX headings, paragraphs, both
 * list kinds with nesting, blockquotes, fenced code, tables, thematic breaks, and inline bold ·
 * italic · strikethrough · code · links — and the edges are honest: setext headings (`Title`
 * over `===`) and four-space indented code blocks are **not** supported, and stay visible as the
 * text they are rather than silently vanishing. Emphasis, links and code are the cases the
 * operator asked for by name (a `**bold**` in a delivered file has to be bold), so they are the
 * cases with the most tests (`markdown.test.ts`).
 *
 * It is pure and it is tested for the same reason `links.ts` and `preview.ts` are: a renderer
 * that is only exercised by opening a file or reading a chat in a browser is a renderer nobody
 * can check.
 */

import { linkify } from './links'

// ------------------------------------------------------------------------ types

export type Align = 'left' | 'center' | 'right'

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; children: Inline[] }
  | { kind: 'em'; children: Inline[] }
  | { kind: 'del'; children: Inline[] }
  | { kind: 'code'; text: string }
  | { kind: 'link'; href: string; children: Inline[] }
  /** A bare URL in the text. `links.ts` found it; the renderer gives it the pane's own door. */
  | { kind: 'url'; url: string }
  | { kind: 'image'; href: string; alt: string }
  | { kind: 'break' }

export type Block =
  | { kind: 'heading'; level: number; children: Inline[] }
  | { kind: 'paragraph'; children: Inline[] }
  | { kind: 'list'; ordered: boolean; start: number; items: Block[][] }
  | { kind: 'quote'; children: Block[] }
  | { kind: 'code'; language: string; text: string }
  | { kind: 'rule' }
  | { kind: 'table'; align: (Align | null)[]; head: Inline[][]; rows: Inline[][][] }
  /** A raw HTML block: shown as the text it is, never parsed and never injected. */
  | { kind: 'html'; text: string }

/**
 * How a link's address may be treated. Only `site` opens the preview pane, and only `site` and
 * `mail` ever become an `href`; everything else is text. Exported because it is the security
 * decision, and it has its own test rather than living in a comment.
 */
export type LinkKind = 'site' | 'mail' | 'plain'

/** The longest run of nesting the inline parser will follow before it stops looking. */
const MAX_INLINE_DEPTH = 8

// --------------------------------------------------------------------- patterns

const FENCE_RE = /^ {0,3}(`{3,}|~{3,})\s*(.*)$/
const ATX_RE = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const ATX_BARE_RE = /^ {0,3}(#{1,6})\s*$/
const RULE_RE = /^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/
const BULLET_RE = /^([ \t]*)([-*+])(?:[ \t]+(.*))?$/
const ORDERED_RE = /^([ \t]*)(\d{1,9})([.)])(?:[ \t]+(.*))?$/
const QUOTE_RE = /^ {0,3}>[ \t]?(.*)$/
const TABLE_ROW_RE = /^ {0,3}\|?(.*?)\|?[ \t]*$/
const TABLE_DELIM_RE = /^ {0,3}\|?[ \t]*:?-{1,}:?[ \t]*(\|[ \t]*:?-{1,}:?[ \t]*)*\|?[ \t]*$/
const HTML_BLOCK_RE = /^ {0,3}<(!--|\/?[A-Za-z][A-Za-z0-9-]*)(\s|\/?>|$)/
const LANGUAGE_RE = /^[A-Za-z0-9+#._-]{1,24}$/

// ------------------------------------------------------------------ link kinds

/**
 * What an address is allowed to become. The refusal is the point: `javascript:` (and `data:`,
 * `vbscript:`, `file:` and a protocol-relative `//host`) are `plain`, which the renderer draws
 * as the words they are. Case and surrounding whitespace are not a way around it.
 */
export function linkKind(href: string): LinkKind {
  const value = (href ?? '').trim()
  if (/^https?:\/\/[^\s]+$/i.test(value)) return 'site'
  if (/^mailto:[^\s@]+@[^\s@]+$/i.test(value)) return 'mail'
  return 'plain'
}

// ------------------------------------------------------------------------ blocks

/** Parse a whole markdown document. Empty input is an empty document, not an error. */
export function parseMarkdown(source: string): Block[] {
  const lines = (source ?? '').replace(/\r\n?/g, '\n').split('\n')
  return parseBlocks(lines, { from: 0, to: lines.length })
}

interface Span {
  from: number
  to: number
}

function parseBlocks(lines: string[], span: Span): Block[] {
  const blocks: Block[] = []
  let i = span.from

  while (i < span.to) {
    const line = lines[i]

    if (!line.trim()) {
      i += 1
      continue
    }

    const fence = FENCE_RE.exec(line)
    if (fence) {
      const code = readFence(lines, i, span.to, fence[1][0])
      blocks.push(code.block)
      i = code.next
      continue
    }

    const heading = ATX_RE.exec(line) ?? ATX_BARE_RE.exec(line)
    if (heading) {
      blocks.push({
        kind: 'heading',
        level: heading[1].length,
        children: parseInline((heading[2] ?? '').trim())
      })
      i += 1
      continue
    }

    if (RULE_RE.test(line)) {
      blocks.push({ kind: 'rule' })
      i += 1
      continue
    }

    if (QUOTE_RE.test(line)) {
      const inner: string[] = []
      let j = i
      while (j < span.to) {
        const match = QUOTE_RE.exec(lines[j])
        if (!match) break
        inner.push(match[1])
        j += 1
      }
      blocks.push({ kind: 'quote', children: parseBlocks(inner, { from: 0, to: inner.length }) })
      i = j
      continue
    }

    if (isListItem(line)) {
      const list = readList(lines, i, span.to)
      blocks.push(list.block)
      i = list.next
      continue
    }

    if (line.includes('|') && i + 1 < span.to && TABLE_DELIM_RE.test(lines[i + 1])) {
      const table = readTable(lines, i, span.to)
      if (table) {
        blocks.push(table.block)
        i = table.next
        continue
      }
    }

    if (HTML_BLOCK_RE.test(line)) {
      const raw: string[] = []
      let j = i
      while (j < span.to && lines[j].trim()) {
        raw.push(lines[j])
        j += 1
      }
      blocks.push({ kind: 'html', text: raw.join('\n') })
      i = j
      continue
    }

    const paragraph: string[] = []
    let j = i
    while (j < span.to && lines[j].trim() && !startsBlock(lines, j, span.to)) {
      // The leading indent goes; trailing spaces stay, because that is markdown's hard break.
      paragraph.push(lines[j].replace(/^[ \t]+/, ''))
      j += 1
    }
    // `startsBlock` refuses to open a paragraph, so this is only reachable for a single line.
    if (j === i) {
      paragraph.push(lines[i].trim())
      j = i + 1
    }
    blocks.push({
      kind: 'paragraph',
      children: parseInline(paragraph.join('\n').replace(/[ \t]+$/, ''))
    })
    i = j
  }

  return blocks
}

/** Whether the line at `index` opens a block, which is what ends the paragraph above it. */
function startsBlock(lines: string[], index: number, to: number): boolean {
  const line = lines[index]
  if (FENCE_RE.test(line)) return true
  if (ATX_RE.test(line) || ATX_BARE_RE.test(line)) return true
  if (RULE_RE.test(line)) return true
  if (QUOTE_RE.test(line)) return true
  if (isListItem(line)) return true
  if (HTML_BLOCK_RE.test(line)) return true
  if (line.includes('|') && index + 1 < to && TABLE_DELIM_RE.test(lines[index + 1])) return true
  return false
}

function isListItem(line: string): boolean {
  return BULLET_RE.test(line) || ORDERED_RE.test(line)
}

/** A fenced code block, to its closing fence or to the end of the document. */
function readFence(
  lines: string[],
  start: number,
  to: number,
  marker: string
): { block: Block; next: number } {
  const info = FENCE_RE.exec(lines[start])?.[2]?.trim() ?? ''
  const language = LANGUAGE_RE.test(info.split(/\s+/)[0] ?? '') ? (info.split(/\s+/)[0] ?? '') : ''
  const body: string[] = []
  let i = start + 1
  while (i < to) {
    const closing = FENCE_RE.exec(lines[i])
    if (closing && closing[1][0] === marker && !closing[2].trim()) break
    body.push(lines[i])
    i += 1
  }
  return {
    block: { kind: 'code', language, text: body.join('\n') },
    next: i < to ? i + 1 : to
  }
}

/**
 * A list, from its first item to the first line that is not part of it.
 *
 * Nesting is by indentation: a deeper item joins the list already open inside the current item.
 * A blank line inside an item keeps it open (a loose list is still one list) but a blank line
 * followed by a non-indented line ends it.
 */
function readList(lines: string[], start: number, to: number): { block: Block; next: number } {
  const first = itemMatch(lines[start])
  const ordered = first?.ordered ?? false
  const markerIndent = first?.indent ?? 0
  const start0 = first?.number ?? 1
  const items: Block[][] = []
  let i = start

  while (i < to) {
    const match = itemMatch(lines[i])
    if (match && match.indent <= markerIndent && match.ordered === ordered) {
      // A new sibling item: gather its own lines, dedented to the item's content column.
      const content: string[] = [match.text]
      let j = i + 1
      while (j < to) {
        const line = lines[j]
        if (!line.trim()) {
          // Keep a blank line only if the list continues after it.
          let k = j + 1
          while (k < to && !lines[k].trim()) k += 1
          if (k < to && continuation(lines[k], match)) {
            content.push('')
            j += 1
            continue
          }
          break
        }
        if (!continuation(line, match)) break
        content.push(dedent(line, match.indent + 2))
        j += 1
      }
      items.push(parseBlocks(content, { from: 0, to: content.length }))
      i = j
      continue
    }
    if (!match && !lines[i].trim()) {
      // A blank line between items of a loose list.
      const next = lines[i + 1]
      if (next !== undefined && itemMatch(next)?.indent === markerIndent) {
        i += 1
        continue
      }
    }
    break
  }

  if (items.length === 0) {
    return {
      block: { kind: 'paragraph', children: parseInline(lines[start].trim()) },
      next: start + 1
    }
  }

  return { block: { kind: 'list', ordered, start: start0, items }, next: i }
}

interface ItemMatch {
  indent: number
  ordered: boolean
  number: number
  text: string
}

function itemMatch(line: string): ItemMatch | null {
  const ordered = ORDERED_RE.exec(line)
  if (ordered) {
    return {
      indent: indentWidth(ordered[1]),
      ordered: true,
      number: Number.parseInt(ordered[2], 10) || 1,
      text: ordered[4] ?? ''
    }
  }
  const bullet = BULLET_RE.exec(line)
  if (bullet) {
    return { indent: indentWidth(bullet[1]), ordered: false, number: 1, text: bullet[3] ?? '' }
  }
  return null
}

/** Whether a line belongs to the item whose content starts at `item.indent + 2`. */
function continuation(line: string, item: ItemMatch): boolean {
  if (/^[ \t]*$/.test(line)) return false
  const nested = itemMatch(line)
  // A deeper item is this item's own nested list; a sibling's is not.
  if (nested) return nested.indent > item.indent
  if (indentWidth(/^[ \t]*/.exec(line)?.[0] ?? '') > item.indent) return true
  // A lazy continuation: a plain line under an item without indentation is still its text.
  return !startsBlock([line], 0, 1)
}

function dedent(line: string, width: number): string {
  let removed = 0
  let index = 0
  while (index < line.length && removed < width) {
    if (line[index] === ' ') {
      removed += 1
      index += 1
    } else if (line[index] === '\t') {
      removed += 4
      index += 1
    } else break
  }
  return line.slice(index)
}

function indentWidth(prefix: string): number {
  let width = 0
  for (const char of prefix) width += char === '\t' ? 4 : 1
  return width
}

/** A pipe table, when the line under the header is a delimiter row. */
function readTable(lines: string[], start: number, to: number): { block: Block; next: number } | null {
  const head = splitRow(lines[start])
  const delimiter = splitRow(lines[start + 1])
  if (!head || !delimiter || head.length !== delimiter.length) return null

  const align = delimiter.map(cell => {
    const trimmed = cell.trim()
    const left = trimmed.startsWith(':')
    const right = trimmed.endsWith(':')
    if (left && right) return 'center' as const
    if (right) return 'right' as const
    if (left) return 'left' as const
    return null
  })

  const rows: Inline[][][] = []
  let i = start + 2
  while (i < to && lines[i].trim() && lines[i].includes('|')) {
    const cells = splitRow(lines[i])
    if (!cells) break
    // A short row is padded and a long one is kept: silently dropping a cell would be a lie
    // about the document, and a table that does not line up is the document's own choice.
    const row = head.map((_, index) => parseInline((cells[index] ?? '').trim()))
    rows.push(row)
    i += 1
  }

  return {
    block: { kind: 'table', align, head: head.map(cell => parseInline(cell.trim())), rows },
    next: i
  }
}

/** Split a table row on unescaped pipes, dropping the optional outer ones. */
function splitRow(line: string): string[] | null {
  const match = TABLE_ROW_RE.exec(line)
  if (!match) return null
  const body = match[1]
  if (body === undefined) return null
  const cells: string[] = []
  let current = ''
  for (let i = 0; i < body.length; i++) {
    const char = body[i]
    if (char === '\\' && body[i + 1] === '|') {
      current += '|'
      i += 1
      continue
    }
    if (char === '|') {
      cells.push(current)
      current = ''
      continue
    }
    current += char
  }
  cells.push(current)
  return cells
}

// ------------------------------------------------------------------------ inline

/** Parse the inline text of a block. Exported because the tests walk it directly. */
export function parseInline(text: string, depth = 0): Inline[] {
  const nodes: Inline[] = []
  let plain = ''
  let i = 0

  const flush = () => {
    if (!plain) return
    // A bare URL in a document is a URL like one in prose, and it gets the same door
    // (`links.ts` is the one place that decides what a URL is).
    for (const segment of linkify(plain)) {
      nodes.push(
        segment.kind === 'url'
          ? { kind: 'url', url: segment.url }
          : { kind: 'text', text: segment.text }
      )
    }
    plain = ''
  }

  while (i < text.length) {
    const char = text[i]

    if (char === '\\' && i + 1 < text.length && isEscapable(text[i + 1])) {
      plain += text[i + 1]
      i += 2
      continue
    }

    // Two trailing spaces before a newline are markdown's hard break.
    if (char === '\n' && /[ \t]{2,}$/.test(plain)) {
      plain = plain.replace(/[ \t]+$/, '')
      flush()
      nodes.push({ kind: 'break' })
      i += 1
      continue
    }

    if (char === '`' && depth < MAX_INLINE_DEPTH) {
      const span = matchCode(text, i)
      if (span) {
        flush()
        nodes.push({ kind: 'code', text: span.text })
        i = span.end
        continue
      }
    }

    // An autolink: `<https://…>` is the address and nothing else.
    if (char === '<' && depth < MAX_INLINE_DEPTH) {
      const autolink = /^<(https?:\/\/[^\s<>]+)>/.exec(text.slice(i))
      if (autolink) {
        flush()
        nodes.push({ kind: 'url', url: autolink[1] })
        i += autolink[0].length
        continue
      }
    }

    if (char === '!' && text[i + 1] === '[' && depth < MAX_INLINE_DEPTH) {
      const link = matchLink(text, i + 1)
      if (link) {
        flush()
        nodes.push({ kind: 'image', href: link.href, alt: plainText(parseInline(link.label, depth + 1)) })
        i = link.end
        continue
      }
    }

    if (char === '[' && depth < MAX_INLINE_DEPTH) {
      const link = matchLink(text, i)
      if (link) {
        flush()
        nodes.push({ kind: 'link', href: link.href, children: parseInline(link.label, depth + 1) })
        i = link.end
        continue
      }
    }

    if ((char === '*' || char === '_') && depth < MAX_INLINE_DEPTH) {
      const emph = matchEmphasis(text, i, char)
      if (emph) {
        flush()
        const children = parseInline(emph.text, depth + 1)
        nodes.push(emph.wrap === 'strong' ? { kind: 'strong', children } : { kind: 'em', children })
        if (emph.wrap === 'both') {
          const inner = nodes.pop() as Inline
          nodes.push({ kind: 'strong', children: [inner] })
        }
        i = emph.end
        continue
      }
    }

    if (char === '~' && text[i + 1] === '~' && depth < MAX_INLINE_DEPTH) {
      const end = text.indexOf('~~', i + 2)
      if (end > i + 2) {
        flush()
        nodes.push({ kind: 'del', children: parseInline(text.slice(i + 2, end), depth + 1) })
        i = end + 2
        continue
      }
    }

    plain += char
    i += 1
  }

  flush()
  return nodes
}

function isEscapable(char: string): boolean {
  return '\\`*_{}[]()#+-.!~>|'.includes(char)
}

/** A code span: one or more backticks, closed by the same run. */
function matchCode(text: string, start: number): { text: string; end: number } | null {
  let run = 0
  while (text[start + run] === '`') run += 1
  const token = '`'.repeat(run)
  const end = text.indexOf(token, start + run)
  if (end === -1) return null
  const inner = text.slice(start + run, end)
  // A span's own leading and trailing space is stripped: `` ` `` around a backtick.
  return { text: inner.replace(/^ ([\s\S]*) $/, '$1'), end: end + run }
}

/** `[label](href "title")`, with a label that may contain nested brackets. */
function matchLink(
  text: string,
  start: number
): { label: string; href: string; end: number } | null {
  if (text[start] !== '[') return null
  let depth = 0
  let close = -1
  for (let i = start; i < text.length; i++) {
    const char = text[i]
    if (char === '\\') {
      i += 1
      continue
    }
    if (char === '[') depth += 1
    else if (char === ']') {
      depth -= 1
      if (depth === 0) {
        close = i
        break
      }
    }
  }
  if (close === -1 || text[close + 1] !== '(') return null

  let parens = 1
  let end = -1
  for (let i = close + 2; i < text.length; i++) {
    const char = text[i]
    if (char === '\\') {
      i += 1
      continue
    }
    if (char === '(') parens += 1
    else if (char === ')') {
      parens -= 1
      if (parens === 0) {
        end = i
        break
      }
    }
  }
  if (end === -1) return null

  const destination = text.slice(close + 2, end).trim()
  // The href is the first whitespace-delimited word; a `"title"` after it is dropped, and an
  // angle-bracketed address keeps its spaces.
  const angled = /^<([^>]*)>/.exec(destination)
  const href = (angled ? angled[1] : destination.split(/\s+/)[0] ?? '').trim()
  if (!href) return null

  return { label: text.slice(start + 1, close), href, end: end + 1 }
}

/** `*one*`, `**two**`, `***three***`, with `_` refusing to break a word in half. */
function matchEmphasis(
  text: string,
  start: number,
  marker: string
): { text: string; end: number; wrap: 'em' | 'strong' | 'both' } | null {
  let run = 1
  if (text[start + 1] === marker) run = 2
  if (run === 2 && text[start + 2] === marker) run = 3
  const token = marker.repeat(run)

  if (marker === '_' && start > 0 && isWord(text[start - 1])) return null
  // A delimiter cannot open onto, or close after, whitespace — which is what makes `** **`
  // spaces rather than emphasis, and what stops a stray asterisk in a sentence from italicising
  // the rest of the paragraph.
  const opens = text[start + run]
  if (opens === undefined || /\s/.test(opens)) return null

  let from = start + run
  while (from < text.length) {
    const close = text.indexOf(token, from)
    if (close === -1) return null
    const after = text[close + token.length] ?? ''
    const before = text[close - 1] ?? ''
    if (/\s/.test(before)) {
      from = close + 1
      continue
    }
    // A single `*` does not close against half of a longer run, which is what lets
    // `*an **important** word*` be an italic phrase with a bold word inside it rather than an
    // emphasis that ends at the first asterisk of the inner pair.
    if (run === 1 && (text[close + 1] === marker || text[close - 1] === marker)) {
      from = close + 1
      continue
    }
    if (marker === '_' && isWord(after)) {
      from = close + 1
      continue
    }
    const inner = text.slice(start + run, close)
    if (!inner.trim()) {
      from = close + 1
      continue
    }
    return {
      text: inner,
      end: close + token.length,
      wrap: run === 3 ? 'both' : run === 2 ? 'strong' : 'em'
    }
  }
  return null
}

function isWord(char: string | undefined): boolean {
  return char !== undefined && /[\p{L}\p{N}]/u.test(char)
}

/** The words in a node tree, for an image's alt text and for a test's assertions. */
export function plainText(nodes: Inline[]): string {
  return nodes
    .map(node => {
      switch (node.kind) {
        case 'text':
          return node.text
        case 'code':
          return node.text
        case 'url':
          return node.url
        case 'image':
          return node.alt
        case 'break':
          return ' '
        default:
          return plainText(node.children)
      }
    })
    .join('')
}

/**
 * The readable text of a markdown message — what a copy button should put on the clipboard.
 *
 * The chat renders markdown, so copying the source would paste `**bold**` and table pipes into an
 * email or a social post. This flattens the same parse tree to the words a reader sees: headings
 * and paragraphs as lines, list items with their marker, quoted lines with `>`, tables as rows,
 * code as its code, and links/images with their address when that adds information. It is not a
 * second renderer — `Markdown.tsx` still decides how the document looks; this only decides what
 * the text says.
 */
export function markdownToText(source: string): string {
  return blocksToText(parseMarkdown(source)).trim()
}

function blocksToText(blocks: Block[]): string {
  return blocks
    .map(blockToText)
    .filter(text => text.trim().length > 0)
    .join('\n\n')
}

function blockToText(block: Block): string {
  switch (block.kind) {
    case 'heading':
    case 'paragraph':
      return inlineToText(block.children)

    case 'list':
      return block.items
        .map((item, index) => {
          const marker = block.ordered ? `${block.start + index}. ` : '- '
          return blocksToText(item)
            .split('\n')
            .map((line, lineIndex) => (lineIndex === 0 ? `${marker}${line}` : `  ${line}`))
            .join('\n')
        })
        .join('\n')

    case 'quote':
      return blocksToText(block.children)
        .split('\n')
        .map(line => `> ${line}`)
        .join('\n')

    case 'code':
      return block.text.replace(/\s+$/, '')

    case 'rule':
      return '---'

    case 'table':
      return [block.head, ...block.rows]
        .map(row => row.map(cell => inlineToText(cell)).join(' | '))
        .join('\n')

    case 'html':
      return block.text
  }
}

function inlineToText(nodes: Inline[]): string {
  return nodes
    .map(node => {
      switch (node.kind) {
        case 'text':
          return node.text
        case 'break':
          return '\n'
        case 'code':
          return node.text
        case 'strong':
        case 'em':
        case 'del':
          return inlineToText(node.children)
        case 'url':
          return node.url
        case 'link': {
          const label = inlineToText(node.children)
          if (!label) return node.href
          return node.href && !label.includes(node.href) ? `${label} (${node.href})` : label
        }
        case 'image': {
          const alt = node.alt.trim()
          if (!alt) return node.href
          return node.href && !alt.includes(node.href) ? `${alt} (${node.href})` : alt
        }
      }
    })
    .join('')
}
