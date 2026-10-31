import { describe, expect, it } from 'vitest'
import { attachmentTarget, fileTarget, siteTarget, targetKey } from './preview'
import {
  EMPTY_PREVIEW_STACK,
  MAX_OPEN_PREVIEWS,
  closePreview,
  currentTarget,
  dismissPreview,
  openPreview,
  showPreview,
  togglePreview
} from './preview-stack'

const beans = fileTarget('/home/you/out/beans.csv')
const scan = attachmentTarget({
  id: 'abc123def456',
  path: '/home/you/.pantler/attachments/abc123def456/soil-report.pdf',
  name: 'soil-report.pdf'
})
// `siteTarget` answers `null` for anything that is not an http(s) address; this one is, and the
// gate itself has its own test in `preview.test.ts` (the internal security audit A19-WEB-3).
const prices = siteTarget('https://example.com/prices')!

describe('the preview sidebar stack', () => {
  it('opens a file: on show, and the pane with it', () => {
    const opened = openPreview(EMPTY_PREVIEW_STACK, beans)
    expect(opened.open).toBe(true)
    expect(currentTarget(opened)).toEqual(beans)
    expect(opened.current).toBe('file:/home/you/out/beans.csv')
  })

  it('keeps what was open, with the newest in front', () => {
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), prices)
    expect(currentTarget(stack)).toEqual(prices)
    expect(stack.items).toEqual([prices, beans])
  })

  it('moves a file that is opened again rather than listing it twice', () => {
    const stack = openPreview(openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), scan), beans)
    expect(stack.items).toEqual([beans, scan])
  })

  it('treats an attachment and a file as two things, even at one path', () => {
    // The key is what says which door the bytes come through: the same name is not the same file.
    const asFile = fileTarget(scan.path)
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, asFile), scan)
    expect(stack.items).toHaveLength(2)
  })

  it('switches to one that is already open, and ignores one that is not', () => {
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), scan)
    expect(currentTarget(showPreview(stack, beans))).toEqual(beans)
    expect(showPreview(stack, prices)).toBe(stack)
  })

  it('hands the pane to the next file when the one on show is dismissed', () => {
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), scan)
    const after = dismissPreview(stack, scan)
    expect(after.open).toBe(true)
    expect(currentTarget(after)).toEqual(beans)
  })

  it('leaves the front alone when a file behind it is dismissed', () => {
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), scan)
    const after = dismissPreview(stack, beans)
    expect(currentTarget(after)).toEqual(scan)
    expect(after.items).toEqual([scan])
  })

  it('goes away when the last file is dismissed', () => {
    const after = dismissPreview(openPreview(EMPTY_PREVIEW_STACK, beans), beans)
    expect(after).toEqual(EMPTY_PREVIEW_STACK)
    expect(currentTarget(after)).toBeNull()
  })

  it('hides without forgetting, so the tab reopens what was being read', () => {
    const stack = openPreview(openPreview(EMPTY_PREVIEW_STACK, beans), scan)
    const hidden = closePreview(stack)
    expect(hidden.open).toBe(false)
    expect(currentTarget(hidden)).toEqual(scan)
    expect(togglePreview(hidden).open).toBe(true)
    // Closing what is already closed is not a change: there is nothing to animate or re-fetch.
    expect(closePreview(hidden)).toBe(hidden)
  })

  it('opens empty when the pane is asked for with nothing in it', () => {
    const revealed = togglePreview(EMPTY_PREVIEW_STACK)
    expect(revealed.open).toBe(true)
    expect(currentTarget(revealed)).toBeNull()
  })

  it('caps the strip at the newest few, and never drops the one on show', () => {
    let stack = EMPTY_PREVIEW_STACK
    const files = Array.from({ length: MAX_OPEN_PREVIEWS + 3 }, (_, index) =>
      fileTarget(`/home/you/out/file-${index}.csv`)
    )
    for (const file of files) stack = openPreview(stack, file)
    expect(stack.items).toHaveLength(MAX_OPEN_PREVIEWS)
    expect(currentTarget(stack)).toEqual(files[files.length - 1])
    expect(stack.items.some(item => targetKey(item) === 'file:/home/you/out/file-0.csv')).toBe(
      false
    )
  })
})
