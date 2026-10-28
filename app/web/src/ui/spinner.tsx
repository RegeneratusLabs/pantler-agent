import { cn } from './cn'

/** An indeterminate busy mark. `label` is announced, and printed beside it. */
export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-ink-3" role="status" aria-live="polite">
      <span
        aria-hidden
        className={cn(
          'size-3.5 shrink-0 animate-spin rounded-full border-2 border-line-strong',
          'border-t-accent',
          className
        )}
      />
      {label && <span className="text-xs">{label}</span>}
    </span>
  )
}
