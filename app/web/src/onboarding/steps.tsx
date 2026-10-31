/**
 * The six step bodies. Copy first, controls second — the words are most of the design here.
 *
 * Every claim on these screens has to be true of *this build*, which is why the apps step says the
 * connections are not switched on yet (`pages/connectors.ts` — nothing is wired) and why the closing
 * summary says where each answer can be changed instead of implying it is final. A first run that
 * oversells is a first run that teaches the operator not to trust the rest.
 */

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Check, Copy, ExternalLink } from 'lucide-react'
import { identity } from '@identity'
import { PantlerMark } from '../brand/PantlerMark'
import { CONNECTOR_PLATFORM } from '../pages/connectors'
import { connectorsToShow } from './apps'
import { Button } from '../ui/button'
import { Field, Input } from '../ui/field'
import { ChoiceCard, ChoiceGroup, SampleLine, StepFrame, SummaryRow } from './kit'
import { VoicePicker } from './VoicePicker'
import { TOUR } from './tour'
import { exampleAsks } from '../chat/examples'
import { WORK_KINDS, type OperatorProfile } from './profile'
import { voiceById } from './personalities'
import type { StepId } from './flow'

export interface StepProps {
  profile: OperatorProfile
  update: (patch: Partial<OperatorProfile>) => void
  go: (step: StepId) => void
}

export function StepBody({ step, ...props }: StepProps & { step: StepId }) {
  switch (step) {
    case 'welcome':
      return <WelcomeStep />
    case 'business':
      return <BusinessStep {...props} />
    case 'voice':
      return <VoiceStep {...props} />
    case 'apps':
      return <AppsStep {...props} />
    case 'tour':
      return <TourStep {...props} />
    case 'done':
      return <DoneStep {...props} />
  }
}

// ------------------------------------------------------------------- welcome

function WelcomeStep() {
  return (
    <div className="flex flex-col gap-8">
      {/* The first thing a new operator meets. 64px of mark with 32px of clear space before the
          words; a pat makes him squash, and the copy below does the talking. */}
      <div className="flex justify-center">
        <PantlerMark state="idle" size={64} interactive enter label="Pantler" />
      </div>
      <StepFrame
        eyebrow="Welcome"
        title="This is an assistant for the business side of your work"
        lede={`${identity.displayName} keeps the paperwork moving — quotes, invoices, records, deliveries and the dates that must not be missed — so you can stay on the work.`}
      >
        <ul className="flex flex-col gap-3 text-sm text-ink-2">
          {[
            'Ask in your own words. There is no special command to learn.',
            'If something is unclear — two customers called Bellview — it asks instead of guessing.',
            'It never sends anything, or moves money, without you saying so.',
            'What you type stays on this machine.'
          ].map(line => (
            <li key={line} className="flex items-start gap-2.5">
              <Check aria-hidden size={16} className="mt-0.5 shrink-0 text-accent" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-3">
          Next you’ll tell me who you are, how you’d like me to sound, and where the apps you use will
          live. Six short steps — and you can stop at any point.
        </p>
      </StepFrame>
    </div>
  )
}

// ------------------------------------------------------------------ business

function BusinessStep({ profile, update }: StepProps) {
  return (
    <StepFrame
      eyebrow="You"
      title="Who am I working for?"
      lede="Both boxes are optional — but a name makes the replies feel less like a form."
    >
      <div className="flex flex-col gap-4">
        <Field label="What should I call you?" hint="A first name is plenty.">
          <Input
            value={profile.name}
            autoComplete="given-name"
            placeholder="Sam"
            onChange={event => update({ name: event.target.value })}
          />
        </Field>
        <Field label="What is the business called?" hint="As you would say it to a customer.">
          <Input
            value={profile.business}
            autoComplete="organization"
            placeholder="Bellview Farm"
            onChange={event => update({ business: event.target.value })}
          />
        </Field>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-ink">What does it mostly do?</h2>
        <ChoiceGroup
          label="What the business mostly does"
          className="flex flex-col gap-3"
        >
          {WORK_KINDS.map(kind => (
            <ChoiceCard
              key={kind.id}
              selected={profile.work === kind.id}
              onSelect={() => update({ work: kind.id })}
              title={kind.label}
              subtitle={kind.blurb}
            />
          ))}
        </ChoiceGroup>
        <p className="text-xs text-ink-3">
          This picks the examples I show you, and which part of the app opens first. It is not a
          label on your business — most places do two of these.
        </p>
      </div>
    </StepFrame>
  )
}

// --------------------------------------------------------------------- voice

function VoiceStep({ profile, update }: StepProps) {
  return (
    <StepFrame
      eyebrow="Your voice"
      title="How should I sound?"
      lede="Same answers, three manners. The sample under each one is the same question answered that way."
    >
      <VoicePicker value={profile.voice} onChange={voice => update({ voice })} />
      <p className="text-xs text-ink-3">
        This applies from your next message, and it is always changeable in Settings.
      </p>
    </StepFrame>
  )
}

// ---------------------------------------------------------------------- apps

function AppsStep({ profile }: StepProps) {
  // Chosen for the work they said they do, not sliced off the front of the list — see `apps.ts`.
  const shown = connectorsToShow(profile.work)
  return (
    <StepFrame
      eyebrow="Your apps"
      title="The apps you already use"
      lede="Your shop, your till, your accounts, your email. When this is switched on, the assistant can read the orders that came in overnight and draft the reply — without you retyping anything."
    >
      <div className="flex flex-col gap-2 rounded-card border border-line bg-raised p-4">
        <h2 className="text-sm font-medium text-ink">How signing in works</h2>
        <p className="text-sm leading-relaxed text-ink-2">
          {CONNECTOR_PLATFORM.blurb}
        </p>
        <p className="text-xs text-ink-3">
          We never keep an app’s password, and you can disconnect one app without touching the rest.
        </p>
      </div>

      {/* After the explanation, not before it: the shared blurb says "the apps below", and the
          honest fix for that is to put them below rather than to rewrite the other agent's copy. */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {shown.map(connector => (
          <div
            key={connector.id}
            className="flex flex-col gap-1 rounded-card border border-line bg-raised px-3 py-2.5"
          >
            <span className="flex items-center gap-2 text-sm text-ink">
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: connector.color }}
              />
              {connector.name}
            </span>
            <span className="text-xs text-ink-3">{connector.kind}</span>
          </div>
        ))}
      </div>

      <p className="rounded-card border border-warning/40 bg-warning/10 px-3 py-2.5 text-xs text-warning">
        <strong className="font-semibold">Not switched on yet.</strong> This build shows you where the
        apps will live and what each one is for. Nothing is connected today, and there is nothing to
        do about it now.
      </p>
    </StepFrame>
  )
}

// ---------------------------------------------------------------------- tour

function TourStep({ profile }: StepProps) {
  const asks = exampleAsks(profile.work)
  return (
    <StepFrame
      eyebrow="A look around"
      title="Where everything is"
      lede="Four things, in the order you’ll meet them. Nothing here needs memorising — it is all on the rail down the side."
    >
      <ol className="flex flex-col gap-3">
        {TOUR.map(card => (
          <li key={card.id} className="flex flex-col gap-1.5 rounded-card border border-line bg-raised p-4">
            <span className="text-display text-[0.68rem] text-accent">
              {card.where}
            </span>
            <h2 className="text-sm font-medium text-ink">{card.title}</h2>
            <p className="text-xs leading-relaxed text-ink-2">{card.body}</p>
          </li>
        ))}
      </ol>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-ink">Three things worth trying first</h2>
        <p className="text-xs text-ink-3">
          Copy one and paste it into the chat when you get there — or type your own version. Yours
          will be better.
        </p>
        <ul className="flex flex-col gap-2">
          {asks.map(ask => (
            <AskToCopy key={ask} ask={ask} />
          ))}
        </ul>
      </div>
    </StepFrame>
  )
}

function AskToCopy({ ask }: { ask: string }) {
  const [copied, setCopied] = useState(false)
  // The confirmation's timer, cleared on unmount: a step change mid-confirmation used to leave a
  // `setCopied` firing into a component that was gone (the internal audit WEB-17).
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = () => {
    // Clipboard access can be refused (an insecure origin, a denied permission). Saying so is
    // better than a button that appears to work: the text is selectable either way.
    void navigator.clipboard
      ?.writeText(ask)
      .then(() => {
        setCopied(true)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => setCopied(false))
  }
  return (
    <li className="flex items-center gap-2 rounded-card border border-line bg-raised px-3 py-2.5">
      <span className="min-w-0 flex-1 text-xs leading-relaxed text-ink-2 italic">{ask}</span>
      <Button variant="quiet" size="sm" onClick={copy} aria-label={`Copy “${ask}”`}>
        {copied ? <Check aria-hidden size={13} /> : <Copy aria-hidden size={13} />}
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </li>
  )
}

// ---------------------------------------------------------------------- done

function DoneStep({ profile, update }: StepProps) {
  const voice = voiceById(profile.voice)
  const work = WORK_KINDS.find(kind => kind.id === profile.work)
  return (
    <StepFrame
      eyebrow="Ready"
      title="That’s the lot"
      lede="Here is what you told me. Every line of it can be changed later — nothing here is a commitment."
    >
      <dl className="flex flex-col rounded-card border border-line bg-raised px-4 py-1">
        <SummaryRow label="Call you" value={profile.name} />
        <SummaryRow label="Business" value={profile.business} />
        <SummaryRow label="Mostly" value={work?.label ?? ''} />
        <SummaryRow label="Voice" value={voice.label} />
      </dl>
      <div className="flex flex-col gap-2">
        <SampleLine>{voice.sample}</SampleLine>
        <p className="text-xs text-ink-3">
          Your apps are still waiting on the apps page, and your voice lives in Settings whenever you
          want a different one.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {/* One way out to the other surfaces, and it finishes setup on the way: the app should not
            drag them back here the next time it opens. */}
        <Link
          to="/settings"
          onClick={() => update({ complete: true })}
          className="inline-flex items-center gap-1.5 text-sm text-accent underline underline-offset-2 hover:brightness-110"
        >
          Open the apps page
          <ExternalLink aria-hidden size={13} />
        </Link>
      </div>
    </StepFrame>
  )
}
