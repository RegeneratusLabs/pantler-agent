import { Menu, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation } from 'react-router'
import { PantlerMark } from '../brand/PantlerMark'
import { PresenceProvider, useMascotState } from '../state/presence'
import { cn } from '../ui/cn'
import { EngineNotice } from './EngineNotice'
import { Sidebar } from './Sidebar'

/** The rail is a slide-over below this width; a fixed column above it. */
const RAIL_WIDTH = 'w-[17.5rem]'

function titleFor(pathname: string): string {
  if (pathname.startsWith('/chat')) return 'Chat'
  if (pathname.startsWith('/profiles')) return 'Profiles'
  if (pathname.startsWith('/records')) return 'Records'
  if (pathname.startsWith('/capabilities')) return 'Capabilities'
  if (pathname.startsWith('/jobs')) return 'Scheduled jobs'
  if (pathname.startsWith('/settings')) return 'Settings'
  return ''
}

/**
 * The shell, with one small piece of shared state above it.
 *
 * The chat reports what the assistant is doing; the rail and the phone header read it. Keeping
 * the provider here rather than in `App` means the first-run screen, which has no rail, never
 * pays for it and never has to fake a state.
 */
export function AppShell() {
  return (
    <PresenceProvider>
      <ShellChrome />
    </PresenceProvider>
  )
}

function ShellChrome() {
  const [railOpen, setRailOpen] = useState(false)
  const { pathname } = useLocation()
  const mascot = useMascotState()
  const drawer = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  // The slide-over covers the trigger (z-40 over the header's button), so the only way out was
  // the backdrop: no Escape, and focus stayed on a control nobody can see or reach
  // (the internal audit WEB-11). Escape closes it, focus moves into the drawer and comes
  // back to the trigger when it closes.
  useEffect(() => {
    if (!railOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setRailOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    drawer.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      trigger.current?.focus()
    }
  }, [railOpen])

  return (
    <div className="flex h-dvh overflow-hidden bg-canvas text-ink">
      <aside className={cn('print-hide hidden shrink-0 lg:block', RAIL_WIDTH)}>
        <Sidebar />
      </aside>

      {railOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="animate-fade absolute inset-0 bg-black/55 backdrop-blur-sm"
            onClick={() => setRailOpen(false)}
          />
          <div
            ref={drawer}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className={cn(
              'animate-slide-in absolute inset-y-0 left-0 shadow-2xl outline-none',
              'w-[min(19rem,85vw)]'
            )}
          >
            <Sidebar onNavigate={() => setRailOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="print-hide flex h-12 shrink-0 items-center gap-3 border-b border-line px-3">
          <button
            type="button"
            ref={trigger}
            aria-label={railOpen ? 'Close navigation' : 'Open navigation'}
            aria-expanded={railOpen}
            onClick={() => setRailOpen(value => !value)}
            className="grid size-8 place-items-center rounded-md text-ink-2 transition-colors hover:bg-hover hover:text-ink lg:hidden"
          >
            {railOpen ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
          {/* The rail is hidden on a phone, so the mark rides in the header instead. 24px with
              the header's 12px padding is exactly its half-height clear space. */}
          <span className="flex items-center lg:hidden">
            <PantlerMark state={mascot} size={24} interactive />
          </span>
          <h1 className="brand-display-sm truncate text-lg leading-[1.2] text-ink-2">
            {titleFor(pathname)}
          </h1>
        </header>

        <EngineNotice />

        <main className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
