import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from './cn'

const badge = cva(
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.72rem] ' +
    'leading-5 whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'border-line text-ink-3',
        ok: 'border-success/45 text-success',
        warn: 'border-warning/45 text-warning',
        danger: 'border-danger/50 text-danger',
        accent: 'border-accent/45 text-accent'
      }
    },
    defaultVariants: { tone: 'neutral' }
  }
)

export type BadgeProps = ComponentProps<'span'> & VariantProps<typeof badge>

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />
}
