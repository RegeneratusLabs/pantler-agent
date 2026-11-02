/**
 * An update is downloaded and waiting for a restart.
 *
 * The host downloads in the background but never installs on its own (`autoInstallOnAppQuit` is
 * off), so this strip is the prompt. "Later" hides it for this session; About still offers the
 * install, so a dismissed update is one click away rather than lost.
 *
 * It only appears when the host has downloaded something: a checking or downloading state is
 * About's business, not a banner on every page.
 */

import { useState } from 'react'
import { useUpdateState } from '../state/updates'
import { Button } from '../ui/button'

export function UpdateNotice() {
  const { supported, state, busy, install } = useUpdateState()
  const [dismissed, setDismissed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!supported || state.status !== 'downloaded' || dismissed) return null

  const label = state.version ? `Pantler ${state.version}` : 'A new version of Pantler'

  const run = async () => {
    setError(null)
    const result = await install()
    if (!result.ok) setError(result.error ?? 'The update could not start.')
  }

  return (
    <div className="print-hide flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-accent/30 bg-accent/5 px-3 py-2 text-xs text-ink-2">
      <span className="min-w-0 flex-1">
        <strong className="font-medium text-ink">{label} is ready.</strong> Restart to install it —
        your records, conversations and model key stay where they are.
        {error && <span className="mt-1 block text-danger">{error}</span>}
      </span>
      <Button variant="primary" size="sm" disabled={busy} onClick={() => void run()}>
        {busy ? 'Starting…' : 'Restart and install'}
      </Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => setDismissed(true)}>
        Later
      </Button>
    </div>
  )
}
