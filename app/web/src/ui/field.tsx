import type { ComponentProps, ReactNode } from 'react'
import { cn } from './cn'

const control =
  'w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink ' +
  'placeholder:text-ink-disabled transition-colors hover:border-line-strong ' +
  'focus:border-accent focus:outline-none disabled:opacity-50'

export function Input({ className, ...props }: ComponentProps<'input'>) {
  return <input className={cn(control, 'h-9 py-0', className)} {...props} />
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea className={cn(control, 'resize-none', className)} {...props} />
}

export function Select({ className, ...props }: ComponentProps<'select'>) {
  return <select className={cn(control, 'h-9 py-0', className)} {...props} />
}

/** A labelled control with an optional hint underneath. */
export function Field({
  label,
  hint,
  children,
  className
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      <span className="text-display text-xs text-ink-3">{label}</span>
      {children}
      {hint && <span className="text-xs leading-relaxed text-ink-3">{hint}</span>}
    </label>
  )
}
