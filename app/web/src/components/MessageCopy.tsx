import { Check, Copy, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'

type CopyState = 'idle' | 'copied' | 'failed'

/**
 * Copy one message's readable text.
 *
 * The clipboard API is the happy path; it needs a secure context, and the app is also reached over
 * plain HTTP on the tailnet. So a refused or missing `navigator.clipboard` falls back to the old
 * textarea + `execCommand` route. If both fail, the button says so rather than showing a checkmark
 * for a copy that did not happen — the same honesty rule the rest of the app keeps.
 *
 * The confirmation timer is cleared on unmount: a step change or a transcript refetch replaces the
 * turn, and a `setState` firing into a gone component was a real defect before
 * (the internal audit WEB-17).
 */
export function MessageCopy({
  text,
  label,
  className
}: {
  text: string
  /** The accessible name, e.g. "Copy answer". The visible word stays short. */
  label: string
  className?: string
}) {
  const [state, setState] = useState<CopyState>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const message = text.trim()
  if (!message) return null

  const finish = (next: CopyState, delay: number) => {
    setState(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), delay)
  }

  const copy = async () => {
    const ok = await writeClipboard(message)
    finish(ok ? 'copied' : 'failed', ok ? 2000 : 4000)
  }

  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn(
          'h-7 gap-1 px-2 text-[0.65rem] text-ink-3',
          state === 'failed' && 'text-danger'
        )}
        aria-label={label}
        title={
          state === 'failed'
            ? 'The browser refused the clipboard — select the text and copy it'
            : label
        }
        onClick={() => void copy()}
      >
        {state === 'copied' ? (
          <Check className="size-3" aria-hidden />
        ) : state === 'failed' ? (
          <TriangleAlert className="size-3" aria-hidden />
        ) : (
          <Copy className="size-3" aria-hidden />
        )}
        {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy'}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'copied' ? 'Copied to the clipboard' : state === 'failed' ? 'Copy failed' : ''}
      </span>
    </span>
  )
}

/** Clipboard write with the plain-HTTP fallback. True only when something was actually copied. */
async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Permission denied or an insecure origin: try the older route below.
  }

  try {
    if (typeof document.execCommand !== 'function') return false
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const copied = document.execCommand('copy')
    document.body.removeChild(area)
    return copied
  } catch {
    return false
  }
}
