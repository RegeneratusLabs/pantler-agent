import { Clock, Database, MessageSquare, Moon, Puzzle, Settings, Sun, Users } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router'
import { PantlerMark } from '../brand/PantlerMark'
import { Wordmark } from '../brand/Wordmark'
import { useMascotState } from '../state/presence'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { ProfileSwitcher } from './ProfileSwitcher'
import { SessionList } from './SessionList'
import { SidebarFooter } from './SidebarFooter'
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
