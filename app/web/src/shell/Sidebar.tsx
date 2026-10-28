import { Clock, Database, MessageSquare, Moon, Puzzle, Settings, Sun, Users } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router'
import { PantlerMark } from '../brand/PantlerMark'
import { Wordmark } from '../brand/Wordmark'
import { useCapabilities, useHealth } from '../state/app-context'
import { useMascotState } from '../state/presence'
import { useProfiles } from '../state/profile-context'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { ProfileSwitcher } from './ProfileSwitcher'
import { SessionList } from './SessionList'
import { applyTheme, loadTheme, saveTheme, type Theme } from './theme'
import { useState } from 'react'

const NAV = [
  { to: '/chat', label: 'Chat', icon: MessageSquare, end: false },
  { to: '/records', label: 'Records', icon: Database, end: true },
  { to: '/profiles', label: 'Profiles', icon: Users, end: true },
  { to: '/capabilities', label: 'Capabilities', icon: Puzzle, end: true },
  { to: '/jobs', label: 'Scheduled jobs', icon: Clock, end: true },
  { to: '/settings', label: 'Settings', icon: Settings, end: true }
]

/**
 * The rail. Brand, the one action that matters (new session), navigation, history, and
 * the state of the connection — in that order, because that is the order a person uses
 * them in.
 */
export function Sidebar({
  onNavigate,
  className
}: {
  onNavigate?: () => void
  className?: string
}) {
  const navigate = useNavigate()
  const [theme, setTheme] = useState<Theme>(() => loadTheme())
  const mascot = useMascotState()

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
    saveTheme(next)
  }

  return (
    <div
      className={cn(
        'flex h-full w-full flex-col border-r border-line bg-surface',
        className
      )}
    >
      {/* The lockup: the real mark, the outlined wordmark, and the weather. 36px is comfortably
          above the mark's 24px minimum and keeps its face legible; 18px of padding is its
          half-height clear space. The wordmark is the SVG, not live text, so it cannot drift
          from the artwork. */}
      <div className="flex items-center gap-[18px] px-[18px] py-[18px]">
        <PantlerMark state={mascot} size={36} interactive />
        <Wordmark />
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          className="ml-auto grid size-7 shrink-0 place-items-center rounded-md text-ink-3 transition-colors hover:bg-hover hover:text-ink"
        >
          {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
      </div>

      <ProfileSwitcher onNavigate={onNavigate} />

      <div className="px-3 pb-3">
        <Button
          variant="primary"
          className="w-full"
          onClick={() => {
            navigate('/chat')
            onNavigate?.()
          }}
        >
          <MessageSquare className="size-4" />
          New session
        </Button>
      </div>

      <nav aria-label="Primary" className="flex flex-col gap-0.5 px-3 pb-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-hover font-medium text-ink'
                  : 'text-ink-2 hover:bg-hover hover:text-ink'
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mx-3 border-t border-line" />

      <div className="flex min-h-0 flex-1 flex-col pt-2">
        <h2 className="text-display px-3 pb-1 text-[0.68rem] text-ink-3">Sessions</h2>
        <SessionList onNavigate={onNavigate} />
      </div>

      <SidebarFooter />
    </div>
  )
}

/**
 * The rail's last line: whether the engine is answering, and which model it reports.
 *
 * There is no power button beside it any more — it existed only to send the app back to the
 * connect screen, and that screen is gone. Nor is there anywhere to re-point the app: the address
 * is `/seam`, forwarded by the app's own server, and an engine that stops answering is reported by
 * the strip AppShell puts above every page.
 */
function SidebarFooter() {
  const { data: health, isError } = useHealth()
  const { data: capabilities } = useCapabilities()
  const { profiles, active } = useProfiles()

  const online = !isError && Boolean(health)
  const version = typeof health?.version === 'string' ? health.version : null
  // The host gateway's advertised model is `hermes-agent`; the thing the operator is actually
  // talking to is the selected profile's model, which the registry already knows.
  const selected = profiles.find(profile => profile.name === active)
  const model = selected?.model ?? capabilities?.model

  return (
    <div className="flex items-center gap-2 border-t border-line px-3 py-2.5">
      <span
        aria-hidden
        className={cn('size-1.5 shrink-0 rounded-full', online ? 'bg-accent' : 'bg-danger')}
      />
      <span className="min-w-0 flex-1 truncate font-mono text-[0.68rem] text-ink-3">
        {online ? (model ?? 'connected') : 'engine unreachable'}
        {version && <span className="text-ink-disabled"> · {version}</span>}
      </span>
    </div>
  )
}
