import { Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { CreateProfileDialog, type NewProfile } from '../components/CreateProfileDialog'
import { profileLabel } from '../pages/profiles'
import { useProfiles } from '../state/profile-context'
import { Select } from '../ui/field'

/**
 * The sentinel the dropdown uses for its create action. No profile can be named this:
 * `PROFILE_NAME_RE` refuses a leading “_”, so the value can never collide with a business.
 */
const NEW_PROFILE = '__new__'

/**
 * Which business the rail is showing, and how to start another one.
 *
 * A profile is not a filter over one set of conversations — it is a different set, a different
 * record store and a different assistant. The selection therefore goes through the server (the
 * engine's own ``active_profile``) rather than living in a browser tab, and a change starts a
 * fresh conversation because the one on screen had a different owner.
 *
 * The create action lives here because the dropdown is where a business is chosen: making one
 * is the other half of that choice. On success the app switches to it, unless the engine is
 * serving one profile at a time — then the card is real on disk and unusable until a restart,
 * and the rail says so instead of dropping the operator into a dead conversation.
 */
export function ProfileSwitcher({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate()
  const { profiles, active, available, activate, create } = useProfiles()
  const [choice, setChoice] = useState(active ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Keep the control on the profile the app is actually using — after a switch, and after a
  // create closed the dialog with the sentinel still selected in the DOM.
  useEffect(() => {
    setChoice(active ?? '')
  }, [active])

  if (!available || profiles.length === 0) return null

  const switchTo = async (name: string) => {
    if (!name || name === active) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await activate(name)
      navigate('/chat')
      onNavigate?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const openCreate = () => {
    setCreateError(null)
    setNotice(null)
    setCreateOpen(true)
  }

  const createAndUse = async (input: NewProfile) => {
    setCreating(true)
    setCreateError(null)
    setNotice(null)
    try {
      const written = await create(input)
      // The profile exists from here on. Close the form first: a retry after a failed switch
      // would answer 409 for a business that was in fact created.
      setCreateOpen(false)
      const label = input.display_name?.trim() || input.name
      if (written.restart_required) {
        setNotice(
          `“${label}” was created, but the engine is serving one business at a time. ` +
            'Restart the engine before working in it.'
        )
        return
      }
      try {
        await activate(written.profile.name)
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught)
        setError(`“${label}” was created, but it could not be selected: ${message}`)
        return
      }
      if (written.profile.served === false) {
        setNotice(
          `The engine is starting “${label}”. A new business is picked up within about ` +
            'half a minute.'
        )
      }
      navigate('/chat')
      onNavigate?.()
    } catch (caught) {
      setCreateError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 px-3 pb-3">
      <label className="flex items-center gap-1.5 text-[0.68rem] text-ink-3">
        <Users className="size-3" aria-hidden />
        <span className="text-display">Profile</span>
      </label>
      <Select
        aria-label="Profile"
        value={choice}
        disabled={busy || creating}
        onChange={event => {
          const value = event.target.value
          if (value === NEW_PROFILE) {
            setChoice(active ?? '')
            openCreate()
            return
          }
          setChoice(value)
          void switchTo(value)
        }}
        className="h-8 text-xs"
      >
        {active === null && <option value="">…</option>}
        {profiles.map(profile => (
          <option key={profile.name} value={profile.name}>
            {profileLabel(profile)}
          </option>
        ))}
        <option value={NEW_PROFILE}>New profile…</option>
      </Select>
      {error && <p className="text-[0.68rem] text-danger">{error}</p>}
      {notice && <p className="text-[0.68rem] text-warning">{notice}</p>}
      <CreateProfileDialog
        open={createOpen}
        busy={creating}
        error={createError}
        onClose={() => {
          if (!creating) setCreateOpen(false)
        }}
        onCreate={createAndUse}
      />
    </div>
  )
}
