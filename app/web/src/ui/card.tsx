import type { ComponentProps, ReactNode } from 'react'
import { cn } from './cn'

export function Card({ className, ...props }: ComponentProps<'section'>) {
  return (
    <section
      className={cn('flex flex-col gap-2.5 rounded-card border border-line bg-raised p-3.5', className)}
      {...props}
    />
  )
}

/**
 * A card's header. `display` styles the title as brand chrome (uppercase with
 * tracking) — use it for our own labels, never for user or model content.
 */
export function CardHeader({
  title,
  aside,
  display,
  className
}: {
  title: ReactNode
  aside?: ReactNode
  display?: boolean
  className?: string
}) {
  return (
    <header className={cn('flex items-center gap-2.5', className)}>
      <h3
        className={cn(
          'min-w-0 flex-1 truncate font-semibold',
          display ? 'text-display text-xs text-ink-3' : 'text-sm text-ink'
        )}
      >
        {title}
      </h3>
      {aside}
    </header>
  )
}
