/**
 * The attachment turn format.
 *
 * The important test here is the golden one: the text below was captured verbatim from
 * `compose_input` in `app/server/attachments.py`. The BFF writes that format and this side
 * reads it, in two languages, with no shared type to keep them honest — so a change on
 * either side has to fail a test, and this is the one that fails.
 */

import { describe, expect, it } from 'vitest'
import { formatBytes, kindLabel, parseTurn } from '@shared/attachments'
import { draftKind, folderNameFromPaths, largePasteName, pastedName } from './attachments'

/** Captured from app/server/attachments.py::compose_input — do not hand-edit. */
const GOLDEN = [
  'Invoice these for me',
  '',
  'Attached files (3):',
  '1. bean-order.csv — text/csv, 25 B',
  '   Path: /home/you/projects/pantler/.data/attachments/web-golden/ff05e68a8a33/bean-order.csv',
  '2. barn.png — image/png, 8 B',
  '   Path: /home/you/projects/pantler/.data/attachments/web-golden/7d8f9bae1ca5/barn.png',
  '3. orders-2024 — folder, 1 file, 2 B',
  '   Path: /home/you/projects/pantler/.data/attachments/web-golden/1bb2d753561a/orders-2024',
  'Read a document with read_file; look at an image with vision_analyze.',
  '',
  '--- bean-order.csv ---',
  'customer,qty',
  'Bellview,12',
  '--- end bean-order.csv ---'
].join('\n')

describe('parseTurn', () => {
  it('reads the turn the BFF actually writes', () => {
    const parsed = parseTurn(GOLDEN)
    expect(parsed.recognised).toBe(true)
    expect(parsed.text).toBe('Invoice these for me')
    expect(parsed.attachments).toHaveLength(3)
    expect(parsed.attachments[0]).toEqual({
      id: 'ff05e68a8a33',
      name: 'bean-order.csv',
      detail: 'text/csv, 25 B',
      path: '/home/you/projects/pantler/.data/attachments/web-golden/ff05e68a8a33/bean-order.csv',
      image: false
    })
    expect(parsed.attachments[1].image).toBe(true)
    expect(parsed.attachments[1].id).toBe('7d8f9bae1ca5')
    expect(parsed.attachments[2].detail).toBe('folder, 1 file, 2 B')
    // The inlined content is kept, not swallowed: the transcript can still show what the
    // assistant was given.
    expect(parsed.context).toContain('Read a document with read_file')
    expect(parsed.context).toContain('Bellview,12')
  })

  it('takes the store id, not the first twelve hex characters in the path', () => {
    // A session directory named `abcdef123456` used to be reported as the attachment id, so the
    // thumbnail URL pointed at the session directory and 404'd
    // (the internal audit CON-6).
    const block = [
      'Attached files (1):',
      '1. shot.png — image/png, 2 B',
      '   Path: /data/attachments/abcdef123456/ff05e68a8a33/shot.png',
      '',
      'Look at this'
    ].join('\n')
    const parsed = parseTurn(block)
    expect(parsed.recognised).toBe(true)
    expect(parsed.attachments[0].id).toBe('ff05e68a8a33')
  })

  it('keeps the whole file name when the name contains the separator', () => {
    // The entry's name group was lazy, so "Invoice — March.pdf" parsed as "Invoice" with the
    // rest in the detail (the internal audit CON-7).
    const block = [
      'Attached files (1):',
      '1. Invoice — March.pdf — application/pdf, 4 KB',
      '   Path: /data/attachments/web-1/ff05e68a8a33/Invoice — March.pdf',
      '',
      'Check it'
    ].join('\n')
    const parsed = parseTurn(block)
    expect(parsed.attachments[0].name).toBe('Invoice — March.pdf')
    expect(parsed.attachments[0].detail).toBe('application/pdf, 4 KB')
  })

  it('still finds the id when the attachment is a folder pick', () => {
    const block = [
      'Attached files (1):',
      '1. quotes — folder, 2 files, 10 B',
      '   Path: /data/attachments/web-1/ff05e68a8a33/quotes/march.pdf',
      '',
      'Three quotes'
    ].join('\n')
    expect(parseTurn(block).attachments[0].id).toBe('ff05e68a8a33')
  })

  it('reads an attachment-only turn, where the block is the whole message', () => {
    const parsed = parseTurn(GOLDEN.slice(GOLDEN.indexOf('Attached files')))
    expect(parsed.recognised).toBe(true)
    expect(parsed.text).toBe('')
    expect(parsed.attachments).toHaveLength(3)
  })

  it('leaves an ordinary message exactly as it was', () => {
    const parsed = parseTurn('Invoice Bellview for 12 kilos of beans')
    expect(parsed.recognised).toBe(false)
    expect(parsed.text).toBe('Invoice Bellview for 12 kilos of beans')
    expect(parsed.attachments).toEqual([])
  })

  it('gives up rather than half-parsing a block it does not understand', () => {
    // A header with no entries under it: a malformed block must not become an empty set of
    // chips, because that would silently drop the files from the screen.
    const broken = 'Invoice these\n\nAttached files (2):\nsomething else entirely'
    const parsed = parseTurn(broken)
    expect(parsed.recognised).toBe(false)
    expect(parsed.text).toBe(broken)
  })

  it('stops at the first entry that is missing its path', () => {
    const truncated = [
      'hi',
      '',
      'Attached files (2):',
      '1. a.csv — text/csv, 10 B',
      '   Path: /tmp/a.csv',
      '2. b.csv — text/csv, 10 B'
    ].join('\n')
    const parsed = parseTurn(truncated)
    expect(parsed.recognised).toBe(true)
    expect(parsed.attachments.map(ref => ref.name)).toEqual(['a.csv'])
  })

  it('prefers the last block, so an operator quoting the format does not confuse it', () => {
    const quoted = ['Attached files (1):', '1. old.csv — text/csv, 1 B', '   Path: /tmp/old.csv']
    const message = [...quoted, '', 'now do this', '', ...quoted].join('\n')
    const parsed = parseTurn(message)
    expect(parsed.recognised).toBe(true)
    expect(parsed.text).toContain('now do this')
  })
})

describe('formatBytes', () => {
  it('matches what the assistant is told', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(999)).toBe('999 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB')
    expect(formatBytes(150 * 1024 * 1024)).toBe('150 MB')
  })
})

describe('a draft before the server has spoken', () => {
  it('guesses an image from either the type or the name', () => {
    expect(draftKind('barn.png', '')).toBe('image')
    expect(draftKind('barn', 'image/jpeg')).toBe('image')
    expect(draftKind('notes.md', 'text/markdown')).toBe('text')
    expect(draftKind('report.pdf', 'application/pdf')).toBe('document')
    expect(draftKind('thing.bin', '')).toBe('other')
  })

  it('names a pasted screenshot so it can be recognised later', () => {
    const at = new Date(2026, 9, 13, 9, 4, 5)
    expect(pastedName('image/png', at)).toBe('pasted-20261013-090405.png')
    expect(pastedName('image/jpeg', at)).toBe('pasted-20261013-090405.jpg')
    // A subtype is not always an extension: `text/plain` is not `.plain`.
    expect(largePasteName(at)).toBe('pasted-20261013-090405.txt')
  })

  it('takes a folder name from the picker’s own relative paths', () => {
    expect(folderNameFromPaths(['orders-2024/q1/beans.csv', 'orders-2024/eggs.csv'])).toBe(
      'orders-2024'
    )
    expect(folderNameFromPaths(['beans.csv'])).toBeUndefined()
  })

  it('labels every kind the listing can carry', () => {
    for (const kind of ['image', 'document', 'text', 'archive', 'folder', 'url', 'other'] as const) {
      expect(kindLabel(kind)).toBeTruthy()
    }
  })
})
