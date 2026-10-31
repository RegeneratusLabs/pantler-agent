import { useState, type ReactNode } from 'react'
import type { ClarifyPrompt } from '../seam/reducer'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'

/** `respond_run` refuses an answer longer than this. */
const MAX_ANSWER = 16384

/**
 * The engine appends this on every non-local surface (`run_turn_runner.py`), because a messaging
 * client answers with plain text. A card has a real control, so the sentence is chat chrome, not
 * part of the question. Display-only: the question the engine holds is unchanged.
 */
const SKIP_HINT = '\nReply "skip" to skip this question.'

/** The question as a card should show it. */
export function questionText(question: string): string {
  return question.endsWith(SKIP_HINT) ? question.slice(0, -SKIP_HINT.length) : question
}

/** The engine parses a multi-select answer as a JSON array string (`clarify_tool._clean_answer`). */
export function multiAnswer(choices: string[]): string {
  return JSON.stringify(choices)
}

/**
 * A clarifying question, parked exactly like an approval.
 *
 * The engine asks one question at a time (up to five in one tool call, sequentially). The answer
 * is a plain string: a choice's exact label, free text, or — for multi-select — a JSON array of
 * labels. `clarify.settled` closes the card; a run that ends first expires it.
 */
export function ClarifyCard({
  prompt,
  onAnswer
}: {
  prompt: ClarifyPrompt
  /** Resolves true when the engine took the answer; false when it did not land. */
  onAnswer: (answer: string) => Promise<boolean>
}) {
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [other, setOther] = useState('')
  const [otherOpen, setOtherOpen] = useState(false)

  if (prompt.expired) {
    return (
      <Frame>
        <Header badge={<Badge tone="danger">not answered in time</Badge>} />
        <p className="text-sm text-ink-2">
          The run ended before this was answered, so the assistant moved on without it.
        </p>
      </Frame>
    )
  }

  if (prompt.settled) {
    return (
      <Frame>
        <Header badge={<Badge tone={sent ? 'ok' : 'neutral'}>{sent ? 'answered' : 'closed'}</Badge>} />
        <p className="text-sm text-ink-2">
          {sent
            ? `You answered: ${sent}`
            : 'The assistant moved on without an answer to this one.'}
        </p>
      </Frame>
    )
  }

  const question = questionText(prompt.question)
  const locked = busy || sent !== null
  const answerable = Boolean(prompt.promptId) && typeof prompt.executionGeneration === 'number'
  const multi = prompt.multiSelect && prompt.choices.length > 0
  const openEnded = prompt.choices.length === 0
  const showFreeText = openEnded || otherOpen || multi

  const send = async (value: string, label = value) => {
    const trimmed = value.trim()
    if (!trimmed || locked || !answerable) return
    setBusy(true)
    setError(null)
    try {
      const delivered = await onAnswer(trimmed)
      if (delivered) {
        setSent(label)
      } else {
        setError('That answer did not reach the assistant. Try again.')
      }
    } catch {
      setError('That answer did not reach the assistant. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (choice: string) => {
    setSelected(previous =>
      previous.includes(choice)
        ? previous.filter(item => item !== choice)
        : [...previous, choice]
    )
  }

  const sendMulti = () => {
    const chosen = prompt.choices.filter(choice => selected.includes(choice))
    const extra = other.trim()
    const answer = [...chosen, ...(extra ? [extra] : [])]
    if (answer.length === 0) return
    void send(multiAnswer(answer), answer.join(', '))
  }

  return (
    <Frame>
      <Header />
      <p className="whitespace-pre-wrap text-sm text-ink">{question}</p>
      <p className="text-xs text-ink-3">
        The assistant needs an answer before it can continue.
      </p>

      {!answerable && (
        <p className="text-xs text-warning">
          This question cannot be answered from here. Stop the run and ask again.
        </p>
      )}

      {answerable && prompt.choices.length > 0 && (
        <div
          className="flex flex-col gap-1.5"
          role={multi ? 'group' : undefined}
          aria-label={multi ? 'Choose one or more' : 'Choose one'}
        >
          {prompt.choices.map(choice => {
            const on = selected.includes(choice)
            return (
              <Button
                key={choice}
                variant={multi ? (on ? 'primary' : 'quiet') : 'secondary'}
                size="sm"
                disabled={locked}
                aria-pressed={multi ? on : undefined}
                className={cn(
                  'justify-start whitespace-normal text-left',
                  multi && on && 'border-accent'
                )}
                onClick={() => (multi ? toggle(choice) : void send(choice))}
              >
                {choice}
              </Button>
            )
          })}
        </div>
      )}

      {answerable && !multi && prompt.choices.length > 0 && (
        <Button
          variant="link"
          size="sm"
          disabled={locked}
          onClick={() => setOtherOpen(open => !open)}
        >
          {otherOpen ? 'Hide free text' : 'Something else'}
        </Button>
      )}

      {answerable && showFreeText && (
        <div className="flex flex-col gap-1.5">
          {(multi || openEnded) && (
            <span className="text-[0.68rem] text-ink-3">
              {multi ? 'Add your own, in addition to the choices above.' : 'Type your answer.'}
            </span>
          )}
          <textarea
            value={other}
            onChange={event => setOther(event.target.value)}
            maxLength={MAX_ANSWER}
            rows={openEnded ? 3 : 1}
            disabled={locked}
            aria-label="Your answer"
            placeholder="Type your answer"
            className={cn(
              'w-full resize-y rounded-lg border border-line bg-canvas px-2.5 py-2 text-sm text-ink',
              'placeholder:text-ink-disabled focus-visible:outline-2 focus-visible:outline-offset-2',
              'focus-visible:outline-accent disabled:opacity-50'
            )}
          />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={locked || (other.trim() === '' && (!multi || selected.length === 0))}
              onClick={() => (multi ? sendMulti() : void send(other))}
            >
              Send answer
            </Button>
            {multi && (
              <span className="text-[0.68rem] text-ink-3">
                {selected.length === 0 ? 'Pick one or more' : `${selected.length} selected`}
              </span>
            )}
            {openEnded && other.length > 0 && (
              <span className="text-[0.68rem] text-ink-3">
                {other.length}/{MAX_ANSWER}
              </span>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-xs text-danger">{error}</p>}
      {busy && <p className="text-[0.68rem] text-ink-3">Sending…</p>}
      {sent && !prompt.settled && (
        <p className="text-[0.68rem] text-ink-3">Answer sent — waiting for the assistant.</p>
      )}
    </Frame>
  )
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 rounded-card border border-line bg-surface/50 p-3.5">
      {children}
    </section>
  )
}

function Header({ badge }: { badge?: ReactNode }) {
  return (
    <header className="flex items-center gap-2.5">
      <h3 className="flex-1 text-display text-xs text-ink-3">Question</h3>
      {badge}
    </header>
  )
}
