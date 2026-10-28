import { Check, Pencil, Plus, Trash2, Users } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { CreateProfileDialog } from '../components/CreateProfileDialog'
import type { ProfileSummary } from '../seam/bff'
import { useProfiles } from '../state/profile-context'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardHeader } from '../ui/card'
import { ConfirmDialog, Dialog } from '../ui/dialog'
import { Field, Input, Textarea } from '../ui/field'
import {
  gatewayNotice,
  profileLabel,
  profileMeta,
  profileState,
  profileStateSentence,
  sortProfiles,
  validateProfileName
} from './profiles'

/**
 * Profiles — the businesses this installation holds.
 *
 * A profile is an engine profile: its own records, conversations, skills, credentials and
 * learning. This screen is where one is created from the installed payload, renamed, selected
 * and removed. It does not edit the assistant's settings — those belong to the selected
 * profile and live under Settings and Capabilities, which is what makes switching meaningful.
 */
export function ProfilesPage() {
  const {
    profiles,
    active,
    available,
    reason,
    gateway,
    restartRequired,
    loading,
    error,
    activate,
    create,
    update,
    remove
  } = useProfiles()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<ProfileSummary | null>(null)
  const [deleting, setDeleting] = useState<ProfileSummary | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [pageError, setPageError] = useState<string | null>(null)

  const listed = useMemo(() => sortProfiles(profiles), [profiles])
  const notice = gatewayNotice(profiles, gateway, restartRequired)

  async function select(profile: ProfileSummary) {
    setPageError(null)
    setBusy(profile.name)
    try {
      if (!profile.active) await activate(profile.name)
      // A conversation belongs to a profile: the one open was named under the old scope.
      navigate('/chat')
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    setPageError(null)
    setBusy(deleting.name)
    try {
      await remove(deleting.name)
      setDeleting(null)
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6">
        <header className="flex items-start gap-3">
          <span aria-hidden className="mt-0.5 text-ink-3">
            <Users className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-display text-sm text-ink">Profiles</h2>
            <p className="text-xs text-ink-3">
              One per business. Each keeps its own records, conversations, skills and
              credentials; the assistant in one profile knows nothing about the others.
            </p>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setPageError(null)
              setCreateOpen(true)
            }}
            disabled={!available}
          >
            <Plus className="size-4" />
            New profile
          </Button>
        </header>

        {!loading && !available && (
          <Card className="border-warning/40 bg-warning/5">
            <p className="text-sm text-ink-2">
              Profiles are not available on this server.
            </p>
            <p className="text-xs text-ink-3">{reason || error || 'No engine profile is configured.'}</p>
            <p className="text-xs text-ink-3">
              Start the BFF with <code>--profile-dir &lt;…/profiles/NAME&gt;</code> so it knows
              the installation it belongs to.
            </p>
          </Card>
        )}

        {notice && (
          <p className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
            {notice}
          </p>
        )}

        {pageError && (
          <p
            role="alert"
            className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger"
          >
            {pageError}
          </p>
        )}

        {loading && profiles.length === 0 && (
          <p className="text-sm text-ink-3">Reading the profiles…</p>
        )}

        {!loading && available && listed.length === 0 && (
          <Card>
            <p className="text-sm text-ink-2">No profiles yet.</p>
            <p className="text-xs text-ink-3">Create one to give a business its own assistant.</p>
          </Card>
        )}

        <ul className="flex flex-col gap-3">
          {listed.map(profile => {
            const state = profileState(profile, gateway)
            return (
              <li key={profile.name}>
                <Card className={profile.active ? 'border-accent/50' : undefined}>
                  <CardHeader
                    title={profileLabel(profile)}
                    aside={
                      <div className="flex items-center gap-1.5">
                        {profile.is_install && <Badge tone="neutral">installed</Badge>}
                        {profile.active ? (
                          <Badge tone="accent">selected</Badge>
                        ) : state === 'restart' ? (
                          <Badge tone="warn">engine restart</Badge>
                        ) : state === 'pending' ? (
                          <Badge tone="neutral">starting</Badge>
                        ) : state === 'ready' ? (
                          <Badge tone="ok">ready</Badge>
                        ) : (
                          <Badge tone="neutral">available</Badge>
                        )}
                      </div>
                    }
                  />
                  <p className="font-mono text-[0.7rem] text-ink-3">{profileMeta(profile) || profile.name}</p>
                  {profile.description && (
                    <p className="text-sm text-ink-2">{profile.description}</p>
                  )}
                  <p className="text-xs text-ink-3">
                    {profileStateSentence(state)}
                  </p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      size="sm"
                      variant={profile.active ? 'secondary' : 'quiet'}
                      onClick={() => void select(profile)}
                      disabled={busy !== null || profile.active}
                    >
                      {profile.active ? <Check className="size-4" /> : null}
                      {profile.active ? 'In use' : 'Use this profile'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setPageError(null)
                        setEditing(profile)
                      }}
                      disabled={busy !== null}
                    >
                      <Pencil className="size-4" />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-danger hover:bg-danger/10"
                      onClick={() => {
                        setPageError(null)
                        setDeleting(profile)
                      }}
                      disabled={busy !== null || profile.is_install || profile.active || profile.name === active}
                      title={
                        profile.is_install
                          ? 'The installed profile cannot be deleted.'
                          : profile.active
                            ? 'Switch to another profile before deleting this one.'
                            : undefined
                      }
                    >
                      <Trash2 className="size-4" />
                      Delete
                    </Button>
                  </div>
                </Card>
              </li>
            )
          })}
        </ul>

        <p className="text-xs leading-relaxed text-ink-disabled">
          A new profile is copied from the installed product: its skills, plugins, packs and
          price book, with no conversations, memories or records from the profile it was modelled
          on. Its records live inside its own profile directory, so deleting the profile removes
          the business with it — which is why the dialog asks twice.
        </p>
      </div>

      <CreateProfileDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={async input => {
          setBusy('create')
          setPageError(null)
          try {
            await create(input)
            setCreateOpen(false)
          } catch (caught) {
            setPageError(caught instanceof Error ? caught.message : String(caught))
          } finally {
            setBusy(null)
          }
        }}
        busy={busy === 'create'}
        error={pageError}
      />

      <EditProfileDialog
        profile={editing}
        onClose={() => setEditing(null)}
        onSave={async (name, patch) => {
          setBusy(name)
          setPageError(null)
          try {
            await update(name, patch)
            setEditing(null)
          } catch (caught) {
            setPageError(caught instanceof Error ? caught.message : String(caught))
          } finally {
            setBusy(null)
          }
        }}
        busy={editing ? busy === editing.name : false}
        error={pageError}
      />

      <ConfirmDialog
        open={deleting !== null}
        destructive
        title={deleting ? `Delete “${profileLabel(deleting)}”?` : 'Delete this profile?'}
        description={
          deleting
            ? `This removes ${deleting.name}'s records, conversations, skills, memories and attachments from this machine. It cannot be undone.`
            : undefined
        }
        confirmLabel="Delete profile"
        error={pageError}
        busy={deleting !== null && busy === deleting.name}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleting(null)}
      />
    </div>
  )
}

function EditProfileDialog({
  profile,
  onClose,
  onSave,
  busy,
  error
}: {
  profile: ProfileSummary | null
  onClose: () => void
  onSave: (
    name: string,
    patch: { new_name?: string; display_name?: string; description?: string }
  ) => Promise<void>
  busy: boolean
  error: string | null
}) {
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [newName, setNewName] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  // Reset the form when a different profile opens. Rendering the dialog for a different card
  // reuses this component, and stale input from the last one would be written to the wrong file.
  const [openedFor, setOpenedFor] = useState<string | null>(null)
  if (profile && openedFor !== profile.name) {
    setOpenedFor(profile.name)
    setDisplayName(profile.display_name)
    setDescription(profile.description)
    setNewName(profile.name)
    setLocalError(null)
  }

  if (!profile) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const renamed = newName.trim() !== profile.name
    if (renamed) {
      const problem = validateProfileName(newName)
      if (problem) {
        setLocalError(problem)
        return
      }
    }
    setLocalError(null)
    void onSave(profile.name, {
      ...(renamed ? { new_name: newName.trim().toLowerCase() } : {}),
      display_name: displayName.trim(),
      description: description.trim()
    })
  }

  return (
    <Dialog
      open
      title={`Edit “${profileLabel(profile)}”`}
      description={
        profile.is_install
          ? 'The installed profile’s display name and description can be changed; its id is part of this server’s setup.'
          : 'Changing the id renames the directory and updates the paths inside its config.'
      }
      error={localError ?? error}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
        </>
      }
    >
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <Field label="Display name">
          <Input
            value={displayName}
            onChange={event => setDisplayName(event.target.value)}
            placeholder={profile.name}
            autoFocus
          />
        </Field>
        <Field
          label="Profile id"
          hint={profile.is_install ? 'The installed profile keeps its id.' : 'The directory name.'}
        >
          <Input
            value={profile.is_install ? profile.name : newName}
            onChange={event => setNewName(event.target.value)}
            disabled={profile.is_install}
            className="font-mono"
            spellCheck={false}
          />
        </Field>
        <Field label="What is it for?">
          <Textarea
            value={description}
            onChange={event => setDescription(event.target.value)}
            rows={3}
          />
        </Field>
      </form>
    </Dialog>
  )
}
