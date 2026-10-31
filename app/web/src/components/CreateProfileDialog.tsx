import { useState, type FormEvent } from 'react'
import { slugifyProfileName, validateProfileName } from '../pages/profiles'
import { Button } from '../ui/button'
import { Dialog } from '../ui/dialog'
import { Field, Input, Textarea } from '../ui/field'

/** What the form sends: the server copies the installed product unless another source is named. */
export interface NewProfile {
  name: string
  display_name?: string
  description?: string
}

/**
 * The new-profile form, shared by the Profiles screen and the rail's profile dropdown.
 *
 * A profile is always copied from the installed product — its skills, plugins, packs and price
 * book — so there is no source to choose here. The id follows the display name until the
 * operator edits it; after that it is theirs, and a later rename of the display name must not
 * silently rewrite it.
 */
export function CreateProfileDialog({
  open,
  onClose,
  onCreate,
  busy,
  error
}: {
  open: boolean
  onClose: () => void
  onCreate: (input: NewProfile) => Promise<void>
  busy: boolean
  error: string | null
}) {
  const [displayName, setDisplayName] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  // A fresh form each time it opens. The component stays mounted while the dialog is closed,
  // so without this the id from the last business would be submitted again — a 409 the
  // operator never asked for. Adjusting state during render is the pattern the edit dialog
  // uses for the same reason.
  const [wasOpen, setWasOpen] = useState(false)
  if (open && !wasOpen) {
    setWasOpen(true)
    setDisplayName('')
    setName('')
    setDescription('')
    setNameTouched(false)
    setLocalError(null)
  } else if (!open && wasOpen) {
    setWasOpen(false)
  }

  const effectiveName = nameTouched ? name : slugifyProfileName(displayName)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const problem = validateProfileName(effectiveName)
    if (problem) {
      setLocalError(problem)
      return
    }
    setLocalError(null)
    void onCreate({
      name: effectiveName,
      display_name: displayName.trim() || undefined,
      description: description.trim() || undefined
    })
  }

  return (
    <Dialog
      open={open}
      title="New profile"
      description="A business of its own: separate records, conversations and learning, on this machine."
      error={localError ?? error}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {busy ? 'Creating…' : 'Create profile'}
          </Button>
        </>
      }
    >
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <Field label="What is this business called?" hint="Shown in the rail and on this screen.">
          <Input
            value={displayName}
            onChange={event => setDisplayName(event.target.value)}
            placeholder="Bellview Farm"
            autoFocus
          />
        </Field>
        <Field
          label="Profile id"
          hint="Lowercase letters, numbers, “-” or “_”. It names the directory and cannot contain spaces."
        >
          <Input
            value={effectiveName}
            onChange={event => {
              setNameTouched(true)
              setName(event.target.value)
            }}
            placeholder="bellview"
            className="font-mono"
            spellCheck={false}
          />
        </Field>
        <Field label="What is it for?" hint="Optional. A sentence the others can be told apart by.">
          <Textarea
            value={description}
            onChange={event => setDescription(event.target.value)}
            placeholder="The market garden and its wholesale customers."
            rows={2}
          />
        </Field>
      </form>
    </Dialog>
  )
}
