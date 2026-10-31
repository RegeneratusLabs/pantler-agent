import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from './cn'

/**
 * Button — hand-rolled rather than pulled from a design-system package
 * (the front-end design §5 decided shadcn/ui *style*; §1 decided we own the
 * code). Variants are named for intent, not colour, so the theme can move.
 */
const button = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium ' +
    'transition-colors select-none disabled:pointer-events-none disabled:opacity-45 ' +
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-accent-ink hover:brightness-110',
        secondary: 'border border-line-strong bg-raised text-ink hover:bg-hover',
        quiet: 'border border-line bg-transparent text-ink hover:bg-hover',
        ghost: 'bg-transparent text-ink-2 hover:bg-hover hover:text-ink',
        danger: 'border border-danger/50 bg-transparent text-danger hover:bg-danger/10',
        link: 'h-auto bg-transparent p-0 text-accent underline underline-offset-2 hover:brightness-110'
      },
      size: {
        sm: 'h-7 px-2.5 text-xs',
        md: 'h-9 px-3.5 text-sm',
        lg: 'h-11 px-5 text-base',
        icon: 'h-8 w-8 p-0'
      }
    },
    defaultVariants: { variant: 'secondary', size: 'md' }
  }
)

export type ButtonProps = ComponentProps<'button'> & VariantProps<typeof button>

export function Button({ className, variant, size, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={cn(button({ variant, size }), className)} {...props} />
}

export { button as buttonVariants }
