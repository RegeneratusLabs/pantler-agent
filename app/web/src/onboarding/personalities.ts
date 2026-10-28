/**
 * The three voices.
 *
 * Hermes ships fourteen personality presets (`hermes_cli/personality.py::BUILTIN_PERSONALITIES`),
 * and eleven of them are jokes — pirate, catgirl, uwu, noir, hype. They are good jokes and they are
 * not a choice to put in front of someone who farms for a living. Three are real: `helpful`,
 * `concise` and `teacher`. Those are the three we ship, renamed for the person choosing:
 *
 *     Warm    ← helpful    friendly, says a little more
 *     Brief   ← concise    the number and nothing else
 *     Patient ← teacher    shows where the number came from
 *
 * Two decisions worth the words:
 *
 * 1. **We keep the engine's name on each voice** (`preset`), so the choice means the same thing if
 *    the operator ever opens a terminal and types `/personality concise`. But the instruction text
 *    we send is ours, written for this business rather than for a general assistant.
 *
 * 2. **The choice is applied by us, on every turn** — see `instructions()`. We do not write
 *    `display.personality` in the engine's config, because that key is read by the CLI and the
 *    messaging gateway and **not by the API server this app talks to**: setting it would be a
 *    switch that does nothing (the engine notes §9). What the seam does honour is the
 *    `instructions` field on `POST /v1/runs`, which the engine uses as the turn's ephemeral system
 *    prompt — verified by asking for a marker word and getting it back.
 *
 * The samples are the same question answered three ways, and they are real numbers from the example
 * price book (green beans at $12.00/kg, GST at 10%) — the arithmetic the kernel does, not invented
 * copy. A person choosing a voice should see the difference, not read a description of it.
 */

export type VoiceId = 'warm' | 'brief' | 'patient'

export interface Voice {
  id: VoiceId
  /** The engine preset this voice corresponds to. Never shown. */
  preset: string
  /** What the operator sees. */
  label: string
  tagline: string
  /** How it reads — one line, in the voice's own character. */
  sample: string
  /** The ephemeral system prompt sent with every turn. */
  instructions: string
}

/** The same question — "Bellview wants 12 kilos of beans, what do I charge?" — in three voices. */
export const VOICES: Voice[] = [
  {
    id: 'warm',
    preset: 'helpful',
    label: 'Warm',
    tagline: 'Talks like a helpful neighbour',
    sample: 'That comes to $158.40 for the beans — $144.00 plus $14.40 GST. Want me to draft it?',
    instructions:
      'Speak warmly and plainly, the way a helpful neighbour who knows the trade would. Use short ' +
      'sentences and everyday words — no jargon and no corporate tone. When you give a figure, say ' +
      'what it is for. When something is uncertain, say so and ask rather than guessing.'
  },
  {
    id: 'brief',
    preset: 'concise',
    label: 'Brief',
    tagline: 'Gives you the number and stops',
    sample: 'Beans: $144.00 + $14.40 GST = $158.40.',
    instructions:
      'Keep every reply as short as it can be while still being complete. Lead with the answer or ' +
      'the number, then at most one line of context. No preamble, no restating the question, and no ' +
      'lists unless the answer genuinely is a list.'
  },
  {
    id: 'patient',
    preset: 'teacher',
    label: 'Patient',
    tagline: 'Shows you where the number came from',
    sample:
      'Your price book has green beans at $12.00 a kilo, so 12 kilos is $144.00. GST at 10% adds ' +
      '$14.40, which makes it $158.40. I can draft that if you like.',
    instructions:
      'Explain as you go, in plain language, the way a patient teacher would. Show where a number ' +
      'came from — which price in the price book, what was added — and use a worked example when it ' +
      'helps. Never make the operator feel behind: say the simple version first and add detail only ' +
      'if it is wanted.'
  }
]

export const DEFAULT_VOICE_ID: VoiceId = 'warm'

const BY_ID = new Map(VOICES.map(voice => [voice.id, voice]))

/** The voice for an id, falling back to the default rather than throwing on stale stored data. */
export function voiceById(id: string | null | undefined): Voice {
  return BY_ID.get(id as VoiceId) ?? BY_ID.get(DEFAULT_VOICE_ID)!
}

/** Whether a string names one of our voices. Used to validate what comes back out of storage. */
export function isVoiceId(value: unknown): value is VoiceId {
  return typeof value === 'string' && BY_ID.has(value as VoiceId)
}

/**
 * What we send as the turn's `instructions`. Empty is a legitimate answer — it means "no voice
 * overlay", and the assistant falls back to the identity in SOUL.md — so an unknown voice
 * contributes nothing rather than an invented one.
 */
export function instructions(id: string | null | undefined): string {
  const voice = BY_ID.get(id as VoiceId)
  return voice ? voice.instructions : ''
}

/**
 * How the answer should be laid out, on every turn.
 *
 * This is a property of the chat surface, not of a voice: the window renders markdown
 * (`components/Markdown.tsx`), so the model is told to use it when it helps and not to decorate
 * a one-line answer. The wording deliberately leaves the shape to the answer rather than
 * demanding a heading on every reply.
 */
export const ANSWER_FORMAT_GUIDANCE =
  'Answer in markdown, not HTML, because this window renders it. Use a short heading when the ' +
  'answer has parts, a bullet list when you are naming several things, and a table when ' +
  'comparing values across items. A one-line answer stays one line — structure is for answers ' +
  'that need it, not decoration.'

/**
 * What a turn actually sends: the chosen voice, plus the formatting instruction that belongs to
 * the surface rather than to any one voice.
 *
 * Kept separate from `instructions` so "no voice" still means "no voice overlay" in the voice
 * data, while every turn still tells the model that this window renders markdown. The engine
 * appends `instructions` after the platform hint at API-call time, so this also carries the
 * instruction into an installed profile whose preserved `config.yaml` still says "no markdown".
 */
export function turnInstructions(id: string | null | undefined): string {
  const voice = instructions(id)
  return voice ? `${voice} ${ANSWER_FORMAT_GUIDANCE}` : ANSWER_FORMAT_GUIDANCE
}
