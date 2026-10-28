// @vitest-environment jsdom
/**
 * The Scheduled jobs page as the operator meets it: a job is described in English, its last run
 * is visible without opening anything, edit and output are reachable from the card, and the
 * chat door navigates instead of pretending the page can do everything.
 */

import type { CronJob } from '@shared/wire'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

const mocks = vi.hoisted(() => ({
  jobs: { data: [] as CronJob[], isPending: false, error: null, refetch: vi.fn(), isFetching: false },
  createJob: vi.fn(),
  updateJob: vi.fn(),
  deleteJob: vi.fn(),
  runJob: vi.fn(),
  pauseJob: vi.fn(),
  resumeJob: vi.fn(),
  jobRuns: vi.fn(),
  jobRun: vi.fn()
}))

vi.mock('../state/app-context', () => ({
  qk: {
    jobs: ['jobs'],
    jobRuns: (id: string) => ['job-runs', id],
    jobRun: (id: string, run: string) => ['job-runs', id, run]
  },
  useJobs: () => mocks.jobs,
  useApp: () => ({
    client: {
      createJob: mocks.createJob,
      updateJob: mocks.updateJob,
      deleteJob: mocks.deleteJob,
      runJob: mocks.runJob,
      pauseJob: mocks.pauseJob,
      resumeJob: mocks.resumeJob
    },
    bff: { jobRuns: mocks.jobRuns, jobRun: mocks.jobRun }
  })
}))

const { JobsPage } = await import('./JobsPage')

const JOB: CronJob = {
  id: 'abcdef123456',
  name: 'Monday briefing',
  prompt: 'Summarise what is outstanding this week.',
  schedule_display: '0 7 * * 1',
  schedule: { kind: 'cron', expr: '0 7 * * 1' },
  enabled: true,
  state: 'scheduled',
  next_run_at: '2026-11-03T07:00:00+10:00',
  last_run_at: '2026-10-27T07:00:00+10:00',
  last_status: 'ok',
  latest_execution: { status: 'completed' },
  repeat: { times: null, completed: 0 }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  mocks.jobs.data = []
})

function ChatProbe() {
  const location = useLocation()
  return <p>chat {location.pathname}</p>
}

function renderPage(jobs: CronJob[]) {
  mocks.jobs.data = jobs
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/jobs']}>
        <Routes>
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/chat/:id" element={<ChatProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('the job list', () => {
  it('describes the schedule and the last run in English', () => {
    renderPage([JOB])

    expect(screen.getByText('Every Monday at 7:00 am')).toBeTruthy()
    expect(screen.getByText('Last run worked')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Edit/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'View output' })).toBeTruthy()
  })

  it('shows a failed run and its error rather than only the state', () => {
    renderPage([
      {
        ...JOB,
        state: 'scheduled',
        last_status: 'error',
        last_error: 'the model was unreachable',
        latest_execution: { status: 'failed' }
      }
    ])

    expect(screen.getByText('Last run failed')).toBeTruthy()
    expect(screen.getByText('the model was unreachable')).toBeTruthy()
  })

  it('shows an unrepresentable schedule as itself', () => {
    renderPage([
      {
        ...JOB,
        schedule_display: '0 9 8-14 * 2',
        schedule: { kind: 'cron', expr: '0 9 8-14 * 2' }
      }
    ])

    expect(screen.getByText('0 9 8-14 * 2')).toBeTruthy()
  })

  it('offers the two doors when there is nothing scheduled', () => {
    renderPage([])

    expect(screen.getByText('Nothing scheduled')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Schedule something/ })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Ask the assistant/ }).length).toBeGreaterThan(0)
  })
})

describe('the card’s actions', () => {
  it('opens the edit dialog with the job in it', () => {
    renderPage([JOB])
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))

    expect(screen.getByText('Edit job')).toBeTruthy()
    expect((screen.getByLabelText(/What should happen/) as HTMLTextAreaElement).value).toBe(
      'Summarise what is outstanding this week.'
    )
  })

  it('opens the run output dialog', async () => {
    mocks.jobRuns.mockResolvedValue({ available: true, job_id: JOB.id, runs: [] })
    renderPage([JOB])
    fireEvent.click(screen.getByRole('button', { name: 'View output' }))

    expect(await screen.findByText(/No runs are kept for this job yet/)).toBeTruthy()
    expect(mocks.jobRuns).toHaveBeenCalledWith(JOB.id, expect.anything())
  })

  it('says so when this machine cannot read run output', async () => {
    mocks.jobRuns.mockResolvedValue({
      available: false,
      reason: 'No engine profile is configured for this server.',
      runs: []
    })
    renderPage([JOB])
    fireEvent.click(screen.getByRole('button', { name: 'View output' }))

    expect(await screen.findByText('No engine profile is configured for this server.')).toBeTruthy()
  })
})

describe('the chat door', () => {
  it('opens a new conversation instead of creating a job', async () => {
    renderPage([JOB])
    fireEvent.click(screen.getByRole('button', { name: /Ask the assistant/ }))

    await waitFor(() => expect(screen.getByText(/^chat \/chat\//)).toBeTruthy())
    expect(mocks.createJob).not.toHaveBeenCalled()
  })
})
