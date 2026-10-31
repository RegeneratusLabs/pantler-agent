/**
 * Choosing a voice — the one control that appears twice, in the first run and in Settings.
 *
 * It is the same component in both places on purpose. A setting that looks different from the
 * question that set it is how people end up unsure whether they are changing the same thing.
 */

import { VOICES, type VoiceId } from './personalities'
import { ChoiceCard, SampleLine } from './kit'

export function VoicePicker({
  value,
  onChange
}: {
  value: VoiceId
  onChange: (id: VoiceId) => void
}) {
  return (
    <div role="radiogroup" aria-label="How the assistant should sound" className="flex flex-col gap-3">
      {VOICES.map(voice => (
        <ChoiceCard
          key={voice.id}
          selected={value === voice.id}
          onSelect={() => onChange(voice.id)}
          title={voice.label}
          subtitle={voice.tagline}
        >
          <SampleLine>{voice.sample}</SampleLine>
        </ChoiceCard>
      ))}
      <p className="text-xs text-ink-3">
        All three work the same way — the same sums, and the same questions when something is
        unclear. Only the manner changes, and you can change it whenever you like.
      </p>
    </div>
  )
}
