import type { CronJob } from '@shared/wire'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CalendarClock,
  Clock,
  MessageSquare,
  Pause,
  Pencil,
  Play,
  Plus,
  Trash2,
  Zap
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { JobDialog } from '../components/JobDialog'
import { JobRunsDialog } from '../components/JobRunsDialog'
import { describeSchedule } from '../components/job-schedule'
import { hasRunOutput, jobRunStatus, repeatLine } from '../components/job-status'
import { qk, useApp, useJobs } from '../state/app-context'
import { makeSessionId } from '../state/useConversation'
import { describeWriteFailure, toMillis } from '../shell/sessions'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardHeader } from '../ui/card'
import { cn } from '../ui/cn'
import { ConfirmDialog } from '../ui/dialog'
import { EmptyState } from '../ui/empty'
import { Spinner } from '../ui/spinner'

/**
 * Scheduled jobs — `GET/POST/PATCH/DELETE /api/jobs` plus pause · resume · run.
 *
 * Note the route: `/api/jobs` on the gateway. `/api/cron/jobs` is the *dashboard* server's
 * route and 404s here, which is exactly the kind of thing `capabilities` would not tell
 * you (`jobs_admin` reads false on this build while these routes work).
 *
 * The page writes the schedule in the operator's words (`components/job-schedule.ts`) and the
 * run output is read from the profile by the BFF (`app/server/job_runs.py`) — the gateway has
 * no per-run route. Chat is a second door, linked here, not the only one.
 */
export function JobsPage() {
  const { data: jobs, isPending, error, refetch, isFetching } = useJobs()
  const { client } = useApp()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [dialog, setDialog] = useState<{ mode: 'create' } | { mode: 'edit'; job: CronJob } | null>(
    null
  )
  const [runsFor, setRunsFor] = useState<CronJob | null>(null)
  const [deleting, setDeleting] = useState<CronJob | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: qk.jobs })

  const act = async (id: string, run: () => Promise<unknown>) => {
    setBusyId(id)
    setActionError(null)
    try {
      await run()
      await invalidate()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusyId(null)
    }
  }

  const ask = () =>
    navigate(`/chat/${makeSessionId()}`, { state: { draft: 'Schedule a job for me: ' } })

  const remove = useMutation({
    mutationFn: (id: string) => client.deleteJob(id),
    onSuccess: () => {
      setDeleting(null)
      void invalidate()
    }
    // No `onError`: the dialog renders `remove.error` itself, so a refused delete says why
    // instead of leaving the dialog open with a button that appears to do nothing
    // (the internal audit WEB-9).
  })

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6">
        <header className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-display text-sm text-ink">Scheduled jobs</h2>
            <p className="mt-0.5 text-xs text-ink-3">
              Work the assistant does on its own, while the engine is running. Set a day and a
              time; read what each run produced underneath.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
              Refresh
            </Button>
            <Button variant="ghost" size="sm" onClick={ask}>
              <MessageSquare className="size-3.5" />
              Ask the assistant
            </Button>
            <Button variant="primary" size="sm" onClick={() => setDialog({ mode: 'create' })}>
              <Plus className="size-3.5" />
              Schedule a job
            </Button>
          </div>
        </header>

        {actionError && (
          <p className="rounded-card border border-danger/40 px-3 py-2 text-xs text-danger">
            {actionError}
          </p>
        )}

        {isPending && <Spinner label="Loading jobs…" />}

        {error && (
          <Card className="border-danger/40">
            <p className="text-sm text-danger">
              Could not read <code className="font-mono">/api/jobs</code>. The engine may be
              down, or this build may not expose scheduled work.
            </p>
          </Card>
        )}

        {!isPending && !error && (jobs?.length ?? 0) === 0 && (
          <Card>
            <EmptyState
              className="py-10"
              icon={<CalendarClock className="size-5" />}
              title="Nothing scheduled"
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="secondary" onClick={() => setDialog({ mode: 'create' })}>
                    <Plus className="size-3.5" />
                    Schedule something
                  </Button>
                  <Button variant="ghost" onClick={ask}>
                    <MessageSquare className="size-3.5" />
                    Ask the assistant
                  </Button>
                </div>
              }
            >
              Nothing runs on its own yet. A job is a task plus a day and a time.
            </EmptyState>
          </Card>
        )}

        <div className="flex flex-col gap-2">
          {(jobs ?? []).map(job => (
            <JobCard
              key={job.id}
              job={job}
              busy={busyId === job.id}
              onRun={() => act(job.id, () => client.runJob(job.id))}
              onPause={() => act(job.id, () => client.pauseJob(job.id))}
              onResume={() => act(job.id, () => client.resumeJob(job.id))}
              onEdit={() => setDialog({ mode: 'edit', job })}
              onViewRuns={() => setRunsFor(job)}
              onDelete={() => setDeleting(job)}
            />
          ))}
        </div>
      </div>

      {/* Mounted only while open, so each dialog starts from its own job, not the last one. */}
      {dialog && (
        <JobDialog
          job={dialog.mode === 'edit' ? dialog.job : undefined}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null)
            void invalidate()
          }}
        />
      )}

      {runsFor && <JobRunsDialog job={runsFor} onClose={() => setRunsFor(null)} />}

      <ConfirmDialog
        open={Boolean(deleting)}
        destructive
        busy={remove.isPending}
        title="Delete this job?"
        description={
          deleting ? `“${deleting.name}” will stop running. This cannot be undone.` : undefined
        }
        confirmLabel="Delete"
        error={
          remove.error
            ? describeWriteFailure(
                remove.error,
                deleting ? `delete “${deleting.name}”` : 'delete that job'
              )
            : undefined
        }
        onCancel={() => {
          remove.reset()
          setDeleting(null)
        }}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  )
}

const TERMINAL_STATES = new Set(['completed', 'error'])

const STATUS_TONE = {
  ok: 'text-success',
  warn: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-ink-3'
} as const

function JobCard({
  job,
  busy,
  onRun,
  onPause,
  onResume,
  onEdit,
  onViewRuns,
  onDelete
}: {
  job: CronJob
  busy: boolean
  onRun: () => void
  onPause: () => void
  onResume: () => void
  onEdit: () => void
  onViewRuns: () => void
  onDelete: () => void
}) {
  const [showPrompt, setShowPrompt] = useState(false)
  const state =
    typeof job.state === 'string' && job.state
      ? job.state
      : job.enabled === false
        ? 'paused'
        : 'active'
  const paused = state === 'paused' || job.enabled === false
  const terminal = TERMINAL_STATES.has(state)

  const scheduleText =
    job.schedule_display ??
    (job.schedule?.kind === 'once' ? job.schedule.run_at : job.schedule?.expr) ??
    ''
  const schedule = describeSchedule(scheduleText)
  const status = jobRunStatus(job)
  const canViewRuns = hasRunOutput(job)
  const repeat = repeatLine(job)

  return (
    <Card className="gap-2.5">
      <CardHeader
        title={job.name}
        aside={
          <div className="flex items-center gap-1.5">
            <Badge tone={state === 'error' ? 'danger' : terminal ? 'neutral' : paused ? 'warn' : 'ok'}>
              {state}
            </Badge>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <Clock className="size-3.5" />
          <span className={cn('text-ink-2', !schedule.known && 'font-mono')}>{schedule.label}</span>
        </span>
        {job.next_run_at && <span>next {formatWhen(job.next_run_at)}</span>}
        {job.last_run_at && <span>last {formatWhen(job.last_run_at)}</span>}
        {typeof job.run_count === 'number' && job.run_count > 0 && <span>{job.run_count} runs</span>}
        {repeat && <span>{repeat}</span>}
        {job.deliver && job.deliver !== 'local' && <span>delivers to {job.deliver}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        {status ? (
          <span className={cn('inline-flex items-center gap-1', STATUS_TONE[status.tone])}>
            {status.label}
          </span>
        ) : (
          !job.last_run_at && <span className="text-ink-3">Not run yet</span>
        )}
        {typeof job.failure_streak === 'number' && job.failure_streak > 1 && (
          <span className="text-danger">{job.failure_streak} failures in a row</span>
        )}
        {job.last_error && (
          <span className="min-w-0 max-w-full truncate text-danger">{job.last_error}</span>
        )}
        {canViewRuns && (
          <button
            type="button"
            onClick={onViewRuns}
            className="text-accent underline underline-offset-2 hover:brightness-110"
          >
            View output
          </button>
        )}
      </div>

      {job.prompt && (
        <div>
          <p
            className={cn(
              'text-xs whitespace-pre-wrap text-ink-2',
              !showPrompt && 'line-clamp-2'
            )}
          >
            {job.prompt}
          </p>
          {job.prompt.length > 140 && (
            <button
              type="button"
              onClick={() => setShowPrompt(value => !value)}
              className="mt-1 text-xs text-accent underline underline-offset-2 hover:brightness-110"
            >
              {showPrompt ? 'Less' : 'More'}
            </button>
          )}
        </div>
      )}

      {Array.isArray(job.skills) && job.skills.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {job.skills.map(skill => (
            <Badge key={skill} className="font-mono">
              {skill}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-line pt-2.5">
        <Button variant="secondary" size="sm" onClick={onRun} disabled={busy}>
          <Zap className="size-3.5" />
          Run now
        </Button>
        <Button variant="quiet" size="sm" onClick={onEdit} disabled={busy}>
          <Pencil className="size-3.5" />
          Edit
        </Button>
        {paused ? (
          <Button variant="quiet" size="sm" onClick={onResume} disabled={busy}>
            <Play className="size-3.5" />
            Resume
          </Button>
        ) : (
          <Button variant="quiet" size="sm" onClick={onPause} disabled={busy || terminal}>
            <Pause className="size-3.5" />
            Pause
          </Button>
        )}
        <Button variant="danger" size="sm" onClick={onDelete} disabled={busy}>
          <Trash2 className="size-3.5" />
          Delete
        </Button>
      </div>
    </Card>
  )
}

/** Accepts an epoch number (in either unit — see `toMillis`) or an ISO string. */
function formatWhen(value: string | number): string {
  const date = new Date(typeof value === 'number' ? toMillis(value) : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}
