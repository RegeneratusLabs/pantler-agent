/**
 * No model is connected.
 *
 * The installer carries the engine but not a model, and the first run can be skipped at that step.
 * Without this strip the first message fails inside the engine and the operator has no way to read
 * that as "there is a setting for this". It is a prompt, not an error: everything that does not
 * need a model still works, and the fix is one link away.
 *
 * It hides only on Settings' Advanced tab, where the form it points at is on screen, and on the
 * first run, which is outside the shell entirely. On Settings' other tabs it stays, because that
 * is exactly where someone might wonder why the assistant is not answering.
 */

import { Link, useLocation } from 'react-router'
import { useEngineSettings } from '../state/app-context'

export function ModelNotice() {
  const { data: settings } = useEngineSettings()
  const { pathname, search } = useLocation()

  if (!settings?.available) return null
  if (settings.model?.default) return null
  const onAdvanced =
    pathname.startsWith('/settings') && new URLSearchParams(search).get('tab') === 'advanced'
  if (onAdvanced) return null

  return (
    <div className="print-hide flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-accent/30 bg-accent/5 px-3 py-2 text-xs text-ink-2">
      <span className="min-w-0 flex-1">
        No model is connected yet. Pantler needs a provider key before it can answer — the key stays
        on this machine.
      </span>
      <Link
        to="/settings?tab=advanced"
        className="font-medium text-accent underline underline-offset-2 hover:brightness-110"
      >
        Connect one
      </Link>
    </div>
  )
}
