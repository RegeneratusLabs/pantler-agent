/**
 * What the preview sidebar has open, and which of them is on show.
 *
 * The preview is not a modal any more: it is a column beside the conversation and it stays put
 * while the talking carries on (the file-preview design §4 D3). That means it has to remember more
 * than "the thing being looked at" — the documents opened in this conversation, in the order they
 * were opened, and which one is in front.
 *
 * That is state with rules: re-opening a file *moves* it rather than listing it twice, dismissing
 * the one on show hands the pane to the next, the last one dismissed closes the pane, and there is
 * a ceiling on how many a conversation may hold. Rules that live in a component are rules that are
 * only ever tested by clicking, so they live here instead — pure, and asserted in
 * `preview-stack.test.ts`, the same way the reducer and `preview.ts` are.
 */

import { targetKey, type PreviewTarget } from './preview'

/**
 * How many documents one conversation may keep open.
 *
 * A sidebar is not a history. Past this the oldest is dropped, which is the same thing every tab
 * strip does and the only rule that keeps a long conversation's memory from growing with it.
 */
export const MAX_OPEN_PREVIEWS = 8

export interface PreviewStack {
  /** Everything opened here, most recently opened first. */
  items: PreviewTarget[]
  /** The key of the one on show. Always one of `items`, or null when there is nothing to show. */
  current: string | null
  /** Whether the pane itself is on screen. Independent of `current`: it can be open and empty. */
  open: boolean
}

export const EMPTY_PREVIEW_STACK: PreviewStack = { items: [], current: null, open: false }

/**
 * Open a target: show it, and put it at the front of the strip.
 *
 * A target already in the strip is moved rather than added, because the identity of a file is its
 * key — the same document reached from a chip and from a card is one document, and two entries
 * pointing at one file would be a lie about how much is open.
 */
export function openPreview(stack: PreviewStack, target: PreviewTarget): PreviewStack {
  const key = targetKey(target)
  const items = [target, ...stack.items.filter(item => targetKey(item) !== key)]
  return { items: items.slice(0, MAX_OPEN_PREVIEWS), current: key, open: true }
}

/**
 * Show one that is already open.
 *
 * A target this stack has never seen is ignored rather than added: the strip is the list of what
 * is open, and a click on it cannot be the thing that opens something new.
 */
export function showPreview(stack: PreviewStack, target: PreviewTarget): PreviewStack {
  const key = targetKey(target)
  if (!stack.items.some(item => targetKey(item) === key)) return stack
  return { ...stack, current: key, open: true }
}

/**
 * Close one document.
 *
 * The pane outlives the document: with others open it hands the front to the most recent of them,
 * and with none left it goes away, because a pane with nothing in it is only ever in the way.
 */
export function dismissPreview(stack: PreviewStack, target: PreviewTarget): PreviewStack {
  const key = targetKey(target)
  const items = stack.items.filter(item => targetKey(item) !== key)
  if (items.length === stack.items.length) return stack
  if (items.length === 0) return EMPTY_PREVIEW_STACK
  if (stack.current !== key) return { ...stack, items }
  return { ...stack, items, current: targetKey(items[0]) }
}

/**
 * Hide the pane, and keep what was in it.
 *
 * The tab on the edge of the conversation is how it comes back, and what it comes back to should
 * be the document the operator was reading — not an empty pane they have to find it again in.
 */
export function closePreview(stack: PreviewStack): PreviewStack {
  return stack.open ? { ...stack, open: false } : stack
}

/** The tab: what was there comes back, an empty pane included. */
export function togglePreview(stack: PreviewStack): PreviewStack {
  return { ...stack, open: !stack.open }
}

/** The target on show, or null — never a stale key pointing at something dismissed. */
export function currentTarget(stack: PreviewStack): PreviewTarget | null {
  if (!stack.current) return null
  return stack.items.find(item => targetKey(item) === stack.current) ?? null
}
