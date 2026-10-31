import { useHealth } from '../state/app-context'
import { cn } from '../ui/cn'

/**
 * The rail's last line: whether the engine is answering.
 *
 * It deliberately does not name the model. The model is an implementation choice the operator
 * never made and cannot act on from here; showing `deepseek-v4.1-flash` bottom-left invited the
 * question the feedback asked. The engine version stays, because it is the one fact support may
 * need and it is not a choice either.
 *
 * There is no power button beside it any more — it existed only to send the app back to the
 * connect screen, and that screen is gone. Nor is there anywhere to re-point the app: the address
 * is `/seam`, forwarded by the app's own server, and an engine that stops answering is reported by
 * the strip AppShell puts above every page.
 */
export function SidebarFooter() {
  const { data: health, isError } = useHealth()

  const online = !isError && Boolean(health)
  const version = typeof health?.version === 'string' ? health.version : null

  return (
    <div className="flex items-center gap-2 border-t border-line px-3 py-2.5">
      <span
        aria-hidden
        className={cn('size-1.5 shrink-0 rounded-full', online ? 'bg-accent' : 'bg-danger')}
      />
      <span className="min-w-0 flex-1 truncate font-mono text-[0.68rem] text-ink-3">
        {online ? 'Connected' : 'engine unreachable'}
        {online && version && <span className="text-ink-disabled"> · {version}</span>}
      </span>
    </div>
  )
}
