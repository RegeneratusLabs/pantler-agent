/**
 * The pieces the first run is built from.
 *
 * A person who has never used an assistant before is the reader here, so the rules are blunt:
 * one question per screen, a control big enough to hit without aiming, the selected thing visibly
 * selected, and never a disabled button without a sentence saying why. Everything is a real
 * `<button>` or a real `<input>` — no clickable `div`s — so the keyboard and a screen reader work
 * the same as a finger.
 */

import { useRef, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { cn } from '../ui/cn'

export function StepFrame({
  eyebrow,
  title,
  lede,
  children
}: {
  eyebrow: string
  title: string
  lede: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-col gap-2">
        <p className="text-display text-xs text-accent">{eyebrow}</p>
        <h1 className="brand-display text-[1.75rem] leading-[1.15] text-ink sm:text-4xl">{title}</h1>
        {lede ? <p className="max-w-prose text-sm leading-relaxed text-ink-2">{lede}</p> : null}
      </header>
      {children}
    </div>
  )
}

/**
 * One big answer. Selected is carried by a border, a tint *and* a tick, because colour alone is not
 * an answer for everyone — and because a tint at 4% is not visible on a laptop in daylight.
 */
/**
 * Which card an arrow key moves to, in the ARIA radiogroup pattern.
 *
 * Pure so it can be tested without a DOM (there is no component runner here — WEB-16): the
 * pattern is roving focus with wraparound, and `null` means "not an arrow key, leave it alone".
 */
export function nextRadioIndex(
  current: number,
  count: number,
  key: string
): number | null {
  if (count <= 0) return null
  const forward = key === 'ArrowDown' || key === 'ArrowRight'
  const backward = key === 'ArrowUp' || key === 'ArrowLeft'
  if (!forward && !backward) return null
  if (current < 0) return forward ? 0 : count - 1
  return (current + (forward ? 1 : -1) + count) % count
}

/**
 * A group of `ChoiceCard`s as a real radiogroup.
 *
 * The cards carried `role="radio"` and the container `role="radiogroup"` with none of the
 * behaviour the pattern requires: no arrow keys and every card in the tab order, which is a
 * promise to a screen-reader user that the keyboard does not keep
 * (the internal audit WEB-17). Arrows move and select; Tab leaves the group; the selected
 * card is the one Tab lands on.
 */
export function ChoiceGroup({
  label,
  children,
  className
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  const group = useRef<HTMLDivElement>(null)
  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label={label}
      className={className}
      onKeyDown={event => {
        const cards: HTMLButtonElement[] = Array.from(
          group.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? []
        ).filter((card: HTMLButtonElement) => !card.disabled)
        const index = cards.indexOf(document.activeElement as HTMLButtonElement)
        const next = nextRadioIndex(index, cards.length, event.key)
        if (next === null) return
        event.preventDefault()
        cards[next]?.focus()
        cards[next]?.click()
      }}
    >
      {children}
    </div>
  )
}

export function ChoiceCard({
  selected,
  onSelect,
  title,
  subtitle,
  children,
  className
}: {
  selected: boolean
  onSelect: () => void
  title: string
  subtitle?: string
  children?: ReactNode
  className?: string
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      // Roving tabindex: the group is one stop, and the arrows move within it.
      tabIndex={selected ? 0 : -1}
      onClick={onSelect}
      className={cn(
        'flex w-full items-start gap-3 rounded-card border p-4 text-left transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        selected
          ? 'border-accent bg-accent/10'
          : 'border-line bg-raised hover:border-line-strong hover:bg-hover',
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
          selected ? 'border-accent bg-accent text-accent-ink' : 'border-line-strong'
        )}
      >
        {selected ? <Check size={13} strokeWidth={3} /> : null}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="text-sm font-medium text-ink">{title}</span>
        {subtitle ? <span className="text-xs leading-relaxed text-ink-3">{subtitle}</span> : null}
        {children}
      </span>
    </button>
  )
}

/** What the voice actually reads like, quoted. Shown beside the choice, never instead of it. */
export function SampleLine({ children }: { children: ReactNode }) {
  return (
    <span className="mt-1 block rounded-lg border border-line bg-canvas/60 px-3 py-2 text-xs leading-relaxed text-ink-2 italic">
      {children}
    </span>
  )
}

/** Progress as dots with a sentence for anyone who cannot see them. */
export function Dots({ index, total }: { index: number; total: number }) {
  return (
    <ol aria-label={`Step ${index} of ${total}`} className="flex items-center gap-1.5">
      {Array.from({ length: total }, (_, position) => (
        <li
          key={position}
          aria-current={position + 1 === index ? 'step' : undefined}
          className={cn(
            'h-1.5 rounded-full transition-all',
            position + 1 === index ? 'w-6 bg-accent' : 'w-1.5 bg-line-strong',
            position + 1 < index && 'bg-accent/50'
          )}
        />
      ))}
    </ol>
  )
}

/** A line in the closing summary: what we heard, and where to change it. */
export function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-2.5 last:border-b-0">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="text-right text-sm text-ink">{value || <span className="text-ink-3">not said</span>}</dd>
    </div>
  )
}
