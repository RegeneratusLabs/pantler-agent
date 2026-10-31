/**
 * The schedule builder's one job is to say what the engine will do without making the operator
 * learn cron. These tests pin both halves of that: the text we generate must be a form the
 * engine's parser accepts (`cron/jobs.py`), and the parser here must refuse anything it cannot
 * represent exactly, because the dialog opens refusals in the advanced field rather than
 * rewriting them.
 */

import { describe, expect, it } from 'vitest'
import type { CronJob } from '@shared/wire'
import {
  choiceFromIso,
  defaultOnceDate,
  describeChoice,
  describeSchedule,
  formatClock,
  fromScheduleText,
  isPastOneShot,
  isoWithOffset,
  scheduleFromJob,
  toScheduleText
} from './job-schedule'

describe('toScheduleText', () => {
  it('writes the engine’s daily and weekly phrases', () => {
    expect(toScheduleText({ kind: 'daily', time: '07:00' })).toBe('every day at 07:00')
    expect(toScheduleText({ kind: 'weekly', days: [1], time: '07:00' })).toBe(
      'every monday at 07:00'
    )
    expect(toScheduleText({ kind: 'weekly', days: [1, 3], time: '07:00' })).toBe(
      'every monday, wednesday at 07:00'
    )
    expect(toScheduleText({ kind: 'weekly', days: [1, 2, 3, 4, 5], time: '09:30' })).toBe(
      'weekdays at 09:30'
    )
    expect(toScheduleText({ kind: 'weekly', days: [6, 7], time: '10:00' })).toBe(
      'weekends at 10:00'
    )
  })

  it('treats every day as daily, and writes nothing when no day is chosen', () => {
    expect(toScheduleText({ kind: 'weekly', days: [1, 2, 3, 4, 5, 6, 7], time: '07:00' })).toBe(
      'every day at 07:00'
    )
    expect(toScheduleText({ kind: 'weekly', days: [], time: '07:00' })).toBe('')
  })

  it('writes a monthly cron and an interval', () => {
    expect(toScheduleText({ kind: 'monthly', day: 15, time: '09:00' })).toBe('0 9 15 * *')
    expect(toScheduleText({ kind: 'interval', every: 30, unit: 'minutes' })).toBe('every 30m')
    expect(toScheduleText({ kind: 'interval', every: 2, unit: 'hours' })).toBe('every 2h')
  })

  it('writes a one-shot with the offset that applies at that date', () => {
    const text = toScheduleText({ kind: 'once', date: '2026-11-03', time: '07:00' })
    expect(text).toMatch(/^2026-11-03T07:00:00[+-]\d{2}:\d{2}$/)
    // The same wall time, not the same UTC hour: the offset preserves the instant.
    const [hour, minute] = [7, 0]
    const expected = new Date(2026, 10, 3, hour, minute, 0, 0)
    expect(new Date(text).getTime()).toBe(expected.getTime())
  })
})

describe('fromScheduleText', () => {
  it('reads the engine phrases the builder itself writes', () => {
    expect(fromScheduleText('every day at 07:00')).toEqual({ kind: 'daily', time: '07:00' })
    expect(fromScheduleText('every monday at 07:00')).toEqual({
      kind: 'weekly',
      days: [1],
      time: '07:00'
    })
    expect(fromScheduleText('every monday, wednesday at 07:00')).toEqual({
      kind: 'weekly',
      days: [1, 3],
      time: '07:00'
    })
    expect(fromScheduleText('weekdays at 09:30')).toEqual({
      kind: 'weekly',
      days: [1, 2, 3, 4, 5],
      time: '09:30'
    })
    expect(fromScheduleText('weekends at 10:00')).toEqual({
      kind: 'weekly',
      days: [6, 7],
      time: '10:00'
    })
  })

  it('reads what the assistant writes (the tool schema’s examples)', () => {
    expect(fromScheduleText('every monday 9am')).toEqual({ kind: 'weekly', days: [1], time: '09:00' })
    expect(fromScheduleText('weekdays at 9am')).toEqual({
      kind: 'weekly',
      days: [1, 2, 3, 4, 5],
      time: '09:00'
    })
    expect(fromScheduleText('every 2h')).toEqual({ kind: 'interval', every: 2, unit: 'hours' })
    expect(fromScheduleText('30m')).toEqual({ kind: 'interval', every: 30, unit: 'minutes' })
    // The engine writes `every 2h` back as `every 120m`; the builder reads it as two hours.
    expect(fromScheduleText('every 120m')).toEqual({ kind: 'interval', every: 2, unit: 'hours' })
  })

  it('reads the simple cron shapes and refuses the rest', () => {
    expect(fromScheduleText('0 7 * * *')).toEqual({ kind: 'daily', time: '07:00' })
    expect(fromScheduleText('0 7 * * 1')).toEqual({ kind: 'weekly', days: [1], time: '07:00' })
    expect(fromScheduleText('0 7 * * 0,6')).toEqual({ kind: 'weekly', days: [6, 7], time: '07:00' })
    expect(fromScheduleText('0 7 * * 1-5')).toEqual({
      kind: 'weekly',
      days: [1, 2, 3, 4, 5],
      time: '07:00'
    })
    expect(fromScheduleText('0 9 15 * *')).toEqual({ kind: 'monthly', day: 15, time: '09:00' })

    // Anything whose meaning is not one of the shapes above is left to the engine and never
    // paraphrased: a second-Tuesday expression, a step, a named month.
    expect(fromScheduleText('0 9 8-14 * 2')).toBeNull()
    expect(fromScheduleText('*/15 9-17 * * 1-5')).toBeNull()
    expect(fromScheduleText('0 9 * JAN *')).toBeNull()
  })

  it('reads a one-shot the engine wrote back, and refuses a relative one', () => {
    expect(fromScheduleText('once at 2026-11-03 07:00')).toEqual({
      kind: 'once',
      date: '2026-11-03',
      time: '07:00'
    })
    expect(fromScheduleText('in 30m')).toBeNull()
    expect(fromScheduleText('once in 30m')).toBeNull()
  })

  it('refuses text with no exact mapping', () => {
    expect(fromScheduleText('every second tuesday at 9am')).toBeNull()
    expect(fromScheduleText('')).toBeNull()
    expect(fromScheduleText('sometimes')).toBeNull()
  })
})

describe('describeSchedule', () => {
  it('says the same thing in English', () => {
    expect(describeSchedule('every monday at 07:00')).toEqual({
      label: 'Every Monday at 7:00 am',
      known: true
    })
    expect(describeSchedule('every monday, wednesday at 07:00').label).toBe(
      'Every Mon, Wed at 7:00 am'
    )
    expect(describeSchedule('weekdays at 09:30').label).toBe('Every weekday at 9:30 am')
    expect(describeSchedule('weekends at 10:00').label).toBe('Weekends at 10:00 am')
    expect(describeSchedule('0 9 15 * *').label).toBe('Monthly on day 15 at 9:00 am')
    expect(describeSchedule('every 2h').label).toBe('Every 2 hours')
    expect(describeSchedule('every 30m').label).toBe('Every 30 minutes')
    expect(describeSchedule('once at 2026-11-03 07:00').label).toBe(
      'Once on Tue 3 Nov 2026 at 7:00 am'
    )
  })

  it('shows an unknown schedule as itself, marked unknown', () => {
    expect(describeSchedule('0 9 8-14 * 2')).toEqual({ label: '0 9 8-14 * 2', known: false })
    expect(describeSchedule('')).toEqual({ label: 'no schedule', known: false })
  })

  it('formats clocks the way the cards speak', () => {
    expect(formatClock('07:05')).toBe('7:05 am')
    expect(formatClock('12:00')).toBe('12:00 pm')
    expect(formatClock('00:30')).toBe('12:30 am')
    expect(formatClock('nonsense')).toBe('nonsense')
  })

  it('describes each choice', () => {
    expect(describeChoice({ kind: 'daily', time: '07:00' })).toBe('Every day at 7:00 am')
    expect(describeChoice({ kind: 'weekly', days: [3], time: '08:00' })).toBe(
      'Every Wednesday at 8:00 am'
    )
    expect(describeChoice({ kind: 'weekly', days: [], time: '08:00' })).toBe('No days chosen')
  })
})

describe('scheduleFromJob', () => {
  const job = (extra: Partial<CronJob>): CronJob => ({ id: 'abcdef123456', name: 'test', ...extra })

  it('prefers the operator’s own words, even an unusual phrase it can read', () => {
    expect(
      scheduleFromJob(job({ schedule_display: 'every monday 9am' })).choice
    ).toEqual({ kind: 'weekly', days: [1], time: '09:00' })
  })

  it('falls back to the structured schedule for an unreadable display', () => {
    // A relative one-shot: the display cannot be re-sent (it would move), but `run_at` can.
    const runAt = '2026-11-03T07:00:00+10:00'
    const local = new Date(runAt)
    const form = scheduleFromJob(
      job({ schedule_display: 'once in 30m', schedule: { kind: 'once', run_at: runAt } })
    )
    expect(form.choice).toEqual({
      kind: 'once',
      date: `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, '0')}-${String(local.getDate()).padStart(2, '0')}`,
      time: `${String(local.getHours()).padStart(2, '0')}:${String(local.getMinutes()).padStart(2, '0')}`
    })
    expect(form.text).toMatch(/^2026-11-0[23]T\d{2}:\d{2}:00[+-]\d{2}:\d{2}$/)
  })

  it('reads an interval from its minutes and a cron from its expression', () => {
    expect(
      scheduleFromJob(job({ schedule_display: 'every 2h', schedule: { kind: 'interval', minutes: 120 } }))
        .choice
    ).toEqual({ kind: 'interval', every: 2, unit: 'hours' })
    expect(
      scheduleFromJob(job({ schedule_display: '0 7 * * 1', schedule: { kind: 'cron', expr: '0 7 * * 1' } }))
        .choice
    ).toEqual({ kind: 'weekly', days: [1], time: '07:00' })
  })

  it('keeps an unrepresentable schedule as text and no builder choice', () => {
    const form = scheduleFromJob(
      job({ schedule_display: '0 9 8-14 * 2', schedule: { kind: 'cron', expr: '0 9 8-14 * 2' } })
    )
    expect(form.choice).toBeNull()
    expect(form.text).toBe('0 9 8-14 * 2')
  })
})

describe('one-shot dates', () => {
  it('defaults to tomorrow', () => {
    const now = new Date(2026, 9, 27, 9, 0)
    expect(defaultOnceDate(now)).toBe('2026-10-28')
  })

  it('knows when the chosen time has already passed', () => {
    const now = new Date(2026, 9, 27, 9, 0)
    expect(isPastOneShot('2026-10-26', '09:00', now)).toBe(true)
    expect(isPastOneShot('2026-10-27', '09:00', now)).toBe(false)
    expect(isPastOneShot('2026-10-27', '08:59', now)).toBe(true)
  })

  it('round-trips an instant through its ISO form', () => {
    const choice = { kind: 'once', date: '2026-11-03', time: '07:00' } as const
    const iso = isoWithOffset(choice.date, choice.time)
    expect(choiceFromIso(iso)).toEqual(choice)
  })
})
