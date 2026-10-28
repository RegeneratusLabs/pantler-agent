import type { ReactNode } from 'react'
import { cn } from './cn'

/** The "nothing here yet" state — one sentence and one action, never a wall. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  className
}: {
  icon?: ReactNode
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'mx-auto flex max-w-md flex-col items-center gap-3 py-14 text-center',
        className
      )}
    >
      {icon && <div className="text-ink-disabled">{icon}</div>}
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {children && <p className="text-sm text-ink-2">{children}</p>}
      {action}
    </div>
  )
}
