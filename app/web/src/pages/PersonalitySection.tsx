/**
 * Settings → Your voice.
 *
 * The same picker the first run uses (`onboarding/VoicePicker.tsx`), because a choice that looks
 * different in the two places it can be made is a choice people are unsure they made.
 *
 * **Why this writes to us and not to the engine's config.** Hermes has `display.personality`, and we
 * do not touch it. That key is read by the CLI and the messaging gateway and *not* by the API server
 * this app talks to, so writing it would put a switch on this screen that changes nothing about the
 * conversations had here — the exact thing the rest of this page refuses to do. What the seam does
 * honour is the `instructions` field on each run, which is what the chat passes and what
 * `onboarding/personalities.ts` owns (the engine notes §9).
 *
 * The page's usual "saved, not yet in effect" warning is therefore absent, and that is deliberate:
 * this one takes effect on the next message, and saying otherwise would teach the operator to
 * distrust the warning that does matter.
 */

import { MicVocal } from 'lucide-react'
import { Link } from 'react-router'
import { Card } from '../ui/card'
import { VoicePicker } from '../onboarding/VoicePicker'
import { operatorProfile, useOperatorProfile } from '../onboarding/profile'
import { voiceById } from '../onboarding/personalities'

export function PersonalitySection() {
  const profile = useOperatorProfile()
  const voice = voiceById(profile.voice)

  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-start gap-2.5">
        <span aria-hidden className="mt-0.5 text-ink-3">
          <MicVocal size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-display text-sm text-ink">Your voice</h2>
          <p className="text-xs text-ink-3">
            How the assistant talks to you. Currently <strong className="font-medium">{voice.label}</strong>{' '}
            — {voice.tagline.toLowerCase()}.
          </p>
        </div>
      </header>

      <Card className="flex flex-col gap-4 p-4">
        <VoicePicker value={profile.voice} onChange={next => void operatorProfile.update({ voice: next })} />
        <p className="text-xs text-ink-3">
          Takes effect on your next message — nothing to restart. To see the setup questions again,{' '}
          <Link to="/welcome" className="text-accent underline underline-offset-2">
            run the guided setup
          </Link>
          .
        </p>
      </Card>
    </section>
  )
}
