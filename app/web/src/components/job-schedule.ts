import type { CronJob } from '@shared/wire'

/**
 * The schedule language of a job, in the operator's terms.
 *
 * The engine already accepts plain English (`cron/jobs.py` `parse_schedule` at the pin):
 * `every monday 9am`, `weekdays at 9am`, `weekends at 10am`, `every 2h`, `30m`, `in 30m`, an
 * ISO one-shot, or a five-field cron expression. The old dialog asked for the hardest one.
 * This module goes the other way: a small set of choices goes in, the engine's own form comes
 * out, and anything it cannot represent is left alone rather than rewritten.
 *
 * Two rules keep it honest:
 *
 *   - **Nothing is guessed.** `fromScheduleText` returns `null` for any text whose meaning is
 *     not exactly one of the shapes below. The dialog opens those in the advanced field, so a
 *     schedule the operator set in another tool survives an edit untouched.
 *   - **Times are text until the engine sees them.** A recurring phrase carries no zone; it
 *     runs on the assistant's clock. A one-shot is written with the browser's UTC offset at
 *     that date, so the instant is exact and the engine's display keeps the wall time chosen.
 */

export type Weekday = 1 | 2 | 3 | 4 | 5 | 6 | 7

/** `HH:MM`, 24-hour, as a native `<input type="time">` produces. */
export type Time = string

export type ScheduleChoice =
  | { kind: 'daily'; time: Time }
  | { kind: 'weekly'; days: Weekday[]; time: Time }
  | { kind: 'monthly'; day: number; time: Time }
  /** `date` is `YYYY-MM-DD` in the operator's own zone. */
  | { kind: 'once'; date: string; time: Time }
  | { kind: 'interval'; every: number; unit: 'minutes' | 'hours' }

const DAY_NAMES = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday'
] as const
const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
const MONTH_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
] as const

/** The name a day chip shows. */
export function dayLabel(day: Weekday): string {
  return DAY_SHORT[day - 1]
}

export function weekdayName(day: Weekday): string {
  return DAY_NAMES[day - 1]
}

export function defaultSchedule(): ScheduleChoice {
  return { kind: 'weekly', days: [1], time: '07:00' }
}

// ------------------------------------------------------------------- clock

/** `07:05` → `7:05 am`; an unparseable value is returned as written, never invented. */
export function formatClock(time: Time): string {
  const parts = clockParts(time)
  if (!parts) return time
  const [hour, minute] = parts
  const suffix = hour < 12 ? 'am' : 'pm'
  const twelve = hour % 12 === 0 ? 12 : hour % 12
  return `${twelve}:${String(minute).padStart(2, '0')} ${suffix}`
}

function clockParts(time: Time): [number, number] | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim())
  if (!match) return null
  const hour = Number(match[1])
  const minute = Number(match[2])
  if (hour > 23 || minute > 59) return null
  return [hour, minute]
}

/** Accepts what a person types in the advanced field: `9am`, `9:30 pm`, `14:00`, `noon`. */
export function parseClock(text: string): Time | null {
  const raw = text.trim().toLowerCase().replace(/\s+/g, '')
  if (!raw) return null
  if (raw === 'noon' || raw === 'midday') return '12:00'
  if (raw === 'midnight') return '00:00'
  const match = /^(\d{1,2})(?::(\d{2}))?(am|pm)?$/.exec(raw)
  if (!match) return null
  let hour = Number(match[1])
  const minute = Number(match[2] ?? 0)
  const meridiem = match[3]
  if (meridiem) {
    if (hour < 1 || hour > 12) return null
    hour = (hour % 12) + (meridiem === 'pm' ? 12 : 0)
  }
  if (hour > 23 || minute > 59) return null
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

// ------------------------------------------------------------------ choice

/** The engine's own string for a choice. Empty when a weekly choice has no days. */
export function toScheduleText(choice: ScheduleChoice): string {
  switch (choice.kind) {
    case 'daily':
      return `every day at ${choice.time}`
    case 'weekly': {
      const days = normalizeDays(choice.days)
      if (days.length === 0) return ''
      if (days.length === 7) return `every day at ${choice.time}`
      if (sameDays(days, [1, 2, 3, 4, 5])) return `weekdays at ${choice.time}`
      if (sameDays(days, [6, 7])) return `weekends at ${choice.time}`
      return `every ${days.map(weekdayName).join(', ')} at ${choice.time}`
    }
    case 'monthly':
      {
        const parts = clockParts(choice.time)
        if (!parts) return ''
        return `${parts[1]} ${parts[0]} ${choice.day} * *`
      }
    case 'once':
      return isoWithOffset(choice.date, choice.time)
    case 'interval':
      return `every ${Math.max(1, Math.round(choice.every))}${choice.unit === 'minutes' ? 'm' : 'h'}`
  }
}

function normalizeDays(days: Weekday[]): Weekday[] {
  return [...new Set(days)].filter(day => day >= 1 && day <= 7).sort((a, b) => a - b) as Weekday[]
}

function sameDays(a: Weekday[], b: Weekday[]): boolean {
  return a.length === b.length && a.every((day, index) => day === b[index])
}

// ------------------------------------------------------------------- parse

/**
 * The builder state for a schedule text, or `null` when this module cannot represent it
 * exactly. Callers must treat `null` as "leave the text alone", never as "guess".
 */
export function fromScheduleText(text: string): ScheduleChoice | null {
  const value = text.trim()
  if (!value) return null
  return parseInterval(value) ?? parseOnce(value) ?? parseCron(value) ?? parsePhrase(value)
}

function parseInterval(text: string): ScheduleChoice | null {
  const lower = text.toLowerCase()
  const match =
    /^every\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$/.exec(lower) ??
    /^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$/.exec(lower)
  if (!match) return null
  const every = Number(match[1])
  if (!Number.isFinite(every) || every <= 0) return null
  // The engine renders `every 2h` back as `every 120m`; two hours is the friendlier reading.
  if (match[2].startsWith('h')) return { kind: 'interval', every, unit: 'hours' }
  if (every >= 60 && every % 60 === 0) {
    return { kind: 'interval', every: every / 60, unit: 'hours' }
  }
  return { kind: 'interval', every, unit: 'minutes' }
}

function parseOnce(text: string): ScheduleChoice | null {
  // The engine's own display for a one-shot: "once at 2026-11-03 07:00".
  const display = /^once\s+at\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})$/i.exec(text.trim())
  if (display) {
    return { kind: 'once', date: display[1], time: `${display[2]}:${display[3]}` }
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text.trim())) return null
  return choiceFromIso(text.trim())
}

function parseCron(text: string): ScheduleChoice | null {
  const parts = text.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const [minuteText, hourText, dayOfMonth, month, dayOfWeek] = parts
  if (!/^\d{1,2}$/.test(minuteText) || !/^\d{1,2}$/.test(hourText)) return null
  if (month !== '*') return null
  const minute = Number(minuteText)
  const hour = Number(hourText)
  if (minute > 59 || hour > 23) return null
  const time = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`

  if (dayOfMonth === '*' && dayOfWeek === '*') return { kind: 'daily', time }
  if (dayOfMonth === '*') {
    const days = parseDayOfWeek(dayOfWeek)
    return days ? { kind: 'weekly', days, time } : null
  }
  if (/^\d{1,2}$/.test(dayOfMonth) && dayOfWeek === '*') {
    const day = Number(dayOfMonth)
    return day >= 1 && day <= 31 ? { kind: 'monthly', day, time } : null
  }
  return null
}

function parseDayOfWeek(field: string): Weekday[] | null {
  if (field === '*') return [1, 2, 3, 4, 5, 6, 7]
  const days: Weekday[] = []
  for (const part of field.split(',')) {
    const range = /^(\d)-(\d)$/.exec(part)
    if (range) {
      const from = Number(range[1])
      const to = Number(range[2])
      if (from > to) return null
      for (let day = from; day <= to; day += 1) {
        const mapped = cronDay(day)
        if (mapped === null) return null
        days.push(mapped)
      }
      continue
    }
    if (!/^\d$/.test(part)) return null
    const mapped = cronDay(Number(part))
    if (mapped === null) return null
    days.push(mapped)
  }
  return normalizeDays(days)
}

function cronDay(day: number): Weekday | null {
  if (day === 0 || day === 7) return 7
  if (day >= 1 && day <= 6) return day as Weekday
  return null
}

function parsePhrase(text: string): ScheduleChoice | null {
  const dayAlt =
    'monday|tuesday|wednesday|thursday|friday|saturday|sunday|' +
    'mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun'
  const specAlt = 'day|daily|everyday|weekday|weekdays|weekend|weekends'
  const dayList = `(?:${dayAlt})(?:\\s*(?:,|and)\\s*(?:${dayAlt}))*`
  const match = new RegExp(
    `^(?:every\\s+)?((?:${specAlt})|(?:${dayList}))\\s+(?:at\\s+)?(.+)$`
  ).exec(text.trim().toLowerCase())
  if (!match) return null
  const time = parseClock(match[2])
  if (!time) return null
  const days = phraseDays(match[1])
  if (days === null) return null
  if (days === 'daily') return { kind: 'daily', time }
  return { kind: 'weekly', days, time }
}

function phraseDays(spec: string): Weekday[] | 'daily' | null {
  const lower = spec.trim().toLowerCase()
  if (lower === 'day' || lower === 'daily' || lower === 'everyday') return 'daily'
  if (lower === 'weekday' || lower === 'weekdays') return [1, 2, 3, 4, 5]
  if (lower === 'weekend' || lower === 'weekends') return [6, 7]
  const days: Weekday[] = []
  for (const token of lower.split(/\s*(?:,|and)\s*/).filter(Boolean)) {
    const day = dayFromName(token)
    if (day === null) return null
    days.push(day)
  }
  return days.length > 0 ? normalizeDays(days) : null
}

function dayFromName(token: string): Weekday | null {
  const aliases: Record<string, Weekday> = {
    monday: 1,
    mon: 1,
    tuesday: 2,
    tue: 2,
    tues: 2,
    wednesday: 3,
    wed: 3,
    weds: 3,
    thursday: 4,
    thu: 4,
    thur: 4,
    thurs: 4,
    friday: 5,
    fri: 5,
    saturday: 6,
    sat: 6,
    sunday: 7,
    sun: 7
  }
  return aliases[token] ?? null
}

// ---------------------------------------------------------------- describe

export interface ScheduleDescription {
  /** The English line. For an unknown text this is the text itself. */
  label: string
  /** False when the label is only the raw schedule, so the caller can set it in mono. */
  known: boolean
}

/** What a card says about a schedule. Unknown text is shown as itself, never paraphrased. */
export function describeSchedule(text: string): ScheduleDescription {
  const choice = fromScheduleText(text)
  if (!choice) return { label: text.trim() || 'no schedule', known: false }
  return { label: describeChoice(choice), known: true }
}

export function describeChoice(choice: ScheduleChoice): string {
  switch (choice.kind) {
    case 'daily':
      return `Every day at ${formatClock(choice.time)}`
    case 'weekly': {
      const days = normalizeDays(choice.days)
      if (days.length === 0) return 'No days chosen'
      if (days.length === 7) return `Every day at ${formatClock(choice.time)}`
      if (sameDays(days, [1, 2, 3, 4, 5])) return `Every weekday at ${formatClock(choice.time)}`
      if (sameDays(days, [6, 7])) return `Weekends at ${formatClock(choice.time)}`
      const names =
        days.length === 1
          ? [weekdayName(days[0]).replace(/^./, letter => letter.toUpperCase())]
          : days.map(dayLabel)
      return `Every ${names.join(', ')} at ${formatClock(choice.time)}`
    }
    case 'monthly':
      return `Monthly on day ${choice.day} at ${formatClock(choice.time)}`
    case 'once':
      return `Once on ${formatDate(choice.date)} at ${formatClock(choice.time)}`
    case 'interval': {
      const unit = choice.unit === 'hours' ? 'hour' : 'minute'
      return `Every ${choice.every} ${unit}${choice.every === 1 ? '' : 's'}`
    }
  }
}

/** `2026-11-03` → `Tue 3 Nov 2026`, computed from the date itself (no zone shift). */
export function formatDate(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim())
  if (!match) return date
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12) return date
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay()
  const name = weekday === 0 ? 'Sun' : DAY_SHORT[weekday - 1]
  return `${name} ${day} ${MONTH_SHORT[month - 1]} ${year}`
}

// --------------------------------------------------------------------- job

export interface JobScheduleForm {
  /** The text the advanced field shows: the job's own words where they are usable. */
  text: string
  /** The builder state, or null when only the text can represent it. */
  choice: ScheduleChoice | null
}

/**
 * The editable form of a job's schedule.
 *
 * `schedule_display` is preferred because it is what the operator or the assistant actually
 * wrote. When it cannot be parsed, the structured record supplies an equivalent: a one-shot's
 * absolute `run_at` (so a relative `in 30m` never moves), an interval's minutes, a cron's
 * expression.
 */
export function scheduleFromJob(job: CronJob): JobScheduleForm {
  const display = typeof job.schedule_display === 'string' ? job.schedule_display.trim() : ''
  if (display) {
    const choice = fromScheduleText(display)
    if (choice) return { text: display, choice }
  }

  const schedule = job.schedule
  if (schedule?.kind === 'once' && typeof schedule.run_at === 'string') {
    const choice = choiceFromIso(schedule.run_at)
    if (choice) return { text: toScheduleText(choice), choice }
  }
  if (schedule?.kind === 'interval' && typeof schedule.minutes === 'number' && schedule.minutes > 0) {
    const choice =
      schedule.minutes % 60 === 0
        ? ({ kind: 'interval', every: schedule.minutes / 60, unit: 'hours' } as const)
        : ({ kind: 'interval', every: schedule.minutes, unit: 'minutes' } as const)
    return { text: toScheduleText(choice), choice }
  }
  if (schedule?.kind === 'cron' && typeof schedule.expr === 'string') {
    return { text: schedule.expr, choice: fromScheduleText(schedule.expr) }
  }
  return { text: display, choice: null }
}

// ------------------------------------------------------------------ dates

/** A one-shot's ISO text, with the offset that applies at that date. */
export function isoWithOffset(date: string, time: Time): string {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  const parts = clockParts(time)
  if (!dateMatch || !parts) return ''
  const local = new Date(
    Number(dateMatch[1]),
    Number(dateMatch[2]) - 1,
    Number(dateMatch[3]),
    parts[0],
    parts[1],
    0,
    0
  )
  if (Number.isNaN(local.getTime())) return ''
  return `${localDate(local)}T${pad(parts[0])}:${pad(parts[1])}:00${offsetText(local)}`
}

/** The browser's local reading of an absolute instant, as a builder choice. */
export function choiceFromIso(iso: string): ScheduleChoice | null {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return { kind: 'once', date: localDate(date), time: `${pad(date.getHours())}:${pad(date.getMinutes())}` }
}

/** Tomorrow, in the operator's own zone: the default for a new one-shot. */
export function defaultOnceDate(now: Date = new Date()): string {
  const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return localDate(date)
}

/** True when the chosen wall time is already behind us; the engine refuses such a one-shot. */
export function isPastOneShot(date: string, time: Time, now: Date = new Date()): boolean {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  const parts = clockParts(time)
  if (!dateMatch || !parts) return false
  const chosen = new Date(
    Number(dateMatch[1]),
    Number(dateMatch[2]) - 1,
    Number(dateMatch[3]),
    parts[0],
    parts[1],
    0,
    0
  )
  return chosen.getTime() < now.getTime()
}

function localDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function offsetText(date: Date): string {
  const offset = -date.getTimezoneOffset()
  const sign = offset < 0 ? '-' : '+'
  const absolute = Math.abs(offset)
  return `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}
