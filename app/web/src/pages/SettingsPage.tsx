import { Brain, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { LearningPanel } from '../components/LearningPanel'
import { ChoiceCard, ChoiceGroup } from '../onboarding/kit'
import { WORK_KINDS, operatorProfile, useOperatorProfile } from '../onboarding/profile'
import { Card } from '../ui/card'
import { Field, Input } from '../ui/field'
import { PersonalitySection } from './PersonalitySection'

/**
 * Settings — the profile questions the first run asks, the voice, and what the assistant has
 * learned. Three sections, and that is the whole screen.
 *
 * **What was removed, and why.** Model, API key, Providers and Connection. For the build we are
 * shipping there is nothing in any of them for an operator to decide:
 *
 *   * **Model.** The install is configured with one, and there is no model *selection* in this
 *     version: a list of names to pick from is a decision we are not asking anyone to make yet.
 *     The reasoning-effort control lived inside this section and went with it. The engine's
 *     `agent.reasoning_effort` and the BFF route that writes it are untouched, so bringing that
 *     control back is a screen, not a capability.
 *   * **API key.** Held by the server this app is served from (the dev server today, the shell in
 *     Phase 1) and added on the way through the `/seam` proxy, so it never reaches this browser.
 *     There is no browser-side copy to paste a replacement into.
 *   * **Providers.** A directory of names nobody can act on: the catalogue carries a provider's
 *     auth type and key variable but never its `base_url`, so switching from here would leave the
 *     engine pointed at the previous provider's endpoint. What a directory cannot do is not worth
 *     a screen.
 *   * **Connection.** The address is `/seam`, forwarded by the app itself. The one case that used
 *     to justify a field — an engine that has moved or is not answering — is a strip across the top
 *     (`shell/EngineNotice.tsx`), and the fix belongs where the engine is started, not in a text
 *     box the browser holds.
 *
 * The "saved, not yet in effect" restart notice went with them, and that is not a loss: the model
 * and `.env` writes were the only two that set `restart_required`
 * (`app/server/pantler_server.py`), and the switches that remain — the capabilities page's
 * suppression lists — land on the next conversation by design. A warning that can never be earned
 * is worse than no warning.
 *
 * **What replaced them** is the profile: the same questions the first run asks on its "Who am I
 * working for?" step, in the same controls, writing to the same store (`onboarding/profile.ts`) —
 * so an answer given here is the answer setup would have given. It saves as you type, exactly like
 * the first run and the voice picker below it, and there is no Save button because there is nothing
 * a Save button would do that typing has not already done.
 */
export function SettingsPage() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6">
        <ProfileSection />
        <PersonalitySection />
        <LearningSection />
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
