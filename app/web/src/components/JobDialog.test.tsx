// @vitest-environment jsdom
/**
 * The New job dialog's contract with the engine.
 *
 * The tests care about two things a screenshot cannot show: the text that reaches `/api/jobs`
 * is the engine's own language (not cron for the common cases), and an edit sends only what
 * changed — so a schedule set elsewhere, or a relative `in 30m`, is never re-evaluated behind
 * the operator's back.
 */

import type { CronJob } from '@shared/wire'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  createJob: vi.fn(),
  updateJob: vi.fn()
}))

vi.mock('../state/app-context', () => ({
  useApp: () => ({ client: { createJob: mocks.createJob, updateJob: mocks.updateJob } })
}))

const { JobDialog } = await import('./JobDialog')

afterEach(() => {
  cleanup()
  mocks.createJob.mockReset()
  mocks.updateJob.mockReset()
})

const JOB: CronJob = {
  id: 'abcdef123456',
  name: 'Monday briefing',
  prompt: 'Summarise the week.',
  schedule_display: '0 7 * * 1',
  schedule: { kind: 'cron', expr: '0 7 * * 1' },
  repeat: { times: null, completed: 0 }
}

function openCreate() {
  render(<JobDialog onClose={vi.fn()} onSaved={vi.fn()} />)
}

function openEdit(job: CronJob = JOB) {
  render(<JobDialog job={job} onClose={vi.fn()} onSaved={vi.fn()} />)
}

describe('creating a job', () => {
  it('opens on the weekly example and sends the engine’s phrase, not cron', async () => {
    mocks.createJob.mockResolvedValue({})
    openCreate()

    expect(screen.getByText('Every Monday at 7:00 am')).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'Summarise the week.' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Schedule job' }))

    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(1))
    expect(mocks.createJob).toHaveBeenCalledWith({
      name: 'Summarise the week.',
      schedule: 'every monday at 07:00',
      prompt: 'Summarise the week.'
    })
  })

  it('sends a daily phrase when Daily is chosen', async () => {
    mocks.createJob.mockResolvedValue({})
    openCreate()
    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'Morning briefing' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Daily' }))
    expect(screen.getByText('Every day at 7:00 am')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Schedule job' }))
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalled())
    expect(mocks.createJob.mock.calls[0][0].schedule).toBe('every day at 07:00')
  })

  it('lets the advanced field be authoritative', async () => {
    mocks.createJob.mockResolvedValue({})
    openCreate()
    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'Rent reminder' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Edit as text' }))
    const text = screen.getByLabelText(/Schedule text/)
    expect((text as HTMLInputElement).value).toBe('every monday at 07:00')

    fireEvent.change(text, { target: { value: '0 9 15 * *' } })
    expect(screen.getByText('Monthly on day 15 at 9:00 am')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Schedule job' }))

    await waitFor(() => expect(mocks.createJob).toHaveBeenCalled())
    expect(mocks.createJob.mock.calls[0][0].schedule).toBe('0 9 15 * *')
  })

  it('will not create a one-shot in the past', () => {
    openCreate()
    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'A reminder' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Once' }))
    fireEvent.change(screen.getByLabelText('On'), { target: { value: '2020-01-01' } })

    expect(screen.getByText(/has already passed/)).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: 'Schedule job' }) as HTMLButtonElement).disabled
    ).toBe(true)
  })

  it('does not send a repeat count for a one-shot', async () => {
    mocks.createJob.mockResolvedValue({})
    openCreate()
    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'Rent reminder' }
    })
    fireEvent.change(screen.getByLabelText('Stop after this many runs'), {
      target: { value: '3' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Once' }))
    fireEvent.click(screen.getByRole('button', { name: 'Schedule job' }))

    await waitFor(() => expect(mocks.createJob).toHaveBeenCalled())
    expect('repeat' in mocks.createJob.mock.calls[0][0]).toBe(false)
  })

  it('does not create without a task', () => {
    openCreate()
    expect(
      (screen.getByRole('button', { name: 'Schedule job' }) as HTMLButtonElement).disabled
    ).toBe(true)
  })
})

describe('editing a job', () => {
  it('prefills the builder and sends only what changed', async () => {
    mocks.updateJob.mockResolvedValue({})
    openEdit()

    expect(screen.getByText('Every Monday at 7:00 am')).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: 'Monday' }) as HTMLButtonElement).getAttribute('aria-pressed')
    ).toBe('true')

    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'Summarise the week and the market.' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(mocks.updateJob).toHaveBeenCalled())
    expect(mocks.updateJob).toHaveBeenCalledWith('abcdef123456', {
      prompt: 'Summarise the week and the market.'
    })
  })

  it('sends the new phrase when a day is added', async () => {
    mocks.updateJob.mockResolvedValue({})
    openEdit()
    fireEvent.click(screen.getByRole('button', { name: 'Friday' }))
    expect(screen.getByText('Every Mon, Fri at 7:00 am')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(mocks.updateJob).toHaveBeenCalled())
    expect(mocks.updateJob).toHaveBeenCalledWith('abcdef123456', {
      schedule: 'every monday, friday at 07:00'
    })
  })

  it('leaves an unrepresentable schedule alone unless its text changes', async () => {
    mocks.updateJob.mockResolvedValue({})
    const job: CronJob = {
      ...JOB,
      schedule_display: '0 9 8-14 * 2',
      schedule: { kind: 'cron', expr: '0 9 8-14 * 2' }
    }
    openEdit(job)

    // It opens in the advanced field, untouched, rather than being rewritten as a builder case.
    const text = screen.getByLabelText(/Schedule text/) as HTMLInputElement
    expect(text.value).toBe('0 9 8-14 * 2')

    fireEvent.change(screen.getByLabelText(/What should happen/), {
      target: { value: 'A new task' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(mocks.updateJob).toHaveBeenCalled())
    expect(mocks.updateJob).toHaveBeenCalledWith('abcdef123456', { prompt: 'A new task' })
  })

  it('shows the engine’s refusal in the dialog', async () => {
    mocks.updateJob.mockRejectedValue(new Error('Cannot activate terminal cron job'))
    openEdit()
    fireEvent.change(screen.getByLabelText(/What should happen/), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain('terminal')
  })
})
