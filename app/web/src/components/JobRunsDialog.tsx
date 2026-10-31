import type { CronJob } from '@shared/wire'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { qk, useApp } from '../state/app-context'
import { toMillis } from '../shell/sessions'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { Dialog } from '../ui/dialog'
import { Spinner } from '../ui/spinner'
import { jobRunStatus } from './job-status'
import { Markdown } from './Markdown'

/**
 * What a job produced.
 *
 * The gateway's `/api/jobs` has no per-run read; the BFF reads the active profile's own
 * `cron/output/<job_id>/` directory (`app/server/job_runs.py`). The dialog is mounted only while
 * it is open, so switching jobs never shows one job's output under another's name.
 */
export function JobRunsDialog({ job, onClose }: { job: CronJob; onClose: () => void }) {
  const { bff } = useApp()
  const [picked, setPicked] = useState<string | null>(null)

  const runs = useQuery({
    queryKey: qk.jobRuns(job.id),
    queryFn: ({ signal }) => bff.jobRuns(job.id, signal)
  })

  const list = runs.data?.runs ?? []
  const activeId = picked ?? list[0]?.id ?? null
  const active = list.find(run => run.id === activeId) ?? null

  const detail = useQuery({
    queryKey: qk.jobRun(job.id, activeId ?? ''),
    queryFn: ({ signal }) => bff.jobRun(job.id, activeId ?? '', signal),
    enabled: activeId !== null
  })

  const status = jobRunStatus(job)

  return (
    <Dialog
      open
      title={job.name}
      description="What this job produced. The assistant keeps the recent runs, so older output may be gone."
      onClose={onClose}
      className="max-h-[calc(100vh-2rem)] w-[min(46rem,calc(100vw-2rem))] overflow-y-auto"
      footer={
        <>
          <Button
            variant="ghost"
            onClick={() => {
              void runs.refetch()
              if (activeId) void detail.refetch()
            }}
            disabled={runs.isFetching}
          >
            Refresh
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
          {status && <Badge tone={status.tone}>{status.label}</Badge>}
          {job.last_run_at && <span>last {formatRunAt(job.last_run_at)}</span>}
          {typeof job.failure_streak === 'number' && job.failure_streak > 1 && (
            <span className="text-danger">{job.failure_streak} failures in a row</span>
          )}
        </div>

        {job.last_error && (
          <p className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs whitespace-pre-wrap text-danger">
            {job.last_error}
          </p>
        )}

        {runs.isPending && <Spinner label="Reading run output…" />}

        {runs.error && (
          <p className="text-sm text-ink-2">
            Could not read this job’s output from this machine. The job itself is unaffected.
          </p>
        )}

        {!runs.isPending && !runs.error && runs.data && !runs.data.available && (
          <p className="text-sm text-ink-2">
            {runs.data.reason ?? 'This machine has no profile to read run output from.'}
          </p>
        )}

        {!runs.isPending && !runs.error && runs.data?.available && list.length === 0 && (
          <p className="text-sm text-ink-2">
            No runs are kept for this job yet. Run it now, or wait for its next run.
          </p>
        )}

        {list.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-[13rem_1fr]">
            <div className="flex max-h-64 flex-col gap-1 overflow-y-auto pr-1">
              {list.map(run => (
                <button
                  key={run.id}
                  type="button"
                  aria-pressed={run.id === activeId}
                  onClick={() => setPicked(run.id)}
                  className={cn(
                    'rounded-lg border px-2.5 py-2 text-left transition-colors',
                    run.id === activeId
                      ? 'border-accent bg-accent/10'
                      : 'border-line hover:border-line-strong'
                  )}
                >
                  <span className="block text-xs text-ink">{formatRunAt(run.at)}</span>
                  <span className="mt-0.5 block truncate text-[0.7rem] text-ink-3">
                    {run.preview || `${formatSize(run.size)} of output`}
                  </span>
                </button>
              ))}
            </div>

            <div className="min-w-0">
              {detail.isPending && <Spinner label="Opening the run…" />}
              {detail.error && (
                <p className="text-sm text-ink-2">That run could not be read. Try Refresh.</p>
              )}
              {detail.data && (
                <>
                  <p className="mb-2 text-xs text-ink-3">
                    {formatRunAt(detail.data.run.at)} · {formatSize(detail.data.run.size)}
                    {detail.data.run.truncated && ' · only the beginning is shown'}
                  </p>
                  <div className="max-h-[46vh] overflow-y-auto rounded-lg border border-line bg-canvas p-4">
                    <Markdown text={detail.data.run.content} variant="document" />
                  </div>
                </>
              )}
              {!detail.data && !detail.isPending && !detail.error && active && (
                <p className="text-sm text-ink-2">Choose a run to read it.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </Dialog>
  )
}

function formatRunAt(value: string | number): string {
  const date = new Date(typeof value === 'number' ? toMillis(value) : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return 'empty'
  if (bytes < 1024) return `${bytes} B`
  return `${Math.round(bytes / 1024)} KB`
}
