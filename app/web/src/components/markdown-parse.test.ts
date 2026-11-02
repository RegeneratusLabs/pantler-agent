import { describe, expect, it } from 'vitest'
import {
  linkKind,
  markdownToText,
  parseInline,
  parseMarkdown,
  plainText,
  type Block,
  type Inline
} from './markdown-parse'

/**
 * The parser's tests, written against documents rather than against functions.
 *
 * `parseMarkdown` is the entry point — a markdown file is what arrives — and the assertions
 * walk the tree it returns. The cases are the ones a delivered `.md` actually contains, in the
 * order the operator asked for them: `**bold**` first, because a file whose emphasis is printed
 * as asterisks is the bug this module exists to fix.
 */

/** The block kinds, for a test that cares about the shape of a document rather than its text. */
function kinds(source: string): string[] {
  return parseMarkdown(source).map(block => block.kind)
}

/** A block's text, with its markup flattened — the shortest way to assert on a heading or a cell. */
function textOf(block: Block): string {
  return plainText(childrenOf(block))
}

function childrenOf(block: Block): Inline[] {
  switch (block.kind) {
    case 'heading':
    case 'paragraph':
      return block.children
    case 'quote':
      return []
    case 'list':
      return block.items.flatMap(item => item.flatMap(childrenOf))
    default:
      return []
  }
}

describe('emphasis', () => {
  it('makes **bold** bold', () => {
    const [paragraph] = parseMarkdown('a **bold** word')
    expect(paragraph).toEqual({
      kind: 'paragraph',
      children: [
        { kind: 'text', text: 'a ' },
        { kind: 'strong', children: [{ kind: 'text', text: 'bold' }] },
        { kind: 'text', text: ' word' }
      ]
    })
  })

  it('makes __bold__ bold too, and *italic* italic', () => {
    const [paragraph] = parseMarkdown('__one__ and *two*')
    expect(paragraph.kind).toBe('paragraph')
    expect(childrenOf(paragraph)).toEqual([
      { kind: 'strong', children: [{ kind: 'text', text: 'one' }] },
      { kind: 'text', text: ' and ' },
      { kind: 'em', children: [{ kind: 'text', text: 'two' }] }
    ])
  })

  it('keeps bold inside italic, which is how a sentence is normally emphasised', () => {
    // The case this app's own documents are full of: `*"… **the important part**"*`.
    expect(childrenOf(parseMarkdown('*an **important** word*')[0])).toEqual([
      {
        kind: 'em',
        children: [
          { kind: 'text', text: 'an ' },
          { kind: 'strong', children: [{ kind: 'text', text: 'important' }] },
          { kind: 'text', text: ' word' }
        ]
      }
    ])
  })

  it('nests ***both*** as strong around em', () => {
    const [paragraph] = parseMarkdown('***both***')
    expect(childrenOf(paragraph)).toEqual([
      {
        kind: 'strong',
        children: [{ kind: 'em', children: [{ kind: 'text', text: 'both' }] }]
      }
    ])
  })

  it('takes ~~strikethrough~~ and `code`', () => {
    const [paragraph] = parseMarkdown('~~gone~~ and `x = 1`')
    expect(childrenOf(paragraph)).toEqual([
      { kind: 'del', children: [{ kind: 'text', text: 'gone' }] },
      { kind: 'text', text: ' and ' },
      { kind: 'code', text: 'x = 1' }
    ])
  })

  it('does not break a word in half on an underscore', () => {
    expect(plainText(parseInline('snake_case_name stays put'))).toBe('snake_case_name stays put')
    expect(childrenOf(parseMarkdown('snake_case_name')[0])).toEqual([
      { kind: 'text', text: 'snake_case_name' }
    ])
  })

  it('honours a backslash escape', () => {
    expect(plainText(parseInline('\\*not italic\\*'))).toBe('*not italic*')
    expect(parseInline('\\*not italic\\*')[0].kind).toBe('text')
  })

  it('refuses an emphasis marker with nothing between it', () => {
    // `** **` is spaces, not emphasis — the case a half-rendered document shows as bold nothing.
    expect(parseInline('** **')).toEqual([{ kind: 'text', text: '** **' }])
  })

  it('terminates on a pathological run of markers', () => {
    // Not a document anybody wrote: the property under test is that a hostile `.md` cannot hang
    // the pane or blow the stack, which is what an unbounded recursive inline parser does.
    const drawn = '*'.repeat(4000)
    const nodes = parseInline(drawn)
    expect(Array.isArray(nodes)).toBe(true)
    expect(plainText(nodes).length).toBeGreaterThan(0)
  })
})

describe('links', () => {
  it('keeps a markdown link, and its label as inline text', () => {
    const nodes = parseInline('see [the prices](https://example.com/prices)')
    expect(nodes[1]).toEqual({
      kind: 'link',
      href: 'https://example.com/prices',
      children: [{ kind: 'text', text: 'the prices' }]
    })
  })

  it('drops a title and unwraps an angle-bracketed address', () => {
    expect(parseInline('[a](<https://x.dev/a b> "title")')[0]).toMatchObject({
      kind: 'link',
      href: 'https://x.dev/a b'
    })
  })

  it('turns a bare URL into a url node, punctuation trimmed', () => {
    const nodes = parseInline('Read https://example.com/prices. Now.')
    expect(nodes.find(node => node.kind === 'url')).toEqual({
      kind: 'url',
      url: 'https://example.com/prices'
    })
  })

  it('reads an autolink without its angle brackets', () => {
    expect(parseInline('see <https://example.com/soil> now')).toEqual([
      { kind: 'text', text: 'see ' },
      { kind: 'url', url: 'https://example.com/soil' },
      { kind: 'text', text: ' now' }
    ])
    // A tag that is not an address is left as the text it is.
    expect(plainText(parseInline('a <span> word'))).toBe('a <span> word')
  })

  it('never makes an action out of an address that is not http, https or mailto', () => {
    expect(linkKind('https://example.com')).toBe('site')
    expect(linkKind('  HTTPS://Example.com  ')).toBe('site')
    expect(linkKind('mailto:josh@example.com')).toBe('mail')
    expect(linkKind('javascript:alert(1)')).toBe('plain')
    expect(linkKind('JaVaScRiPt:alert(1)')).toBe('plain')
    expect(linkKind('data:text/html,<script>x</script>')).toBe('plain')
    expect(linkKind('//example.com')).toBe('plain')
    expect(linkKind('../prices.md')).toBe('plain')
    expect(linkKind('#the-section')).toBe('plain')
    // The parser keeps the address; it is the renderer that asks, so the two can be tested apart.
    expect(parseInline('[x](javascript:alert(1))')[0]).toMatchObject({
      kind: 'link',
      href: 'javascript:alert(1)'
    })
  })

  it('draws an image as its alt text rather than fetching it', () => {
    expect(parseInline('![a chart](https://example.com/chart.png)')).toEqual([
      { kind: 'image', href: 'https://example.com/chart.png', alt: 'a chart' }
    ])
  })

  it('keeps a link label with a nested bracket', () => {
    expect(parseInline('[a [b] c](https://x.dev)')[0]).toMatchObject({
      kind: 'link',
      href: 'https://x.dev'
    })
  })
})

describe('blocks', () => {
  it('reads ATX headings by level', () => {
    const blocks = parseMarkdown('# One\n\n### Three\n\n###### Six')
    expect(blocks.map(block => (block.kind === 'heading' ? block.level : 0))).toEqual([1, 3, 6])
  })

  it('joins a wrapped paragraph and keeps a hard break', () => {
    const [wrapped] = parseMarkdown('one line\nand the next')
    expect(plainText(childrenOf(wrapped))).toBe('one line\nand the next')

    const [broken] = parseMarkdown('one line  \nand the next')
    expect(childrenOf(broken).some(node => node.kind === 'break')).toBe(true)
  })

  it('reads both list kinds, with the ordered list’s own start', () => {
    const [bullets] = parseMarkdown('- beans\n- eggs')
    expect(bullets.kind === 'list' && bullets.ordered).toBe(false)
    expect(bullets.kind === 'list' && bullets.items.length).toBe(2)

    const [numbers] = parseMarkdown('3. three\n4. four')
    expect(numbers).toMatchObject({ kind: 'list', ordered: true, start: 3 })
  })

  it('nests a list under the item it is indented beneath', () => {
    const [list] = parseMarkdown('- fruit\n  - apples\n  - pears\n- bread')
    expect(list.kind).toBe('list')
    if (list.kind !== 'list') return
    expect(list.items.length).toBe(2)
    expect(list.items[0].map(block => block.kind)).toEqual(['paragraph', 'list'])
    expect(list.items[1].map(block => block.kind)).toEqual(['paragraph'])
  })

  it('keeps an item’s continuation line as its text', () => {
    const [list] = parseMarkdown('- a delivery\n  that arrived late')
    expect(list.kind).toBe('list')
    if (list.kind !== 'list') return
    expect(plainText(childrenOf(list.items[0][0]))).toBe('a delivery\nthat arrived late')
  })

  it('reads a fenced block, its language, and the source inside it verbatim', () => {
    const [code] = parseMarkdown('```python\nprint("**not bold**")\n```')
    expect(code).toEqual({ kind: 'code', language: 'python', text: 'print("**not bold**")' })
  })

  it('runs an unterminated fence to the end rather than losing it', () => {
    expect(parseMarkdown('```\nstill code')).toEqual([
      { kind: 'code', language: '', text: 'still code' }
    ])
  })

  it('does not mistake a fence for a paragraph, or the other way round', () => {
    expect(kinds('# a\n\ntext\n\n- item\n\n> quote\n\n---\n\n```\ncode\n```')).toEqual([
      'heading',
      'paragraph',
      'list',
      'quote',
      'rule',
      'code'
    ])
  })

  it('reads a blockquote as blocks of its own', () => {
    const [quote] = parseMarkdown('> quoted **words**\n> and a second line')
    expect(quote.kind).toBe('quote')
    if (quote.kind !== 'quote') return
    expect(quote.children[0].kind).toBe('paragraph')
    // The two quoted lines are one paragraph: a single newline is a soft break, which is a
    // space on screen (the renderer does not preserve whitespace), not two paragraphs.
    expect(plainText(childrenOf(quote.children[0]))).toBe('quoted words\nand a second line')
    expect(childrenOf(quote.children[0])).toContainEqual({
      kind: 'strong',
      children: [{ kind: 'text', text: 'words' }]
    })
  })

  it('reads a table with its alignment and its rows', () => {
    const [table] = parseMarkdown('| item | qty |\n| :--- | ---: |\n| beans | 12 |')
    expect(table.kind).toBe('table')
    if (table.kind !== 'table') return
    expect(table.align).toEqual(['left', 'right'])
    expect(table.head.map(cell => plainText(cell))).toEqual(['item', 'qty'])
    expect(table.rows.map(row => row.map(cell => plainText(cell)))).toEqual([['beans', '12']])
  })

  it('shows a raw HTML block as text, never as markup', () => {
    const blocks = parseMarkdown('<div class="x">\n  <b>bold?</b>\n</div>')
    expect(blocks).toEqual([{ kind: 'html', text: '<div class="x">\n  <b>bold?</b>\n</div>' }])
  })

  it('leaves a setext underline visible rather than swallowing the line above it', () => {
    // Not supported, and honest about it: the words are still on screen.
    const blocks = parseMarkdown('Title\n===')
    expect(blocks.every(block => block.kind === 'paragraph' || block.kind === 'rule')).toBe(true)
    expect(textOf(blocks[0])).toContain('Title')
  })

  it('is an empty document for empty input', () => {
    expect(parseMarkdown('')).toEqual([])
    expect(parseMarkdown('\n\n  \n')).toEqual([])
  })
})


describe('markdownToText', () => {
  it('flattens emphasis, headings and lists to the words a reader sees', () => {
    expect(markdownToText('# Weekly totals\n\n**Bellview CSA** owes:\n\n- 12 kg beans\n- 4 dozen eggs')).toBe(
      'Weekly totals\n\nBellview CSA owes:\n\n- 12 kg beans\n- 4 dozen eggs'
    )
  })

  it('keeps a table readable as rows rather than pipes in the source', () => {
    expect(markdownToText('| Item | Amount |\n| --- | --- |\n| Beans | $144.00 |')).toBe(
      'Item | Amount\nBeans | $144.00'
    )
  })

  it('keeps code as code and a link with its address', () => {
    expect(markdownToText('Run `npm test` and see [the docs](https://example.com/docs).')).toBe(
      'Run npm test and see the docs (https://example.com/docs).'
    )
  })

  it('keeps a bare URL in the text', () => {
    expect(markdownToText('The market is at https://example.com/market this week.')).toBe(
      'The market is at https://example.com/market this week.'
    )
  })

  it('is empty for an empty message', () => {
    expect(markdownToText('')).toBe('')
  })
})
