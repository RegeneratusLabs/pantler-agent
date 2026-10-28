import { cn } from './cn'

/**
 * Switch — a binary control for something that is genuinely on or off.
 *
 * It is a `<button role="switch">` rather than a styled checkbox so the label stays ours
 * and the state is announced correctly. The caller owns the state; this only reports the
 * requested change, which is what lets a save failure leave the switch where it was.
 */
export function Switch({
  checked,
  disabled,
  onCheckedChange,
  label,
  className
}: {
  checked: boolean
  disabled?: boolean
  onCheckedChange: (next: boolean) => void
  /** Accessible name, for when there is no visible <label> pointing at this control. */
  label: string
  className?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        'disabled:pointer-events-none disabled:opacity-45',
        checked ? 'border-accent/60 bg-accent/80' : 'border-line-strong bg-canvas',
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          'block size-3.5 rounded-full transition-transform',
          checked ? 'translate-x-[1.15rem] bg-accent-ink' : 'translate-x-[0.15rem] bg-ink-3'
        )}
      />
    </button>
  )
}
