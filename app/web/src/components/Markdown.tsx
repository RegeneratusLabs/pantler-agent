import { Fragment, useMemo, type ReactNode } from 'react'
import { Image as ImageIcon } from 'lucide-react'
import { linkKind, parseMarkdown, type Align, type Block, type Inline } from './markdown-parse'
import { PreviewLink } from './Prose'
import { cn } from '../ui/cn'

/**
 * A markdown document, drawn as elements.
 *
 * `markdown.ts` decides *what the document says* and this decides how it looks; the split is the
 * same one `links.ts`/`Prose.tsx` and `preview.ts`/`PreviewSidebar.tsx` keep, and it is what makes
 * the parser testable without a DOM. Two properties are this file's rather than the parser's:
 *
 *   - **Everything is a React element.** A `<strong>` here is a `<strong>`; there is no
 *     `dangerouslySetInnerHTML` in this path, so a document cannot inject markup by being read.
 *   - **A link is opened the way prose links are.** An `http(s)` address goes through
 *     `PreviewLink`, which reaches the preview pane's own context and leaves the browser's new
 *     tab to a modifier click. A `mailto:` is a mail link; anything else — a relative path, an
 *     anchor, a `javascript:` address — is drawn as the words it is (`markdown.ts` `linkKind`).
 *
 * There are two scales, because the same document is read in two different places:
 *
 *   - **`document`** is the preview pane. A document sits beside a conversation, and its `#` is
 *     not the app's own heading, so the scale is deliberately quiet. Nothing here is
 *     `text-display`, because that is brand chrome and a file is not the brand.
 *   - **`chat`** is the assistant's answer. It is the thing the operator is reading, so it gets
 *     the body size and the heading steps a conversation expects. Markdown headings are the UI
 *     sans, never the display face: a heading in an answer is still not brand chrome.
 *
 * In the chat scale `#` is drawn as an `<h2>` and every level shifts down one. The page already
 * has an `<h1>` (the shell's title), and an answer is a section of that page rather than a second
 * title. The visual sizes still step down from 1.5rem.
 */

export type MarkdownVariant = 'document' | 'chat'

export function Markdown({
  text,
  className,
  variant = 'document'
}: {
  text: string
  className?: string
  variant?: MarkdownVariant
}) {
  const blocks = useMemo(() => parseMarkdown(text ?? ''), [text])
  const scale = SCALES[variant]

  return (
    <div className={cn(scale.root, className)}>
      {blocks.map((block, index) => (
        <Fragment key={index}>{blockView(block, variant)}</Fragment>
      ))}
    </div>
  )
}

interface Scale {
  root: string
  list: (ordered: boolean) => string
  item: string
  quote: string
  codeLanguage: string
  code: string
  html: string
  tableWrap: string
  table: string
  th: string
  td: string
}

const SCALES: Record<MarkdownVariant, Scale> = {
  document: {
    root: 'flex flex-col gap-3 text-sm leading-relaxed text-ink-2 [overflow-wrap:anywhere]',
    list: ordered =>
      ordered
        ? 'flex list-decimal flex-col gap-1 pl-5'
        : 'flex list-disc flex-col gap-1 pl-5',
    item: '',
    quote: 'border-l-2 border-line pl-3 text-ink-3',
    codeLanguage: 'text-display text-[0.6rem] text-ink-disabled',
    code:
      'overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono ' +
      'text-[0.72rem] leading-relaxed text-ink-2',
    html:
      'overflow-auto rounded-lg border border-line bg-canvas/50 p-3 font-mono ' +
      'text-[0.7rem] whitespace-pre-wrap text-ink-disabled',
    tableWrap: 'overflow-x-auto',
    table: 'w-full border-collapse text-[0.8rem]',
    th: 'border border-line bg-hover/50 px-2 py-1 font-medium text-ink',
    td: 'border border-line px-2 py-1 align-top'
  },
  chat: {
    root: 'flex flex-col gap-4 text-base leading-relaxed text-ink-2 [overflow-wrap:anywhere]',
    list: ordered =>
      ordered
        ? 'flex list-decimal flex-col gap-2 pl-6 marker:text-ink-3'
        : 'flex list-disc flex-col gap-2 pl-6 marker:text-ink-3',
    item: '[&>*+*]:mt-2',
    quote: 'border-l-2 border-accent/40 pl-4 text-ink-2',
    codeLanguage: 'text-display text-[0.65rem] text-ink-disabled',
    code:
      'max-w-full overflow-auto rounded-lg border border-line bg-canvas/60 p-4 font-mono ' +
      'text-[0.85rem] leading-relaxed text-ink-2',
    html:
      'max-w-full overflow-auto rounded-lg border border-line bg-canvas/60 p-4 font-mono ' +
      'text-[0.8rem] whitespace-pre-wrap text-ink-disabled',
    tableWrap: 'max-w-full overflow-x-auto rounded-lg border border-line',
    table: 'w-full border-collapse text-[0.95rem]',
    th: 'border-b border-line bg-hover/60 px-3 py-2 font-semibold text-ink',
    td: 'border-b border-line/60 px-3 py-2 align-top'
  }
}

const DOCUMENT_HEADING: Record<number, string> = {
  1: 'font-semibold text-ink mt-1 text-lg',
  2: 'font-semibold text-ink mt-1 text-base',
  3: 'font-semibold text-ink text-sm',
  4: 'font-semibold text-ink text-xs text-ink-2',
  5: 'font-semibold text-ink text-xs text-ink-2',
  6: 'font-semibold text-ink text-xs text-ink-2'
}

const CHAT_HEADING: Record<number, string> = {
  1: 'font-semibold text-ink text-2xl leading-tight',
  2: 'font-semibold text-ink text-xl leading-snug',
  3: 'font-semibold text-ink text-lg leading-snug',
  4: 'font-semibold text-ink text-base',
  5: 'font-semibold text-ink text-sm',
  6: 'font-semibold text-ink text-sm'
}

function blockView(block: Block, variant: MarkdownVariant): ReactNode {
  const scale = SCALES[variant]

  switch (block.kind) {
    case 'heading':
      return (
        <Heading level={block.level} variant={variant}>
          {inlineView(block.children)}
        </Heading>
      )

    case 'paragraph':
      return <p>{inlineView(block.children)}</p>

    case 'list':
      return block.ordered ? (
        <ol start={block.start} className={scale.list(true)}>
          {block.items.map((item, index) => (
            <li key={index} className={scale.item}>
              {blocksView(item, variant)}
            </li>
          ))}
        </ol>
      ) : (
        <ul className={scale.list(false)}>
          {block.items.map((item, index) => (
            <li key={index} className={scale.item}>
              {blocksView(item, variant)}
            </li>
          ))}
        </ul>
      )

    case 'quote':
      return (
        <blockquote className={scale.quote}>
          <div className="flex flex-col gap-2">{blocksView(block.children, variant)}</div>
        </blockquote>
      )

    case 'code':
      return (
        <div className="flex flex-col gap-1">
          {block.language && <span className={scale.codeLanguage}>{block.language}</span>}
          <pre className={scale.code}>
            <code>{block.text}</code>
          </pre>
        </div>
      )

    case 'rule':
      return <hr className="border-0 border-t border-line" />

    case 'table':
      return <TableView table={block} variant={variant} />

    case 'html':
      // Shown, never parsed: an HTML block in a document is text here, which is the same answer
      // `previews.py` gives an `.html` file — no page is ever executed because it was scrolled
      // past.
      return <pre className={scale.html}>{block.text}</pre>
  }
}

function blocksView(blocks: Block[], variant: MarkdownVariant): ReactNode {
  return blocks.map((block, index) => <Fragment key={index}>{blockView(block, variant)}</Fragment>)
}

/** A heading's size and semantic level. The chat scale shifts under the shell's own `<h1>`. */
function Heading({
  level,
  variant,
  children
}: {
  level: number
  variant: MarkdownVariant
  children: ReactNode
}) {
  const className = variant === 'chat' ? CHAT_HEADING[level] : DOCUMENT_HEADING[level]
  const tag = variant === 'chat' ? Math.min(level + 1, 6) : Math.min(level, 6)
  const Tag = `h${tag}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'
  return <Tag className={className}>{children}</Tag>
}

function TableView({ table, variant }: { table: Extract<Block, { kind: 'table' }>; variant: MarkdownVariant }) {
  const scale = SCALES[variant]

  return (
    <div className={scale.tableWrap}>
      <table className={scale.table}>
        <thead>
          <tr>
            {table.head.map((cell, index) => (
              <th
                key={index}
                scope="col"
                className={cn(scale.th, alignClass(table.align[index]))}
              >
                {inlineView(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={cn(scale.td, alignClass(table.align[cellIndex]))}
                >
                  {inlineView(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function alignClass(align: Align | null | undefined): string {
  if (align === 'center') return 'text-center'
  if (align === 'right') return 'text-right'
  return 'text-left'
}

/** Inline nodes, in order. `key` is the index: a document does not reorder under itself. */
function inlineView(nodes: Inline[]): ReactNode {
  return nodes.map((node, index) => <Fragment key={index}>{inlineNode(node)}</Fragment>)
}

function inlineNode(node: Inline): ReactNode {
  switch (node.kind) {
    case 'text':
      return node.text

    case 'break':
      return <br />

    case 'strong':
      return <strong className="font-semibold text-ink">{inlineView(node.children)}</strong>

    case 'em':
      return <em>{inlineView(node.children)}</em>

    case 'del':
      return <del className="text-ink-3">{inlineView(node.children)}</del>

    case 'code':
      return (
        <code className="rounded border border-line bg-canvas/50 px-1 py-0.5 font-mono text-[0.78em] text-ink">
          {node.text}
        </code>
      )

    case 'url':
      return <PreviewLink url={node.url}>{node.url}</PreviewLink>

    case 'link':
      return linkView(node)

    case 'image':
      return imageView(node)
  }
}

function linkView(node: Extract<Inline, { kind: 'link' }>): ReactNode {
  const children = inlineView(node.children)
  const kind = linkKind(node.href)

  if (kind === 'site') return <PreviewLink url={node.href}>{children}</PreviewLink>
  if (kind === 'mail') {
    return (
      <a
        href={node.href}
        className="text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent/70"
      >
        {children}
      </a>
    )
  }
  // A relative path, an in-document anchor, or an address this will not open. The words stay on
  // screen — D8's rule for a path with no working directory — and the address rides in the title
  // so it can still be read and copied.
  return <span title={node.href}>{children}</span>
}

function imageView(node: Extract<Inline, { kind: 'image' }>): ReactNode {
  const label = node.alt || node.href
  const glyph = <ImageIcon className="inline size-3.5 shrink-0 align-[-0.15em]" aria-hidden />

  if (linkKind(node.href) !== 'site') {
    return (
      <span className="text-ink-3" title={node.href}>
        {glyph} {label}
      </span>
    )
  }
  return (
    <span className="whitespace-nowrap">
      <PreviewLink url={node.href} className="inline-flex items-center gap-1">
        {glyph}
        {label}
      </PreviewLink>
    </span>
  )
}
