/**
 * Making a URL in a sentence clickable — and nothing else.
 *
 * the front-end design §4 says the assistant's answer has no authority; the record is the
 * tool card underneath. The answer is rendered markdown now (`Markdown.tsx`), but plain prose
 * still needs a door for a URL: `Prose.tsx` uses this for the operator's own message and the
 * interim status line, and `markdown.ts` uses it for a bare URL inside a rendered answer.
 *
 * This module is deliberately *not* a markdown renderer. No headings, no lists, no emphasis, no
 * tables: the paragraph keeps its shape (`whitespace-pre-wrap`) and only gains anchors. A path in
 * a sentence is still a path — a file is previewed from a structured place instead (the
 * attachment block, a tool call's arguments, a tool result's own field), because guessing which
 * words on screen are a path is how a renderer ends up turning prose into broken image icons.
 *
 * The regex is strict on purpose: a scheme, a host, and no whitespace. Trailing sentence
 * punctuation is trimmed, but a closing bracket is kept when it balances one inside the URL —
 * `https://en.wikipedia.org/wiki/Foo_(bar)` is a real address and `(see https://x.dev)` is a
 * real sentence, and both have to come out right.
 */

export type Segment =
  | { kind: 'text'; text: string }
  | { kind: 'url'; url: string; text: string }

const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/gi

/** Punctuation that ends a sentence rather than a URL. A bracket is handled separately. */
const TRAILING_PUNCTUATION = /[.,;:!?…]+$/

export function linkify(text: string): Segment[] {
  if (!text) return []

  const segments: Segment[] = []
  let cursor = 0
  URL_RE.lastIndex = 0

  for (let match = URL_RE.exec(text); match !== null; match = URL_RE.exec(text)) {
    const trimmed = trimUrl(match[0])
    if (!trimmed) continue
    if (match.index > cursor) {
      segments.push({ kind: 'text', text: text.slice(cursor, match.index) })
    }
    segments.push({ kind: 'url', url: trimmed, text: trimmed })
    // Anything the trim gave back is text, not part of the link.
    cursor = match.index + trimmed.length
    URL_RE.lastIndex = cursor
  }

  if (cursor < text.length) segments.push({ kind: 'text', text: text.slice(cursor) })
  return segments
}

/** True when a string is nothing but one URL — the case that is a link, not a sentence. */

/**
 * The URL without the sentence that followed it.
 *
 * Trailing `. , ; : ! ?` is always dropped. A closing bracket is dropped only when it closes
 * nothing — counting the openers and closers inside the match is what tells the two cases apart.
 */
export function trimUrl(raw: string): string {
  let url = raw.replace(TRAILING_PUNCTUATION, '')

  for (const [open, close] of [
    ['(', ')'],
    ['[', ']'],
    ['{', '}']
  ] as const) {
    while (url.endsWith(close) && count(url, close) > count(url, open)) {
      url = url.slice(0, -1)
    }
  }

  // A URL that is now empty, or that lost its host, is not a URL.
  return /^https?:\/\/\S+$/i.test(url) ? url : ''
}

function count(text: string, character: string): number {
  let total = 0
  for (const value of text) if (value === character) total += 1
  return total
}
