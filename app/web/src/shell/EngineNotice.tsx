/**
 * The engine is not answering.
 *
 * This is the failure half of the connect screen, kept and made smaller. It says what is
 * wrong, but it does not stand in front of the application: a session list, an old transcript
 * and every settings page are still readable, and an operator who is only here to look
 * something up is not stopped by a dead engine they cannot fix anyway.
 *
 * **It does not offer to fix it, and that is the honest end of the old connect screen.** The
 * address is `/seam`, forwarded by the app's own server, and the key is that server's too — the
 * browser holds neither and Settings → Connection is gone. The remedy is where the engine is
 * started, which is not a text box this page could put in front of anyone.
 *
 * It lives in the shell rather than on a page because the rail that carries the same
 * information is hidden below `lg` — on a phone this strip is the only sign the engine is
 * down.
 */

import { SeamError } from '../seam/client'
import { useApp, useHealth } from '../state/app-context'
import { Button } from '../ui/button'

export function EngineNotice() {
  const { settings } = useApp()
  const { error, isError, isFetching, refetch } = useHealth()

  if (!isError) return null

  // A refused key answers exactly like a dead engine — one failed request — but the two are
  // different problems, and saying which one it is saves the walk to a settings page that can
  // no longer help. The difference is the whole content of this strip.
  const refused =
    error instanceof SeamError && (error.status === 401 || error.status === 403)
      ? error.status
      : null

  return (
    <div className="print-hide flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
      <span className="min-w-0 flex-1">
        {refused !== null ? (
          <>
            The engine refused this app's key (HTTP {refused}). The key belongs to the server this
            app is served from, not to this browser — so it is that server's profile to check.
          </>
        ) : (
          <>
            The engine is not answering at <code className="font-mono">{settings.baseUrl}</code>.
            The app reaches it through its own server, so there is nothing to change here — check
            the engine is running, then retry.
          </>
        )}
      </span>
      <Button variant="ghost" size="sm" disabled={isFetching} onClick={() => void refetch()}>
        {isFetching ? 'Checking…' : 'Retry'}
      </Button>
    </div>
  )
}
