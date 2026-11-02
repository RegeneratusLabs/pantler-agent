import { useQueryClient } from '@tanstack/react-query'
import { Brain, History, Info, KeyRound, UserRound } from 'lucide-react'
import { type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { identity } from '@identity'
import { LearningChangeLog, LearningPanel } from '../components/LearningPanel'
import { ModelForm } from '../model/ModelForm'
import { ChoiceCard, ChoiceGroup, SummaryRow } from '../onboarding/kit'
import { WORK_KINDS, operatorProfile, useOperatorProfile } from '../onboarding/profile'
import type { UpdateState } from '../pantler'
import { qk, useApp, useEngineSettings } from '../state/app-context'
import { useUpdateState } from '../state/updates'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Field, Input } from '../ui/field'
import { Tabs } from '../ui/tabs'
import { PersonalitySection } from './PersonalitySection'

/**
 * Settings — five tabs: the business, the voice, what it has learned, the advanced settings, and
 * this install. The guided path is the first three; the model provider lives under **Advanced**.
 *
 * **Why the model is behind Advanced.** A model key is the one thing a general operator never
 * has to think about after setup, and a provider form on the first tab told every one of them
 * that it was their job. It is still one click away for the people who want it — a different
 * provider, their own endpoint, a service the guided setup does not offer — and the "no model
 * connected" strip links straight to it. The form itself is unchanged: it writes the
 * `config.yaml` `model:` block and `.env` through the BFF, shows only whether a key is set, and
 * asks the desktop host to restart the engine so the write takes effect. Four providers with
 * endpoints pinned to the engine's own registry (`model/providers.ts`) plus a custom endpoint is
 * the honest list for now.
 *
 * **Why tabs.** The page had grown to four stacked sections, and the model form alone is taller
 * than a window; someone looking for the voice picker had to scroll past all of it. The tabs keep
 * each question separate and use the same pattern as Capabilities (`ui/tabs.tsx`), including the
 * ARIA keyboard behaviour. Panels stay mounted and hidden when inactive, so a half-typed key or a
 * chosen voice survives a tab switch. The selected tab is in the URL (`?tab=advanced`), because
 * more than one screen needs to point at it.
 */
type SettingsTab = 'business' | 'voice' | 'learning' | 'advanced' | 'about'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'business', label: 'Business' },
  { id: 'voice', label: 'Voice' },
  { id: 'learning', label: 'Learning' },
  { id: 'advanced', label: 'Advanced' },
  { id: 'about', label: 'About' }
]

/** The first tab a general operator lands on. */
const DEFAULT_TAB: SettingsTab = 'business'

function isTab(value: string | null): value is SettingsTab {
  return TABS.some(entry => entry.id === value)
}

export function SettingsPage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab = isTab(requested) ? requested : DEFAULT_TAB

  const choose = (next: SettingsTab) => {
    const updated = new URLSearchParams(params)
    if (next === DEFAULT_TAB) updated.delete('tab')
    else updated.set('tab', next)
    setParams(updated, { replace: true })
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6">
        <header className="flex flex-col gap-1">
          <p className="text-sm text-ink-2">
            The business it works for, how it sounds, and what it has learned. The model provider
            and key live under <strong className="font-medium text-ink">Advanced</strong>.
          </p>
        </header>

        <Tabs
          items={TABS}
          value={tab}
          onChange={next => choose(next as SettingsTab)}
          label="Settings sections"
        />

        <div
          role="tabpanel"
          id="panel-business"
          aria-labelledby="tab-business"
          hidden={tab !== 'business'}
          className="flex flex-col gap-6"
        >
          <ProfileSection />
        </div>

        <div
          role="tabpanel"
          id="panel-voice"
          aria-labelledby="tab-voice"
          hidden={tab !== 'voice'}
          className="flex flex-col gap-6"
        >
          <PersonalitySection />
        </div>

        <div
          role="tabpanel"
          id="panel-learning"
          aria-labelledby="tab-learning"
          hidden={tab !== 'learning'}
          className="flex flex-col gap-6"
        >
          <LearningSection />
        </div>

        <div
          role="tabpanel"
          id="panel-advanced"
          aria-labelledby="tab-advanced"
          hidden={tab !== 'advanced'}
          className="flex flex-col gap-6"
        >
          <section className="flex flex-col gap-2">
            <h2 className="text-display text-sm text-ink">For advanced users</h2>
            <p className="text-sm leading-relaxed text-ink-2">
              Bring your own model provider — a key from one of the providers below, or any
              OpenAI-compatible endpoint, including a model on this machine. This is also where the
              diagnostics, credentials and services the guided setup does not offer belong. Most
              people never need this page.
            </p>
          </section>
          <ModelSection />
          <Section
            icon={<History className="size-4" />}
            title="Learning change log"
            subtitle="Every skill the assistant has written or changed, and the conversation that caused it. Read-only."
          >
            <LearningChangeLog />
          </Section>
        </div>

        <div
          role="tabpanel"
          id="panel-about"
          aria-labelledby="tab-about"
          hidden={tab !== 'about'}
          className="flex flex-col gap-6"
        >
          <AboutSection />
        </div>
      </div>
    </div>
  )
}

/**
 * One section header, so the page reads as one thing. The voice section carries its own copy of
 * this markup rather than importing it (importing the other way would make the two files circular).
 */
function Section({
  icon,
  title,
  subtitle,
  children
}: {
  icon: ReactNode
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-start gap-2.5">
        <span aria-hidden className="mt-0.5 text-ink-3">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-display text-sm text-ink">{title}</h2>
          <p className="text-xs text-ink-3">{subtitle}</p>
        </div>
      </header>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------- model

/**
 * The provider and its key.
 *
 * `available: false` is a normal answer, not an error: the BFF was started without a profile
 * directory, so there is no `config.yaml` to edit and the form would have nowhere to write.
 */
function ModelSection() {
  const { data: settings, isPending } = useEngineSettings()
  const { bff } = useApp()
  const queryClient = useQueryClient()

  return (
    <Section
      icon={<KeyRound className="size-4" />}
      title="Model"
      subtitle="The provider that answers and the key it uses. Written to this profile, never read back."
    >
      <Card className="gap-4">
        {isPending ? (
          <p className="text-sm text-ink-3">Reading this install’s settings…</p>
        ) : !settings?.available ? (
          <p className="text-sm text-ink-3">
            {settings?.reason ?? 'Settings are read-only here, so there is no profile to write.'}
          </p>
        ) : (
          <ModelForm
            settings={settings}
            bff={bff}
            onSaved={() => void queryClient.invalidateQueries({ queryKey: qk.settings })}
          />
        )}
      </Card>
    </Section>
  )
}

// -------------------------------------------------------------------- profile

/**
 * The operator's own answers: what to call them, what the business is called, and what it mostly
 * does. The labels are the first run's, word for word — a question asked differently in two places
 * is two questions.
 *
 * `work` is *not* a label on the business and the copy says so: it picks the examples and the apps
 * shown during setup (`onboarding/apps.ts`, `onboarding/tour.ts`), which is the whole of what it
 * does in this build. Selling it as more than that would be the kind of claim this page exists to
 * avoid.
 */
function ProfileSection() {
  const profile = useOperatorProfile()

  return (
    <Section
      icon={<UserRound className="size-4" />}
      title="Your details"
      subtitle="Who the assistant is working for. The same questions the first run asks, kept on this machine."
    >
      <Card className="gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="What should I call you?" hint="A first name is plenty.">
            <Input
              value={profile.name}
              autoComplete="given-name"
              placeholder="Sam"
              onChange={event => void operatorProfile.update({ name: event.target.value })}
            />
          </Field>
          <Field label="What is the business called?" hint="As you would say it to a customer.">
            <Input
              value={profile.business}
              autoComplete="organization"
              placeholder="Bellview Farm"
              onChange={event => void operatorProfile.update({ business: event.target.value })}
            />
          </Field>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-display text-xs text-ink-3">What does it mostly do?</span>
          <ChoiceGroup
            label="What the business mostly does"
            className="grid gap-2 sm:grid-cols-3"
          >
            {WORK_KINDS.map(kind => (
              <ChoiceCard
                key={kind.id}
                selected={profile.work === kind.id}
                onSelect={() => void operatorProfile.update({ work: kind.id })}
                title={kind.label}
                subtitle={kind.blurb}
                className="p-3"
              />
            ))}
          </ChoiceGroup>
          <p className="text-xs text-ink-3">
            This picks the examples and the apps the setup shows you. It is not a label on your
            business — most places do two of these.
          </p>
        </div>

        <p className="border-t border-line pt-3 text-xs text-ink-disabled">
          Saved as you type, and kept in this browser rather than on the engine — one set of
          answers per profile, so your phone and this machine each hold their own copy of each.
        </p>
      </Card>
    </Section>
  )
}

// ----------------------------------------------------------------- learning

/**
 * What the assistant has learned, folded away.
 *
 * A `<Section>` like the others so the page reads as one thing, with the content itself collapsed
 * — this is a screen someone opens to *check* something, not to act, and an expanded wall of
 * memory entries at the end of the page would give it weight it has not earned.
 */
function LearningSection() {
  return (
    <Section
      icon={<Brain className="size-4" />}
      title="What it has learned"
      subtitle="Read-only. The facts it keeps about your business, and the skills it has written for itself."
    >
      <LearningPanel />
    </Section>
  )
}

// --------------------------------------------------------------------- about

/**
 * This install, honestly: the version, the profile, the runtime, and what an update does.
 *
 * There is no "check for updates" button because the updater is off in this build and the
 * installer is unsigned; a button that can only ever answer "no" is a worse answer than the
 * sentence. The paths are the installed app's and the copy says so — a browser build has no such
 * folder, which is why the sentence names the app rather than claiming this page's own machine.
 */
function AboutSection() {
  const { data: settings } = useEngineSettings()
  const versions = window.pantler?.versions
  const update = useUpdateState()

  return (
    <Section
      icon={<Info className="size-4" />}
      title="This install"
      subtitle="The version, the profile it reads, and where your data lives."
    >
      <Card className="gap-4">
        <dl className="flex flex-col rounded-card border border-line bg-canvas px-4 py-1">
          <SummaryRow label="Version" value={__PANTLER_VERSION__} />
          <SummaryRow label="Profile" value={settings?.profile?.name ?? 'not configured'} />
          <SummaryRow label="Update channel" value={identity.updateFeedChannel} />
          <SummaryRow label="Updates" value={updateLabel(update.state)} />
          {versions?.electron && <SummaryRow label="Electron" value={versions.electron} />}
          {versions?.chrome && <SummaryRow label="Chromium" value={versions.chrome} />}
          {versions?.node && <SummaryRow label="Node" value={versions.node} />}
        </dl>

        {update.supported && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void update.check()}
              disabled={
                update.busy || update.state.status === 'checking' || update.state.status === 'downloading'
              }
            >
              {update.state.status === 'checking' ? 'Checking…' : 'Check for updates'}
            </Button>
            {update.state.status === 'downloaded' && (
              <Button variant="primary" size="sm" onClick={() => void update.install()} disabled={update.busy}>
                Restart and install{update.state.version ? ` ${update.state.version}` : ''}
              </Button>
            )}
            {update.state.status === 'error' && update.state.error && (
              <span className="text-xs text-danger">
                {update.state.error}{' '}
                <a
                  href="https://github.com/RegeneratusLabs/pantler-agent/releases/latest"
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  Download it manually
                </a>
              </span>
            )}
          </div>
        )}

        <p className="text-xs leading-relaxed text-ink-3">
          Profiles, records, conversations and the model key live in this profile on this machine —
          <code className="font-mono"> %APPDATA%\pantler</code> in the installed Windows app —
          outside the program, so a new installer keeps them. The desktop app writes the engine and
          server logs to <code className="font-mono">%APPDATA%\pantler\logs</code>.
        </p>

        <p className="text-xs leading-relaxed text-ink-3">
          Updates are checked after launch and every four hours, and downloaded in the background;
          you choose when to restart. The installer is not code-signed yet, so an update is checked
          against the SHA-512 in <code className="font-mono">latest.yml</code> but carries no
          publisher signature — install it only if you trust this repository. 0.0.5 is the first
          build that can update itself; 0.0.4 needs the manual installer.
        </p>
      </Card>
    </Section>
  )
}

function updateLabel(state: UpdateState): string {
  switch (state.status) {
    case 'checking':
      return 'Checking…'
    case 'available':
      return 'Downloading…'
    case 'downloading':
      return `Downloading ${state.percent ?? 0}%`
    case 'downloaded':
      return state.version ? `${state.version} is ready` : 'Ready to install'
    case 'error':
      return 'Check failed'
    case 'idle':
      return state.checkedAt ? 'Up to date' : 'Not checked yet'
    default:
      return 'Not available here'
  }
}
