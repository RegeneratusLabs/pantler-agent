/**
 * Reading `MEDIA:` out of a reply.
 *
 * The cases are the ones the engine's own desktop has to handle, because the directive is the
 * engine's and the model writes it the same way here: a line of its own, two in a row, one
 * wrapped in quotes because it was copied out of a terminal result, and a path in a sentence
 * that is *not* a directive and must stay words.
 */

import { describe, expect, it } from 'vitest'
import { mediaPath, splitMedia } from './media'

const CARD = '/home/you/projects/pantler/output/instagram/markets/northey-street-sundays.png'
const CARD2 = '/home/you/projects/pantler/output/instagram/markets/pomona-saturdays.png'

describe('mediaPath', () => {
  it('reads a directive that is a line of its own', () => {
    expect(mediaPath(`MEDIA:${CARD}`)).toBe(CARD)
  })

  it('tolerates the whitespace a model puts after the colon', () => {
    expect(mediaPath(`MEDIA:   ${CARD}`)).toBe(CARD)
    expect(mediaPath(`  MEDIA:${CARD}  `)).toBe(CARD)
  })

  it('unwraps a quote or a backtick the path arrived with', () => {
    // A path copied out of a terminal result carries its quoting with it.
    expect(mediaPath(`MEDIA:"${CARD}"`)).toBe(CARD)
    expect(mediaPath(`MEDIA:'${CARD}'`)).toBe(CARD)
    expect(mediaPath(`MEDIA:\`${CARD}\``)).toBe(CARD)
  })

  it('drops the full stop a sentence leaves on the end', () => {
    expect(mediaPath(`MEDIA:${CARD}.`)).toBe(CARD)
  })

  it('refuses a relative path, which cannot be resolved honestly', () => {
    // The transcript carries no working directory, so this would be a card that cannot open.
    expect(mediaPath('MEDIA:output/instagram/card.png')).toBeUndefined()
    expect(mediaPath('MEDIA:./card.png')).toBeUndefined()
  })

  it('refuses a line that is not the directive', () => {
    expect(mediaPath(CARD)).toBeUndefined()
    expect(mediaPath(`Here it is: MEDIA:${CARD}`)).toBeUndefined()
    expect(mediaPath('MEDIA:')).toBeUndefined()
    expect(mediaPath('')).toBeUndefined()
  })

  it('refuses a path with no deliverable extension, which is a half-streamed one', () => {
    // The answer arrives a delta at a time, so a directive is briefly `/home/you/proj`. The
    // engine requires a known extension for the same reason: without it a fragment would render
    // as a card, be refused by the server, and redraw as the path grew.
    expect(mediaPath('MEDIA:/home/you/proj')).toBeUndefined()
    expect(mediaPath('MEDIA:/home/you/projects/pantler/output/instagram/markets/card')).toBeUndefined()
    expect(mediaPath('MEDIA:/home/you/projects/pantler/output/instagram/markets/card.pn')).toBeUndefined()
  })

  it('accepts the non-image types the engine delivers, so they can be cards', () => {
    expect(mediaPath('MEDIA:/home/you/projects/pantler/output/note.md')).toBe(
      '/home/you/projects/pantler/output/note.md'
    )
    expect(mediaPath('MEDIA:/tmp/a.pdf')).toBe('/tmp/a.pdf')
    expect(mediaPath('MEDIA:/tmp/a.csv')).toBe('/tmp/a.csv')
  })
})

describe('splitMedia', () => {
  it('takes the directives out of the answer and keeps the words', () => {
    // The shape the operator reported: two cards, then the sentence about them.
    const text = `Two cards are ready.\n\nMEDIA:${CARD}\nMEDIA:${CARD2}\n\nCaptions, ready to copy:`
    const said = splitMedia(text)

    expect(said.paths).toEqual([CARD, CARD2])
    expect(said.text).toBe('Two cards are ready.\n\nCaptions, ready to copy:')
  })

  it('leaves an answer with no directive exactly as it was', () => {
    const text = 'Just a sentence.\n\nAnd a second paragraph.'
    expect(splitMedia(text)).toEqual({ text, paths: [] })
  })

  it('collapses the blank lines a removed directive leaves behind', () => {
    // Otherwise a turn that was mostly attachments renders as a column of gaps.
    const said = splitMedia(`MEDIA:${CARD}\n\n\nMEDIA:${CARD2}`)
    expect(said.paths).toEqual([CARD, CARD2])
    expect(said.text).toBe('')
  })

  it('keeps a path mentioned in a sentence as words', () => {
    // Only the directive is recognised — never a path sniffed out of prose (D7).
    const text = `I wrote it to ${CARD} and you can open it there.`
    expect(splitMedia(text)).toEqual({ text, paths: [] })
  })

  it('keeps a directive that shares its line with a sentence as words', () => {
    // A line is only a directive when the whole line is one, so no sentence ever loses a word.
    const text = `Here it is: MEDIA:${CARD}`
    expect(splitMedia(text)).toEqual({ text, paths: [] })
  })

  it('names a file once even when the assistant repeated the directive', () => {
    const said = splitMedia(`MEDIA:${CARD}\nMEDIA:${CARD}\nReady.`)
    expect(said.paths).toEqual([CARD])
    expect(said.text).toBe('Ready.')
  })

  it('handles an empty answer and Windows line endings', () => {
    expect(splitMedia('')).toEqual({ text: '', paths: [] })
    expect(splitMedia(`One.\r\nMEDIA:${CARD}\r\nTwo.`)).toEqual({
      text: 'One.\nTwo.',
      paths: [CARD]
    })
  })
})
