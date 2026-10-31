import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Button } from './button'
import { cn } from './cn'

/**
 * A modal, built on <dialog> so the browser owns focus-trapping, the backdrop
 * and Escape. Nothing is hand-rolled that the platform already does correctly.
 *
 * `error` is where a refusal goes. A dialog whose confirm button sends something is a
 * dialog that can be told no, and a "no" with nowhere to appear reads as a dead button:
 * the modal sits there, unchanged, and the operator clicks again.
 */
export function Dialog({
  open,
  title,
  description,
  error,
  onClose,
  children,
  footer,
  className
}: {
  open: boolean
  title: ReactNode
  description?: ReactNode
  error?: ReactNode
  onClose: () => void
  children?: ReactNode
  footer?: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  // A native `<dialog>` does not take its name from a heading inside it, so a screen reader
  // announced an unnamed dialog (the internal audit WEB-17).
  const headingId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (dialog && open && !dialog.open) dialog.showModal()
  }, [open])

  if (typeof document === 'undefined' || !open) return null

  return createPortal(
    <dialog
      ref={ref}
      // Fires for Escape. Unmounting takes the dialog out of the top layer with it, so
      // there is no separate close path to keep in sync.
      aria-labelledby={headingId}
      aria-describedby={description ? descriptionId : undefined}
      onClose={onClose}
      onClick={event => {
        // A click whose target is the dialog itself is a backdrop click.
        if (event.target === ref.current) onClose()
      }}
      className={cn(
        'm-auto w-[min(30rem,calc(100vw-2rem))] rounded-card border border-line ' +
          'bg-overlay p-0 text-ink backdrop:bg-black/55 backdrop:backdrop-blur-sm',
        className
      )}
    >
      <div className="flex flex-col gap-3 p-5">
        <div className="flex flex-col gap-1">
          <h2 id={headingId} className="text-display text-sm text-ink">{title}</h2>
          {description && (
            <p id={descriptionId} className="text-sm text-ink-2">
              {description}
            </p>
          )}
        </div>
        {children}
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger"
          >
            {error}
          </p>
        )}
        {footer && <div className="flex justify-end gap-2 pt-1">{footer}</div>}
      </div>
    </dialog>,
    document.body
  )
}

/** The common case: a sentence, a confirm and a cancel. */
export function ConfirmDialog({
  open,
  title,
  description,
  error,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive,
  busy,
  onConfirm,
  onCancel
}: {
  open: boolean
  title: ReactNode
  description?: ReactNode
  error?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Dialog
      open={open}
      title={title}
      description={description}
      error={error}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </Button>
        </>
      }
    />
  )
}
