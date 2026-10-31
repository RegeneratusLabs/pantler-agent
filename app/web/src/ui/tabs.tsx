import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from './cn'

export interface TabItem {
  id: string
  label: ReactNode
}

/**
 * A small tab bar with the ARIA pattern the page actually needs.
 *
 * The Capabilities page had grown into one long scroll; tabs are the honest way to keep each
 * question — what the assistant knows, what it can reach, and the engine's own toolsets —
 * separate without hiding any of them. This is hand-rolled (no dependency) and follows the
 * pattern: one `tablist`, one selected `tab`, roving `tabIndex`, and Left/Right/Home/End moving
 * the selection and the focus together.
 *
 * The caller owns the panel and gives it `id="panel-<id>"`, `role="tabpanel"` and
 * `aria-labelledby="tab-<id>"`. Panels should stay mounted and hidden when inactive, so a
 * pending sign-in link or a typed value survives a tab switch.
 */
export function Tabs({
  items,
  value,
  onChange,
  label
}: {
  items: readonly TabItem[]
  value: string
  onChange: (id: string) => void
  label: string
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null
    if (event.key === 'ArrowRight') next = (index + 1) % items.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    if (next === null) return
    event.preventDefault()
    const item = items[next]
    if (!item) return
    onChange(item.id)
    refs.current[next]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      aria-orientation="horizontal"
      className="inline-flex w-full max-w-full flex-wrap gap-1 rounded-lg border border-line bg-surface/40 p-1 sm:w-auto"
    >
      {items.map((item, index) => {
        const selected = item.id === value
        return (
          <button
            key={item.id}
            ref={element => {
              refs.current[index] = element
            }}
            type="button"
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={event => move(event, index)}
            className={cn(
              'min-w-0 flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors sm:flex-none',
              selected ? 'bg-accent/10 text-accent' : 'text-ink-3 hover:bg-hover hover:text-ink'
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
