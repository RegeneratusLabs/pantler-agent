/**
 * The assistant working, in words.
 *
 * A tool card is a record (the front-end design §4) and looks like one. This is the other
 * case: the errands behind an answer — searching the web, reading a file, running a command —
 * which are the assistant's business and not the operator's reading. One quiet line each, no
 * payload, and what sits behind the line is a title or a link rather than an envelope.
 *
 * Nothing here is a card: no border, no badge, no duration in the operator's face. It should be
 * possible to read a whole turn and notice the work only when you want to.
 */

import {
  BookOpen,
  Clock,
  FileText,
  Globe,
  Image as ImageIcon,
  Sparkles,
  Terminal,
  TriangleAlert,
  type LucideIcon
} from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import type { ToolCall } from '../seam/reducer'
import { cn } from '../ui/cn'
import {
  activityDetail,
  activityLayout,
  activityLine,
  anyRunning,
  detailLabel,
  effectiveStatus,
  failures,
  familyOf,
  hostOf,
  liveSummary,
  summarise,
  type ActivityDetail,
  type ToolFamily
} from './activity'
import { FileCard } from './FileCard'
import { siteTarget } from './preview'
import { usePreview } from './preview-context'

const ICONS: Record<ToolFamily, LucideIcon> = {
  web: Globe,
  file: FileText,
  media: ImageIcon,
  code: Terminal,
  help: BookOpen,
  memory: Sparkles,
  schedule: Clock
}

/**
 * One turn's run of errands, as a single quiet block.
 *
 * A run has three shapes (`activityLayout`): rows while it is short, a summary line with a
 * one-line ticker while it is live, and the same summary alone once it has settled past a few
 * steps. The live shape is the one this component exists for: a call arriving must never fold
 * the rows above it, and a run that is still going must not grow down the page — the ticker
 * slides each action up and out of one line instead.
 *
 * Failures are rows in every shape. A run that swallowed a refusal behind a count would break
 * invariant 3 in the quietest possible way.
 */
export function ActivityGroup({ calls, live = false }: { calls: readonly ToolCall[]; live?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  // Enter once, for a run that starts while the turn is running; a transcript read back whole
  // must not animate its rows at the reader.
  const [animate] = useState(live)
  const { mode, header } = activityLayout({ count: calls.length, live, expanded })

  // A run that still holds a call in flight says what has *finished* — "Searched the web ×2"
  // rather than "×3" — and never prints that call as a row of its own, because a row that
  // disappears the moment the call answers is the contraction this shape exists to avoid
  // (`failures`). Live, the call in flight is the ticker's line instead.
  const running = anyRunning(calls)
  const summary = running ? liveSummary(calls) : summarise(calls)
  const label =
    mode === 'folded'
      ? `${calls.length} steps${summary ? ` · ${summary}` : ''}`
      : summary || `${calls.length} steps`

  const ticking = calls.filter(call => effectiveStatus(call) !== 'error')
  const rows = mode === 'rows' ? calls : failures(calls)

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 border-l-2 border-line pl-3.5',
        animate && 'animate-row-in'
      )}
    >
      {header && (
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm text-ink-3">
          <span>{label}</span>
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded(value => !value)}
            className="text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
          >
            {expanded ? 'hide the steps' : `show all ${calls.length}`}
          </button>
        </p>
      )}

      {mode === 'ticker' && ticking.length > 0 && <ActivityTicker calls={ticking} />}

      {rows.map(call => (
        <ActivityRow key={call.key} call={call} />
      ))}
    </div>
  )
}

/**
 * A one-line window over a live run's calls.
 *
 * Every row is stacked in a reel offset by the newest row's index, so a call arriving slides the
 * one before it up and out of a fixed line box: the run reads as one line ticking over in place
 * rather than a list growing down the page. It is the same idea as Hermes' tool-run ticker, and
 * the CSS is what keeps the offset exact whatever a row contains (`styles.css`, `.activity-ticker`).
 */
function ActivityTicker({ calls }: { calls: readonly ToolCall[] }) {
  return (
    <div className="activity-ticker">
      <div
        className="activity-ticker__reel"
        style={{ '--activity-ticker-index': calls.length - 1 } as CSSProperties}
      >
        {calls.map(call => (
          <div className="activity-ticker__row" key={call.key}>
            <TickerRow call={call} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** One row in the reel: the sentence and a glyph, clipped to the ticker's line box. */
function TickerRow({ call }: { call: ToolCall }) {
  const running = effectiveStatus(call) === 'running'
  const Icon = ICONS[familyOf(call.tool)]

  return (
    <p className="flex min-w-0 items-center gap-2 text-sm">
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {running ? (
          <span aria-hidden className="animate-pulse-dot size-1.5 rounded-full bg-accent" />
        ) : (
          <Icon aria-hidden className="size-3.5 text-ink-disabled" />
        )}
      </span>
      <span className={cn('min-w-0 truncate', running ? 'text-ink-2' : 'text-ink-3')}>
        {activityLine(call)}
      </span>
    </p>
  )
}

function ActivityRow({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false)

  const family = familyOf(call.tool)
  const status = effectiveStatus(call)
  const failed = status === 'error'
  const running = status === 'running'
  const line = activityLine(call)
  const detail = activityDetail(call)
  const label = detailLabel(detail, family)
  const Icon = failed ? TriangleAlert : ICONS[family]

  return (
    <div className="flex flex-col gap-1">
      <p className="flex items-start gap-2 text-sm">
        <span className="mt-1 flex size-3.5 shrink-0 items-center justify-center">
          {running ? (
            <span aria-hidden className="animate-pulse-dot size-1.5 rounded-full bg-accent" />
          ) : (
            <Icon aria-hidden className={cn('size-3.5', failed ? 'text-danger' : 'text-ink-disabled')} />
          )}
        </span>

        <span className={cn(failed ? 'text-danger' : running ? 'text-ink-2' : 'text-ink-3')}>
          {line}
        </span>

        {label && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(value => !value)}
            className="text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
          >
            {open ? 'hide' : label}
          </button>
        )}
      </p>

      {open && <Detail detail={detail} />}
    </div>
  )
}

function Detail({ detail }: { detail: ActivityDetail }) {
  const { open } = usePreview()
  return (
    <div className="ml-[1.375rem] flex flex-col gap-1.5">
      {detail.message && (
        <p className="text-xs whitespace-pre-wrap text-danger">{detail.message}</p>
      )}

      {detail.items.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {detail.items.map((item, index) => (
            <li key={`${item.url ?? item.path ?? item.label}-${index}`} className="text-xs text-ink-3">
              {item.url ? (
                // A source opens the preview sheet, like every other link in the app: a page the
                // assistant read should be readable here, beside what it said about it. A
                // modifier-click still gets the browser's own tab.
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  onClick={event => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                    if (event.button !== 0) return
                    event.preventDefault()
                    // A source URL comes from a tool result, so it is exactly the kind of value
                    // that must not be trusted by the component drawing it: `siteTarget` answers
                    // `null` for anything that is not an http(s) address
                    // (the internal security audit A19-WEB-3).
                    const target = siteTarget(item.url as string)
                    if (target) open(target)
                  }}
                  className="underline underline-offset-2 hover:text-ink-2"
                >
                  {item.label}
                </a>
              ) : item.path ? (
                // A file the call named: a card, because a document is looked at and a source is
                // read (the file-preview design §4 D3).
                <FileCard path={item.path} name={item.label.split(/[\\/]/).pop()} />
              ) : (
                item.label
              )}
              {item.url && <span className="text-ink-disabled"> · {hostOf(item.url)}</span>}
            </li>
          ))}
        </ul>
      )}

      {detail.duration !== undefined && (
        <p className="text-xs text-ink-disabled">took {detail.duration.toFixed(2)}s</p>
      )}
    </div>
  )
}
