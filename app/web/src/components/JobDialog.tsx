import type { CronJob, UpdateJobRequest } from '@shared/wire'
import { useState } from 'react'
import { useApp } from '../state/app-context'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { Dialog } from '../ui/dialog'
import { Field, Input, Select, Textarea } from '../ui/field'
import {
  dayLabel,
  defaultOnceDate,
  defaultSchedule,
  describeSchedule,
  formatClock,
  fromScheduleText,
  isPastOneShot,
  scheduleFromJob,
  toScheduleText,
  weekdayName,
  type ScheduleChoice,
  type Weekday
} from './job-schedule'

/**
 * Create or edit a scheduled job.
 *
 * The schedule is built from the days and times an operator thinks in, and the engine's own
 * language comes out (`components/job-schedule.ts`). The raw text is never hidden: **Edit as
 * text** shows exactly what will be sent, and an existing job whose schedule this dialog cannot
 * represent opens there rather than being quietly rewritten.
 *
 * The dialog is mounted only while it is open, so its state is the job's, not the last job's.
 */
export function JobDialog({
  job,
  onClose,
  onSaved
}: {
  /** Undefined means a new job. */
  job?: CronJob
  onClose: () => void
  onSaved: () => void
}) {
  const { client } = useApp()
  const editing = Boolean(job)
  const initial = job ? scheduleFromJob(job) : null

  const [name, setName] = useState(job?.name ?? '')
  const [prompt, setPrompt] = useState(job?.prompt ?? '')
  const [choice, setChoice] = useState<ScheduleChoice | null>(
    initial ? initial.choice : defaultSchedule()
  )
  const [advanced, setAdvanced] = useState(Boolean(initial && initial.choice === null))
  const [text, setText] = useState(initial ? initial.text : toScheduleText(defaultSchedule()))
  const [repeat, setRepeat] = useState(job?.repeat?.times ? String(job.repeat.times) : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const scheduleText = advanced || !choice ? text : toScheduleText(choice)
  // What the schedule means now, in the same shape the dirty check compares against. A cron
  // expression and its builder phrase describe the same schedule; saving a prompt change must
  // not rewrite one into the other.
  const initialScheduleText = initial
    ? initial.choice
      ? toScheduleText(initial.choice)
      : initial.text
    : ''
  const summary = describeSchedule(scheduleText)
  const parsedText = advanced ? fromScheduleText(text) : null
  const once =
    (choice?.kind === 'once' ? choice : null) ??
    (parsedText?.kind === 'once' ? parsedText : null)
  const past = Boolean(once && isPastOneShot(once.date, once.time))
  const repeatNumber = repeat.trim() ? Number(repeat) : null
  const repeatValid = repeatNumber === null || (Number.isInteger(repeatNumber) && repeatNumber >= 1)

  const valid =
    prompt.trim().length > 0 &&
    scheduleText.trim().length > 0 &&
    (choice === null || choice.kind !== 'weekly' || choice.days.length > 0) &&
    (choice === null || choice.kind !== 'interval' || choice.every >= 1) &&
    !past &&
    repeatValid

  const updateChoice = (next: ScheduleChoice) => {
    setChoice(next)
    setText(toScheduleText(next))
  }

  const switchKind = (kind: ScheduleChoice['kind']) => {
    // In the advanced field the text is the truth; a kind button on a text it can read should
    // keep that reading rather than throw the operator's edit away.
    const base = advanced ? fromScheduleText(text) ?? choice : choice
    if (base?.kind === kind) {
      if (advanced) {
        setChoice(base)
        setText(toScheduleText(base))
        setAdvanced(false)
      }
      return
    }
    const time = base && 'time' in base ? base.time : '07:00'
    let next: ScheduleChoice
    if (kind === 'daily') next = { kind: 'daily', time }
    else if (kind === 'weekly') {
      next = { kind: 'weekly', days: base?.kind === 'weekly' ? base.days : [1], time }
    } else if (kind === 'monthly') next = { kind: 'monthly', day: 1, time }
    else if (kind === 'once') next = { kind: 'once', date: defaultOnceDate(), time }
    else next = { kind: 'interval', every: 2, unit: 'hours' }
    setAdvanced(false)
    updateChoice(next)
  }

  const toggleDay = (day: Weekday) => {
    if (choice?.kind !== 'weekly') return
    const days = choice.days.includes(day)
      ? choice.days.filter(value => value !== day)
      : [...choice.days, day]
    updateChoice({ ...choice, days: days.sort((a, b) => a - b) })
  }

  const submit = async () => {
    if (!valid || busy) return
    setBusy(true)
    setError(null)
    try {
      if (job) {
        const patch: UpdateJobRequest = {}
        const nextName = name.trim()
        if (nextName && nextName !== job.name) patch.name = nextName
        if (prompt.trim() !== (job.prompt ?? '').trim()) patch.prompt = prompt.trim()
        // Only when it changed: a relative form such as `in 30m` must not be re-evaluated, and
        // a cron expression must not be rewritten as a phrase by an unrelated edit.
        if (scheduleText !== initialScheduleText) patch.schedule = scheduleText
        const repeatBefore = job.repeat?.times ?? null
        if (!once && repeatNumber !== repeatBefore) patch.repeat = repeatNumber ?? 0
        if (Object.keys(patch).length === 0) {
          onClose()
          return
        }
        await client.updateJob(job.id, patch)
      } else {
        await client.createJob({
          name: name.trim() || derivedName(prompt),
          schedule: scheduleText,
          prompt: prompt.trim(),
          ...(repeatNumber !== null && !once ? { repeat: repeatNumber } : {})
        })
      }
      onSaved()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      title={editing ? 'Edit job' : 'Schedule a job'}
      description={
        editing
          ? 'Change the task, the schedule, or both. The job keeps its history.'
          : 'The assistant runs this on its own, in a fresh conversation, while the engine is running.'
      }
      onClose={() => {
        if (!busy) onClose()
      }}
      className="max-h-[calc(100vh-2rem)] w-[min(34rem,calc(100vw-2rem))] overflow-y-auto"
      error={error}
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy || !valid} onClick={() => void submit()}>
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Schedule job'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field
          label="What should happen?"
          hint="Each run starts a fresh conversation, so write it so it stands on its own."
        >
          <Textarea
            value={prompt}
            rows={3}
            autoFocus
            onChange={event => setPrompt(event.target.value)}
            placeholder="Summarise what is outstanding this week and what I should chase."
          />
        </Field>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-display text-xs text-ink-3">When</legend>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Schedule kind">
            {KINDS.map(kind => (
              <button
                key={kind.id}
                type="button"
                aria-pressed={choice?.kind === kind.id}
                onClick={() => switchKind(kind.id)}
                className={cn(
                  'rounded-lg border px-2.5 py-1 text-xs transition-colors',
                  choice?.kind === kind.id
                    ? 'border-accent bg-accent/10 text-ink'
                    : 'border-line text-ink-3 hover:border-line-strong'
                )}
              >
                {kind.label}
              </button>
            ))}
          </div>

          {!advanced && choice && (
            <ChoiceControls choice={choice} onChange={updateChoice} onToggleDay={toggleDay} />
          )}

          {advanced && (
            <Field
              label="Schedule text"
              hint="A phrase such as “every monday 9am”, an interval, a cron expression, or an ISO time."
            >
              <Input
                value={text}
                onChange={event => setText(event.target.value)}
                className="font-mono"
              />
            </Field>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className={cn('text-xs', summary.known ? 'text-ink-2' : 'text-ink-3')}>
              {summary.known ? summary.label : 'Custom schedule — the engine checks it on save.'}
            </p>
            {advanced ? (
              parsedText && (
                <button
                  type="button"
                  onClick={() => {
                    setChoice(parsedText)
                    setAdvanced(false)
                  }}
                  className="text-xs text-accent underline underline-offset-2 hover:brightness-110"
                >
                  Use the builder
                </button>
              )
            ) : (
              <button
                type="button"
                onClick={() => {
                  setText(scheduleText)
                  setAdvanced(true)
                }}
                className="text-xs text-accent underline underline-offset-2 hover:brightness-110"
              >
                Edit as text
              </button>
            )}
          </div>

          {past && once && (
            <p className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
              {`${formatClock(once.time)} on ${once.date} has already passed. Pick a later time.`}
            </p>
          )}

          <p className="text-xs text-ink-3">
            Times are the assistant’s clock — this machine’s, unless a time zone is configured.
          </p>
        </fieldset>

        <Field
          label="Name"
          hint={editing ? undefined : 'Optional. Left blank, it is taken from the first words of the task.'}
        >
          <Input
            value={name}
            onChange={event => setName(event.target.value)}
            placeholder={derivedName(prompt) || 'Monday briefing'}
          />
        </Field>

        {!once && (
          <Field label="Stop after" hint="Leave blank to run indefinitely.">
            <div className="flex items-center gap-2">
              <Input
                value={repeat}
                inputMode="numeric"
                onChange={event => setRepeat(event.target.value.replace(/[^0-9]/g, ''))}
                placeholder="∞"
                className="w-24 font-mono"
                aria-label="Stop after this many runs"
              />
              <span className="text-xs text-ink-3">runs</span>
            </div>
          </Field>
        )}
      </div>
    </Dialog>
  )
}

const KINDS: { id: ScheduleChoice['kind']; label: string }[] = [
  { id: 'daily', label: 'Daily' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'monthly', label: 'Monthly' },
  { id: 'once', label: 'Once' },
  { id: 'interval', label: 'Every N' }
]

const WEEKDAYS: Weekday[] = [1, 2, 3, 4, 5, 6, 7]

function ChoiceControls({
  choice,
  onChange,
  onToggleDay
}: {
  choice: ScheduleChoice
  onChange: (choice: ScheduleChoice) => void
  onToggleDay: (day: Weekday) => void
}) {
  if (choice.kind === 'interval') {
    return (
      <div className="flex items-end gap-2">
        <Field label="Every" className="w-24">
          <Input
            value={String(choice.every)}
            inputMode="numeric"
            aria-label="Interval"
            onChange={event => {
              const every = Number(event.target.value.replace(/[^0-9]/g, '') || '0')
              onChange({ ...choice, every })
            }}
            className="font-mono"
          />
        </Field>
        <Field label="Unit" className="w-32">
          <Select
            value={choice.unit}
            onChange={event =>
              onChange({ ...choice, unit: event.target.value as 'minutes' | 'hours' })
            }
          >
            <option value="minutes">minutes</option>
            <option value="hours">hours</option>
          </Select>
        </Field>
      </div>
    )
  }

  if (choice.kind === 'weekly') {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Days">
          {WEEKDAYS.map(day => (
            <button
              key={day}
              type="button"
              aria-pressed={choice.days.includes(day)}
              aria-label={weekdayName(day).replace(/^./, letter => letter.toUpperCase())}
              onClick={() => onToggleDay(day)}
              className={cn(
                'size-8 rounded-lg border text-xs transition-colors',
                choice.days.includes(day)
                  ? 'border-accent bg-accent/10 text-ink'
                  : 'border-line text-ink-3 hover:border-line-strong'
              )}
            >
              {dayLabel(day)}
            </button>
          ))}
        </div>
        <TimeField time={choice.time} onChange={time => onChange({ ...choice, time })} />
      </div>
    )
  }

  if (choice.kind === 'monthly') {
    return (
      <div className="flex items-end gap-2">
        <Field label="On day" className="w-32">
          <Select
            value={String(choice.day)}
            onChange={event => onChange({ ...choice, day: Number(event.target.value) })}
          >
            {Array.from({ length: 31 }, (_, index) => index + 1).map(day => (
              <option key={day} value={day}>
                {day}
              </option>
            ))}
          </Select>
        </Field>
        <TimeField time={choice.time} onChange={time => onChange({ ...choice, time })} />
        <p className="text-xs text-ink-3">A month without this day is skipped.</p>
      </div>
    )
  }

  if (choice.kind === 'once') {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-end gap-2">
          <Field label="On" className="flex-1">
            <Input
              type="date"
              value={choice.date}
              onChange={event => onChange({ ...choice, date: event.target.value })}
            />
          </Field>
          <TimeField time={choice.time} onChange={time => onChange({ ...choice, time })} />
        </div>
        <p className="text-xs text-ink-3">The job runs once and then stops.</p>
      </div>
    )
  }

  return <TimeField time={choice.time} onChange={time => onChange({ ...choice, time })} />
}

function TimeField({ time, onChange }: { time: string; onChange: (time: string) => void }) {
  return (
    <Field label="At" className="w-32">
      <Input type="time" value={time} onChange={event => onChange(event.target.value)} />
    </Field>
  )
}

/** The name the engine would have made from the prompt, for the placeholder. */
function derivedName(prompt: string): string {
  const line = (prompt.trim().split('\n')[0] ?? '').replace(/\s+/g, ' ').trim()
  return line.length > 60 ? `${line.slice(0, 57).trimEnd()}…` : line
}
