/**
 * The one form that connects a model, in the first run and in Settings.
 *
 * It writes exactly two files through the BFF: the key to the profile's `.env` and the `model:`
 * block to its `config.yaml`. The key is never read back — the form only ever learns `is_set` —
 * and the page says where it went.
 *
 * **Why the restart is here.** The engine loads `.env` when the gateway starts
 * (`gateway/run.py`), so a saved key is inert until the engine restarts. In the desktop app the
 * host can do that (`window.pantler.restartEngine`, the supervisor's own stop/start); in the
 * browser build there is no host, so the form says so rather than pretending the model is live.
 */

import { useId, useState } from 'react'
import { Check, KeyRound, Loader2 } from 'lucide-react'
import type { EngineSettings } from '@shared/wire'
import type { BffClient } from '../seam/bff'
import { Button } from '../ui/button'
import { Field, Input, Select } from '../ui/field'
import { PROVIDERS, modelProblem, modelValues, providerById, type ModelProvider } from './providers'

export interface ModelFormProps {
  settings: EngineSettings
  bff: Pick<BffClient, 'saveModel' | 'saveKey' | 'clearKey'>
  /** Called after the files are written, before the restart, so the page can refetch. */
  onSaved?: () => void
  /** Called when the form has done all it can — the onboarding step advances on it. */
  onConnected?: () => void
  /** The first run has less room; Settings has a section header above it. */
  compact?: boolean
}

type Status = 'connected' | 'restart' | 'removed' | null

/** The provider the form opens on: the saved one when we know it, otherwise DeepSeek. */
function openingProvider(settings: EngineSettings): ModelProvider {
  return providerById(settings.model?.provider ?? '') ?? PROVIDERS[0]
}

export function ModelForm({ settings, bff, onSaved, onConnected, compact = false }: ModelFormProps) {
  const listId = useId()
  const opening = openingProvider(settings)
  const savedIsKnown = opening.id === (settings.model?.provider ?? '')

  const [providerId, setProviderId] = useState(opening.id)
  const [model, setModel] = useState(() =>
    savedIsKnown ? settings.model?.default || opening.defaultModel : opening.defaultModel
  )
  const [baseUrl, setBaseUrl] = useState(() =>
    opening.custom ? settings.model?.base_url || '' : opening.baseUrl
  )
  const [keyEnv, setKeyEnv] = useState(() =>
    savedIsKnown ? settings.model?.key_env || opening.keyEnv : opening.keyEnv
  )
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'saving' | 'restarting' | null>(null)
  const [status, setStatus] = useState<Status>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const provider = providerById(providerId) ?? PROVIDERS[0]
  const info = settings.keys?.find(entry => entry.name === keyEnv.trim())
  const keySet = info?.is_set === true
  const current = settings.model ?? {}

  function choose(nextId: string) {
    const next = providerById(nextId)
    if (!next) return
    setProviderId(next.id)
    setModel(next.defaultModel)
    setBaseUrl(next.baseUrl)
    setKeyEnv(next.keyEnv)
    setKey('')
    setError(null)
    setStatus(null)
    setConfirmRemove(false)
  }

  async function connect() {
    const choice = { provider, model, keyEnv, baseUrl }
    const problem = modelProblem(choice)
    if (problem) {
      setError(problem)
      return
    }
    if (!key.trim() && !keySet) {
      setError('Paste the API key for this provider.')
      return
    }

    setBusy('saving')
    setError(null)
    setStatus(null)
    try {
      if (key.trim()) await bff.saveKey(keyEnv.trim(), key.trim())
      await bff.saveModel(modelValues(choice))
      setKey('')
      onSaved?.()

      const restart = window.pantler?.restartEngine
      if (!restart) {
        // A browser has no host to restart: the files are written, and the copy says why that is
        // not the same as connected.
        setStatus('restart')
        onConnected?.()
        return
      }

      setBusy('restarting')
      const result = await restart()
      if (!result?.ok) throw new Error(result?.error || 'The engine did not restart.')
      setStatus('connected')
      onConnected?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the model.')
    } finally {
      setBusy(null)
    }
  }

  async function removeKey() {
    setBusy('saving')
    setError(null)
    try {
      await bff.clearKey(keyEnv.trim())
      setConfirmRemove(false)
      setStatus('removed')
      onSaved?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove the key.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {!savedIsKnown && current.default && (
        <p className="rounded-card border border-line bg-canvas px-3 py-2.5 text-xs text-ink-3">
          This install is on{' '}
          <strong className="font-medium text-ink-2">
            {current.provider || 'a provider'} / {current.default}
          </strong>
          . Choosing one below replaces that selection.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Provider" hint="Where the key comes from.">
          <Select value={providerId} onChange={event => choose(event.target.value)}>
            {PROVIDERS.map(entry => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="Model"
          hint={
            provider.models.length
              ? 'The provider’s model id. The suggested one is a safe default.'
              : 'The model id the endpoint expects.'
          }
        >
          <Input
            value={model}
            list={listId}
            autoComplete="off"
            spellCheck={false}
            placeholder={provider.custom ? 'your-model-id' : provider.defaultModel}
            onChange={event => setModel(event.target.value)}
          />
          <datalist id={listId}>
            {provider.models.map(choice => (
              <option key={choice} value={choice} />
            ))}
          </datalist>
        </Field>
      </div>

      <p className="text-xs leading-relaxed text-ink-3">{provider.blurb}</p>

      {provider.custom && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Base URL"
            hint="The OpenAI-compatible endpoint, usually ending in /v1."
            className="sm:col-span-2"
          >
            <Input
              value={baseUrl}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://api.example.com/v1"
              onChange={event => setBaseUrl(event.target.value)}
            />
          </Field>
          <Field
            label="Key name"
            hint="The environment variable the key is stored as. Keep the provider’s name for it."
          >
            <Input
              value={keyEnv}
              autoComplete="off"
              spellCheck={false}
              placeholder="CUSTOM_API_KEY"
              onChange={event => setKeyEnv(event.target.value)}
            />
          </Field>
        </div>
      )}

      <Field
        label={keySet ? `API key — set` : 'API key'}
        hint={
          keySet
            ? `A key is already stored for ${keyEnv}. Leave this blank to keep it.`
            : `Stored in this profile’s .env as ${keyEnv || 'KEY_NAME'} and never shown again.`
        }
      >
        <Input
          type="password"
          value={key}
          autoComplete="off"
          spellCheck={false}
          placeholder={keySet ? '••••••••  leave blank to keep the saved key' : 'paste the key'}
          onChange={event => setKey(event.target.value)}
        />
      </Field>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => void connect()} disabled={busy !== null}>
          {busy === 'restarting' ? (
            <>
              <Loader2 aria-hidden className="size-4 animate-spin" />
              Restarting the engine…
            </>
          ) : busy === 'saving' ? (
            'Saving…'
          ) : (
            'Connect'
          )}
        </Button>

        {keySet && !confirmRemove && (
          <Button variant="ghost" onClick={() => setConfirmRemove(true)} disabled={busy !== null}>
            Remove key
          </Button>
        )}
        {confirmRemove && (
          <>
            <Button variant="danger" onClick={() => void removeKey()} disabled={busy !== null}>
              Remove {keyEnv}
            </Button>
            <Button variant="ghost" onClick={() => setConfirmRemove(false)} disabled={busy !== null}>
              Cancel
            </Button>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-card border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      {status === 'connected' && (
        <p role="status" className="flex items-start gap-2 rounded-card border border-ok/40 bg-ok/10 px-3 py-2 text-xs text-ink-2">
          <Check aria-hidden className="mt-0.5 size-3.5 shrink-0 text-ok" />
          <span>Connected. The engine restarted and this model is now the one answering.</span>
        </p>
      )}
      {status === 'restart' && (
        <p role="status" className="rounded-card border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          <strong className="font-semibold">Saved — restart the engine to apply it.</strong> The
          engine reads <code className="font-mono">.env</code> and{' '}
          <code className="font-mono">config.yaml</code> at startup. This browser window cannot
          restart it; the installed app does that for you. Restart the engine (or Pantler) and the
          model will answer.
        </p>
      )}
      {status === 'removed' && (
        <p role="status" className="rounded-card border border-line bg-canvas px-3 py-2 text-xs text-ink-3">
          The key was removed from this profile. The model will stop answering until a new key is
          connected.
        </p>
      )}

      {!compact && (
        <p className="text-xs leading-relaxed text-ink-3">
          <KeyRound aria-hidden className="mr-1 inline size-3 align-[-2px]" />
          The key is written to this machine’s profile and never returns to this page. Pantler does
          not proxy the model call or pay for it.
        </p>
      )}
    </div>
  )
}
