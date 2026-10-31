import { Fragment, type ReactNode } from 'react'
import { linkify } from './links'
import { siteTarget } from './preview'
import { usePreview } from './preview-context'
import { cn } from '../ui/cn'

/**
 * Plain prose, with the URLs in it made clickable.
 *
 * The assistant's answer is rendered markdown now (`Markdown.tsx`, chat scale). What stays here
 * is the text that should not be interpreted: the operator's own message and the assistant's
 * interim status line. Both are still the same wrapper — `whitespace-pre-wrap`, no headings and
 * no lists — and the only change from a bare paragraph is that an `http(s)` URL becomes a button
 * that opens the preview pane, with the browser's own new tab as the secondary action (a
 * modifier-click, or the pane's own link).
 *
 * The click is intercepted rather than followed because the pane is the point: a link the
 * assistant read should be readable *here*, next to what it said about it, and a site that turns
 * out to be unreadable is one that gets a snapshot and a "open in a tab" instead.
 */
export function Prose({
  text,
  className,
  as: Tag = 'p'
}: {
  text: string
  className?: string
  as?: 'p' | 'span' | 'div'
}) {
  const segments = linkify(text)

  return (
    <Tag className={cn('whitespace-pre-wrap', className)}>
      {segments.map((segment, index) =>
        segment.kind === 'text' ? (
          <Fragment key={index}>{segment.text}</Fragment>
        ) : (
          <PreviewLink key={index} url={segment.url}>
            {segment.text}
          </PreviewLink>
        )
      )}
    </Tag>
  )
}

/**
 * One `http(s)` URL, made openable — the rule, in the one place it lives.
 *
 * `Prose` applies it to plain prose and `Markdown` applies it to a link in a document or an
 * answer; both mean the same thing by it, so both come here. A modifier-click, a middle click or
 * a non-primary button keeps the browser's own behaviour: a person who asks for a tab should get
 * a tab.
 */
export function PreviewLink({
  url,
  children,
  className
}: {
  url: string
  children: ReactNode
  className?: string
}) {
  const { open } = usePreview()

  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      title={url}
      onClick={event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
        if (event.button !== 0) return
        event.preventDefault()
        // `siteTarget` is the gate, not this component: it answers `null` for anything that is
        // not an http(s) address, and then there is nothing to open
        // (the internal security audit A19-WEB-3).
        const target = siteTarget(url)
        if (target) open(target)
      }}
      className={cn(
        'text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent/70',
        className
      )}
    >
      {children}
    </a>
  )
}
