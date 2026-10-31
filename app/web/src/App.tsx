import { QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { OnboardingPage } from './onboarding/OnboardingPage'
import { operatorProfile } from './onboarding/profile'
import { StartRedirect } from './onboarding/StartRedirect'
import { CapabilitiesPage } from './pages/CapabilitiesPage'
import { ChatPage, NewChatRedirect } from './pages/ChatPage'
import { JobsPage } from './pages/JobsPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { RecordsPage } from './pages/RecordsPage'
import { SettingsPage } from './pages/SettingsPage'
import { loadSettings, saveSettings, type SeamSettings } from './seam/settings'
import { AppShell } from './shell/AppShell'
import { AppProvider, createQueryClient } from './state/app-context'
import { ProfileProvider, useProfiles } from './state/profile-context'

/**
 * The application, which opens on the conversation — or on the first run, for someone who has not
 * been through it yet.
 *
 * There is no connect screen in front of it, and that is deliberate. The address is already
 * `/seam` and the dev server supplies the engine's key on the way through the proxy (in
 * Phase 1 the shell does the same job), so a screen asking for a gateway address and a key
 * has nothing to ask for — it is a door that only opens outward. The same argument retired
 * Settings → **Connection**: the one case that used to justify a field there, an engine that has
 * moved or is not answering, is a strip across the top (`shell/EngineNotice.tsx`) that says what
 * is wrong and leaves the fix where the engine is started.
 *
 * The seam settings are still state rather than a constant because a value an earlier build
 * stored is still honoured (`seam/settings.ts`). No screen calls `updateSettings` any more; it is
 * kept for the shell tier, which is where a secret is allowed to live (the desktop notes).
 *
 * The first run is a screen of its own, outside the shell: no rail, nothing to navigate to yet
 * (`onboarding/OnboardingPage.tsx`). It replaces the catch-all rather than guarding every route, so
 * someone halfway through setup can still follow the apps link into Settings.
 */
export function App() {
  const [settings, setSettings] = useState<SeamSettings>(loadSettings)
  // Created once: a query client that is rebuilt on render would drop every cache entry.
  const [queryClient] = useState(createQueryClient)

  /**
   * Re-point the app at a different engine. Every panel is refetched because the old answers
   * came from the old address — keeping them cached under the same key would show one engine's
   * data beside another's.
   */
  const updateSettings = useCallback(
    (next: SeamSettings) => {
      saveSettings(next)
      setSettings(next)
      void queryClient.invalidateQueries()
    },
    [queryClient]
  )

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ProfileProvider>
          <ScopedApp settings={settings} updateSettings={updateSettings} />
        </ProfileProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

/**
 * The application under a profile scope.
 *
 * The clients are built from the selected profile, so changing it rebuilds both the seam client
 * (whose URLs carry `/p/<name>/`) and the BFF client (whose requests carry the header). The
 * cache is dropped on a change for the same reason: one business's sessions and records must
 * never appear under another's name, even for the frame between the click and the refetch.
 */
function ScopedApp({
  settings,
  updateSettings
}: {
  settings: SeamSettings
  updateSettings: (next: SeamSettings) => void
}) {
  const { active, install } = useProfiles()
  useProfileCacheReset(active)
  // The setup answers follow the business. The installed profile inherits the legacy single-key
  // value once, so an upgrade does not ask the operator who they are all over again.
  useEffect(() => {
    operatorProfile.setScope(active, { inheritLegacy: active !== null && active === install })
  }, [active, install])
  return (
    <AppProvider settings={settings} updateSettings={updateSettings} profile={active}>
      <Routes>
        {/* Outside the shell: first run has no rail, and nothing to navigate to yet. */}
        <Route path="/welcome" element={<OnboardingPage />} />
        <Route element={<AppShell />}>
          <Route path="/chat" element={<NewChatRedirect />} />
          <Route path="/chat/:sessionId" element={<ChatPage />} />
          <Route path="/records" element={<RecordsPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/capabilities" element={<CapabilitiesPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<StartRedirect />} />
        </Route>
      </Routes>
    </AppProvider>
  )
}

function useProfileCacheReset(active: string | null) {
  const queryClient = useQueryClient()
  // `undefined` is "the registry has not answered yet", which is different from "the registry
  // answered null". The first resolution from undefined to a name drops the requests made
  // before the profile was known (the bare `/seam` ones); a later change drops the old
  // profile's answer. Removing during the transition is what stops one business's rows being
  // shown under another's name for a frame.
  const previous = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (previous.current !== undefined && previous.current !== active) {
      // `resetQueries`, not `removeQueries`: removing an active query detaches the observers
      // mid-flight and leaves the screen on its loading state (observed live). A reset clears
      // the old answer, aborts the request that belonged to it, and refetches through the
      // *new* client, which is the one carrying `/p/<name>/`. The registry is the exception:
      // it is the thing that just changed, and resetting it would loop the switch.
      void queryClient.resetQueries({
        predicate: query => query.queryKey[0] !== 'profiles'
      })
    }
    previous.current = active
  }, [active, queryClient])
}
