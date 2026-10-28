import type { CronJob } from '@shared/wire'

/**
 * What the last run did, in the operator's words.
 *
 * `state` on a recurring job stays `scheduled` after a failed run — the job is still going to
 * fire again — so the failure only exists in `last_status` / `latest_execution`. A card that
 * showed only the state would report a job that has been failing for a week as healthy.
 */
export interface JobRunStatus {
  label: string
  tone: 'ok' | 'warn' | 'danger' | 'neutral'
}

export function jobRunStatus(job: CronJob): JobRunStatus | null {
  const latest = job.latest_execution?.status
  if (latest === 'completed') return { label: 'Last run worked', tone: 'ok' }
  if (latest === 'failed') return { label: 'Last run failed', tone: 'danger' }
  if (latest === 'running' || latest === 'claimed') return { label: 'Running now', tone: 'warn' }
  if (latest === 'unknown') return { label: 'Last run interrupted', tone: 'warn' }

  if (job.last_status === 'ok') return { label: 'Last run worked', tone: 'ok' }
  if (job.last_status === 'error') return { label: 'Last run failed', tone: 'danger' }
  if (job.last_status === 'delivery_failed') {
    return { label: 'Last run worked; delivery failed', tone: 'warn' }
  }
  if (job.last_status === 'blocked_config') return { label: 'Blocked by settings', tone: 'warn' }
  if (job.last_status) return { label: `Last run: ${job.last_status}`, tone: 'neutral' }
  return null
}

/** Whether there is an output file worth offering: a run happened. */
export function hasRunOutput(job: CronJob): boolean {
  return Boolean(job.last_run_at || job.latest_execution)
}

/** `times: null` is forever; `completed` counts finished runs. */
export function repeatLine(job: CronJob): string | null {
  const times = job.repeat?.times ?? null
  if (times === null) return null
  const completed = job.repeat?.completed ?? 0
  if (times === 1) return completed > 0 ? 'ran once' : 'runs once'
  return completed > 0 ? `${completed} of ${times} runs` : `${times} runs at most`
}
