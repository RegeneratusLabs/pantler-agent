// @vitest-environment jsdom
/**
 * What the markdown renderer draws, from its props.
 *
 * The parser has its own suite (`markdown.test.ts`); this one is about the two scales and the
 * properties that must survive both. It renders with `react-dom/server`, because the component's
 * output is the point and there are no effects to wait for. The environment is jsdom rather than
 * the default node one because `Markdown` reaches `PreviewLink` (and therefore the preview
 * context, which touches `window`) for every link it draws.
 *
 * The chat cases are the shapes a model actually writes: an ATX heading, a bold lead, a bullet
 * list, a pipe table, a fenced block and a link. The document cases are the preview pane's
 * existing scale, which must not move while the chat scale is added.
 */

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Markdown, type MarkdownVariant } from './Markdown'

const draw = (text: string, variant: MarkdownVariant = 'chat') =>
  renderToStaticMarkup(<Markdown text={text} variant={variant} />)

const ANSWER = `# Weekly totals

**Bellview CSA** owes:

- 12 kg beans
- 4 dozen eggs

| Item | Amount |
| --- | --- |
| Beans | $144.00 |
| Eggs | $36.00 |

\`\`\`sh
echo ok
\`\`\`
`

describe('the chat scale', () => {
  it('draws an answer as headings, bold, lists, a table and code', () => {
    const html = draw(ANSWER)

    // `#` becomes an h2 in chat, so the answer sits under the shell's own h1; the size is the
    // top chat step, not the document's quiet text-lg.
    expect(html).toMatch(/<h2[^>]*class="[^"]*text-2xl/)
    expect(html).toContain('<strong')
    expect(html).toContain('<ul')
    expect(html.match(/<li/g)).toHaveLength(2)
    expect(html).toContain('<table')
    expect(html).toContain('scope="col"')
    expect(html).toContain('Beans')
    expect(html).toContain('<pre')
    expect(html).toContain('font-mono')

    // The point of the change: the punctuation is gone from the words on screen.
    expect(html).not.toContain('**Bellview')
    expect(html).not.toContain('| Item |')
    expect(html).not.toContain('- 12 kg')
  })

  it('steps the heading levels down under the shell heading', () => {
    expect(draw('# One')).toMatch(/<h2[^>]*text-2xl/)
    expect(draw('## Two')).toMatch(/<h3[^>]*text-xl/)
    expect(draw('### Three')).toMatch(/<h4[^>]*text-lg/)
    expect(draw('#### Four')).toMatch(/<h5[^>]*text-base/)
    expect(draw('##### Five')).toMatch(/<h6[^>]*text-sm/)
  })

  it('uses the chat body size and gap', () => {
    const html = draw('A sentence.')
    expect(html).toContain('text-base')
    expect(html).toContain('gap-4')
  })
})

describe('the document scale', () => {
  it('is unchanged: an h1 and the quiet text-lg', () => {
    expect(draw('# Title', 'document')).toMatch(/<h1[^>]*text-lg/)
    expect(draw('A sentence.', 'document')).toContain('text-sm')
  })

  it('keeps the document table compact', () => {
    const html = draw('| Item | Amount |\n| --- | --- |\n| Beans | $144.00 |', 'document')
    expect(html).toContain('text-[0.8rem]')
    expect(html).toContain('px-2')
  })
})

describe('safety is the same in both scales', () => {
  it('opens only an http(s) link', () => {
    const html = draw('[lab report](https://example.com/lab)')
    expect(html).toContain('href="https://example.com/lab"')
    expect(html).toContain('target="_blank"')
  })

  it('leaves a javascript: address as words', () => {
    const html = draw('[nope](javascript:alert(1))')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('nope')
  })

  it('shows a raw HTML block as text, never as markup', () => {
    const html = draw('<div class="note">not a page</div>')
    expect(html).not.toContain('<div class="note">')
    expect(html).toContain('&lt;div')
  })

  it('renders an empty answer as an empty document', () => {
    const html = draw('')
    expect(html).toContain('<div')
    expect(html).not.toContain('<p>')
    expect(html).not.toContain('<h')
  })
})
