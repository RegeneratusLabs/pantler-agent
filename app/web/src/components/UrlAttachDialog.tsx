import { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/button'
import { Dialog } from '../ui/dialog'
import { Field, Input } from '../ui/field'
import { Spinner } from '../ui/spinner'

/**
 * Attach a URL.
 *
 * The BFF fetches the page once, now, and keeps what it answered — rather than passing the
 * link through for the agent to fetch at send time. That is a deliberate difference from the
 * reference: what the operator attached is what the assistant reads, a page that changes
 * afterwards cannot silently rewrite yesterday's answer, and the chip can show the page's own
 * title instead of a URL.
 *
 * The cost is that attaching is slower than typing, so the dialog says what it is doing.
 */
export function UrlAttachDialog({
  open,
  onClose,
  onAttach
}: {
  open: boolean
  onClose: () => void
  onAttach: (url: string) => Promise<void>
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    setValue('')
    setError(undefined)
    const frame = requestAnimationFrame(() => input.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [open])

  const valid = /^https?:\/\/\S+$/i.test(value.trim())

  const submit = async () => {
    const url = value.trim()
    if (!valid || busy) return
    setBusy(true)
    setError(undefined)
    try {
      await onAttach(url)
      onClose()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'That address could not be read')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      title="Attach a URL"
      description="The page is fetched once, now, and its text is kept with the turn."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!valid || busy}>
            {busy ? 'Fetching…' : 'Attach'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={event => {
          event.preventDefault()
          void submit()
        }}
      >
        <Field
          label="Address"
          hint={
            error ? (
              <span className="text-danger">{error}</span>
            ) : value.length > 0 && !valid ? (
              'Include the full address, e.g. https://example.com/price-list'
            ) : (
              'A page on the open internet. Pages behind a login need the browser instead.'
            )
          }
        >
          <Input
            ref={input}
            value={value}
            inputMode="url"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder="https://example.com/price-list"
            disabled={busy}
            onChange={event => setValue(event.target.value)}
          />
        </Field>
        {busy && (
          <div className="pt-2">
            <Spinner label="Fetching the page…" />
          </div>
        )}
      </form>
    </Dialog>
  )
}
