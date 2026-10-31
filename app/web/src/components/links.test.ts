import { describe, expect, it } from 'vitest'
import { linkify, trimUrl } from './links'

/** The segments as a compact shape, so an assertion reads like the sentence it came from. */
function parts(text: string) {
  return linkify(text).map(segment => (segment.kind === 'url' ? `[${segment.url}]` : segment.text))
}

describe('linkify', () => {
  it('leaves a sentence with no link as one text segment', () => {
    expect(linkify('Twelve kilos of beans.')).toEqual([
      { kind: 'text', text: 'Twelve kilos of beans.' }
    ])
  })

  it('finds a URL inside a sentence and keeps the words around it', () => {
    expect(parts('See https://example.com/prices for the list.')).toEqual([
      'See ',
      '[https://example.com/prices]',
      ' for the list.'
    ])
  })

  it('takes the trailing full stop, and not the path', () => {
    expect(parts('Read https://example.com/a/b.html.')).toEqual([
      'Read ',
      '[https://example.com/a/b.html]',
      '.'
    ])
  })

  it('keeps a bracket that closes one the URL opened', () => {
    expect(parts('(https://en.wikipedia.org/wiki/Foo_(bar))')).toEqual([
      '(',
      '[https://en.wikipedia.org/wiki/Foo_(bar)]',
      ')'
    ])
    expect(trimUrl('https://x.dev/a(b)')).toBe('https://x.dev/a(b)')
    expect(trimUrl('https://x.dev/a)')).toBe('https://x.dev/a')
  })

  it('keeps a query string, a fragment and a port', () => {
    expect(trimUrl('https://example.com:8443/a?b=1&c=2#top')).toBe(
      'https://example.com:8443/a?b=1&c=2#top'
    )
  })

  it('finds several links in one message, across lines', () => {
    expect(parts('two:\nhttps://a.dev/x\nhttps://b.dev/y\n')).toEqual([
      'two:\n',
      '[https://a.dev/x]',
      '\n',
      '[https://b.dev/y]',
      '\n'
    ])
  })

  it('does not invent a link where there is no scheme', () => {
    expect(linkify('www.example.com and example.com/path')).toEqual([
      { kind: 'text', text: 'www.example.com and example.com/path' }
    ])
  })

  it('does not link a path, however file-shaped', () => {
    // The rule from the file-preview design §4 D7: a path is previewed from a structured place,
    // never guessed out of a sentence.
    expect(parts('Wrote /home/you/out/beans.csv')).toEqual(['Wrote /home/you/out/beans.csv'])
  })

  it('stops at a character that cannot be in a URL', () => {
    expect(parts('a <https://x.dev/a> b')).toEqual(['a <', '[https://x.dev/a]', '> b'])
    expect(parts('"https://x.dev/a"')).toEqual(['"', '[https://x.dev/a]', '"'])
  })


  it('never returns an empty URL', () => {
    for (const text of ['https://', 'https://.', 'http:// ']) {
      expect(linkify(text).every(segment => segment.kind === 'text' || segment.url.length > 8)).toBe(
        true
      )
    }
  })
})
