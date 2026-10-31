/**
 * The seam client — the only place that talks HTTP to the engine.
 *
 * Two lessons are ported from the Hermes desktop's `api-transport.ts`, because both were
 * learned the expensive way upstream:
 *
 *   1. `POST /v1/runs` is NOT idempotent. An ECONNRESET can arrive after the server
 *      already created the session and submitted the prompt, so a blind retry
 *      double-submits a turn. Only idempotent verbs are retried here.
 *   2. SSE is read with `fetch` + a stream reader, not `EventSource`, because
 *      `EventSource` cannot send an Authorization header.
 */

import type {
  ApprovalChoice,
  ApprovalResponse,
  Capabilities,
  ClarifyResponse,
  CreateJobRequest,
  CreateSessionRequest,
  CronJob,
  HealthResponse,
  JobListResponse,
  JobResponse,
  RunEvent,
  SessionListResponse,
  SessionMessagesResponse,
  SessionPatch,
  SessionResponse,
  SseFrame,
  StartRunRequest,
  StartRunResponse,
  ToolsetEntry,
  UpdateJobRequest
} from '@shared/wire'
import { isTrustedBaseUrl } from './settings'

export interface SeamConfig {
  baseUrl: string
  apiKey: string
  /**
   * The profile this client speaks for. The gateway's multi-profile surface is a URL prefix
   * (`/p/<name>/…`), so the whole client is scoped once here rather than every call site
   * remembering. A single-profile gateway accepts the prefix when it names the profile it was
   * launched as, which is why the installed profile works before any host migration.
   */
  profile?: string | null
}

/** The document's own origin, or undefined where there is none (a worker, a test, a server render). */
function pageOrigin(): string | undefined {
  return typeof window === 'undefined' ? undefined : window.location.origin
}

export class SeamError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'SeamError'
    this.status = status
    this.code = code
  }
}

/** Network-level failures, as opposed to an HTTP status the server chose. */
export class SeamUnreachable extends Error {
  constructor(message: string, cause?: unknown) {
    super(message)
    this.name = 'SeamUnreachable'
    this.cause = cause
  }
}

// --------------------------------------------------------------- SSE decoding

/**
 * Incremental SSE decoder. Pure and synchronous so it can be tested without a socket.
 *
 * The engine's frames are `id: <seq>` + `data: <json>`, with `: open` / `: keepalive`
 * comment frames that carry no payload. The event TYPE lives in the JSON `event` key —
 * there is no SSE `event:` line to read (the front-end design §2).
 */
export class SseDecoder {
  private buffer = ''

  push(chunk: string): SseFrame[] {
    this.buffer += chunk

    // Normalise CRLF to LF before looking for frame boundaries, because a CRLF stream
    // separates frames with `\r\n\r\n` and a plain search for `\n\n` would never match.
    // A trailing lone CR is held back: the following LF may still be in the next chunk.
    let text = this.buffer
    let held = ''
    if (text.endsWith('\r')) {
      held = '\r'
      text = text.slice(0, -1)
    }
    this.buffer = text.replace(/\r\n/g, '\n') + held

    const frames: SseFrame[] = []

    let boundary = this.buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      const frame = decodeBlock(block)
      if (frame) frames.push(frame)
      boundary = this.buffer.indexOf('\n\n')
    }

    return frames
  }
}

function decodeBlock(block: string): SseFrame | null {
  let id: number | null = null
  const dataLines: string[] = []

  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (line === '' || line.startsWith(':')) continue // comment / keepalive
    if (line.startsWith('id:')) {
      const parsed = Number.parseInt(line.slice(3).trim(), 10)
      if (Number.isFinite(parsed)) id = parsed
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }

  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  if (!payload.trim()) return null

  try {
    return { id, data: JSON.parse(payload) as RunEvent }
  } catch {
    // A malformed frame must not kill the stream; skip it.
    return null
  }
}

// -------------------------------------------------------------------- client

const IDEMPOTENT = new Set(['GET', 'HEAD', 'OPTIONS'])

export class SeamClient {
  constructor(private readonly config: SeamConfig) {}

  private url(path: string): string {
    const base = this.config.baseUrl.replace(/\/$/, '')
    const profile = (this.config.profile ?? '').trim()
    if (!profile) return `${base}${path}`
    return `${base}/p/${encodeURIComponent(profile)}${path}`
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = { ...extra }
    // Omitted rather than sent empty when the dev server supplies it through the proxy.
    // An empty `Bearer ` would be a malformed credential, and the proxy replaces the
    // header anyway.
    //
    // And only ever to an address that is this app's own origin or this machine's loopback:
    // a key is not something to hand to whatever host a stored setting names
    // (the internal security audit A19-WEB-4).
    if (this.config.apiKey && isTrustedBaseUrl(this.config.baseUrl, pageOrigin())) {
      headers.Authorization = `Bearer ${this.config.apiKey}`
    }
    return headers
  }

  /** Retry policy: idempotent verbs only. See the module comment. */
  private async request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const init: RequestInit = {
      method,
      headers: this.headers(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal
    }

    const attempts = IDEMPOTENT.has(method) ? 2 : 1
    let lastError: unknown

    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        const response = await fetch(this.url(path), init)
        if (!response.ok) {
          const { message, code } = await describeError(response)
          throw new SeamError(message, response.status, code)
        }
        if (response.status === 204) return undefined as T
        // A 200 with an empty body is a legitimate "done" from a DELETE, and parsing it
        // would throw — which the catch below would misreport as an unreachable engine.
        const text = await response.text()
        if (!text.trim()) return undefined as T
        try {
          return JSON.parse(text) as T
        } catch {
          throw new SeamError(
            `The engine answered HTTP ${response.status} with a body that is not JSON.`,
            response.status
          )
        }
      } catch (error) {
        if (error instanceof SeamError) throw error
        lastError = error
        // Only a connection-establishment failure is safe to retry, and only for a verb
        // that is idempotent by definition.
        if (attempt === attempts - 1) break
      }
    }

    throw new SeamUnreachable(
      `Could not reach the engine at ${this.config.baseUrl}. Is the gateway running?`,
      lastError
    )
  }

  health(signal?: AbortSignal): Promise<HealthResponse> {
    return this.request<HealthResponse>('GET', '/health', undefined, signal)
  }

  capabilities(signal?: AbortSignal): Promise<Capabilities> {
    return this.request<Capabilities>('GET', '/v1/capabilities', undefined, signal)
  }

  toolsets(signal?: AbortSignal): Promise<{ data: ToolsetEntry[] }> {
    return this.request<{ data: ToolsetEntry[] }>('GET', '/v1/toolsets', undefined, signal)
  }

  /*
   * `skills()` used to sit here, calling the engine's `GET /v1/skills`. That route answers 500 at
   * this pin — its handler passes a keyword `_find_all_skills` does not accept — and nothing read
   * the method: the profile's skills come from the BFF's capability registry instead
   * (`app/server/capabilities.py`), which reads the same files the engine would have.
   */

  /**
   * Not idempotent — never retried.
   *
   * `instructions` is the turn's ephemeral system prompt, and it is how the operator's chosen voice
   * reaches the model: the engine resolves `display.personality` from config on the CLI and
   * messaging surfaces but **not** on this one, so a personality written to `config.yaml` would
   * never be read here. Verified both ways — a configured personality changed nothing, and an
   * `instructions` string came back in the reply (the engine notes §9).
   */
  startRun(
    input: string,
    sessionId?: string,
    signal?: AbortSignal,
    instructions?: string
  ): Promise<StartRunResponse> {
    const body: StartRunRequest = { input }
    if (sessionId) body.session_id = sessionId
    if (instructions) body.instructions = instructions
    return this.request<StartRunResponse>('POST', '/v1/runs', body, signal)
  }

  /**
   * The model catalogue. One of very few settings-shaped routes the gateway actually serves:
   * `/api/config`, `/api/config/schema`, `/api/env` and `/api/model/set` are all 404 here, so
   * this is the whole of what the seam knows about settings.
   */

  /** Not idempotent — never retried. */
  respondToApproval(
    runId: string,
    choice: ApprovalChoice,
    requestId?: string | null,
    executionGeneration?: number | null,
    signal?: AbortSignal
  ): Promise<ApprovalResponse> {
    // The authority run's endpoint requires the generation beside the prompt id; a plain run
    // accepts `request_id` alone. Sending both when known works for either shape.
    const body: Record<string, string | number> = { choice }
    if (requestId) body.request_id = requestId
    if (typeof executionGeneration === 'number') body.execution_generation = executionGeneration
    return this.request<ApprovalResponse>('POST', `/v1/runs/${runId}/approval`, body, signal)
  }

  /**
   * Answer a clarifying question. Unlike an approval, the authority route requires all three
   * fields — the engine rejects a body that names anything else (`respond_run`).
   *
   * Not idempotent — never retried.
   */
  respondToClarify(
    runId: string,
    answer: string,
    requestId: string,
    executionGeneration: number,
    signal?: AbortSignal
  ): Promise<ClarifyResponse> {
    const body = {
      answer,
      request_id: requestId,
      execution_generation: executionGeneration
    }
    return this.request<ClarifyResponse>('POST', `/v1/runs/${runId}/clarify`, body, signal)
  }

  stopRun(runId: string, signal?: AbortSignal): Promise<unknown> {
    return this.request('POST', `/v1/runs/${runId}/stop`, {}, signal)
  }

  sessionMessages(sessionId: string, signal?: AbortSignal): Promise<SessionMessagesResponse> {
    return this.request<SessionMessagesResponse>(
      'GET',
      `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
      undefined,
      signal
    )
  }

  // ------------------------------------------------------------------ sessions
  //
  // The rail's whole data source. Idempotent verbs are retried by `request`; the
  // mutating ones are not, which is why `createSession` sends a client-chosen id —
  // a retried create would otherwise make a second, empty session.

  listSessions(
    options: { limit?: number; offset?: number } = {},
    signal?: AbortSignal
  ): Promise<SessionListResponse> {
    const query = new URLSearchParams()
    if (options.limit !== undefined) query.set('limit', String(options.limit))
    if (options.offset !== undefined) query.set('offset', String(options.offset))
    const suffix = query.size ? `?${query}` : ''
    return this.request<SessionListResponse>('GET', `/api/sessions${suffix}`, undefined, signal)
  }

  /** Not idempotent — never retried. Pass `id` so the caller knows the name up front. */
  createSession(
    body: CreateSessionRequest,
    signal?: AbortSignal
  ): Promise<SessionResponse> {
    return this.request<SessionResponse>('POST', '/api/sessions', body, signal)
  }


  /** Accepts only the fields in `SessionPatch`; the engine 400s on anything else. */
  patchSession(
    sessionId: string,
    patch: SessionPatch,
    signal?: AbortSignal
  ): Promise<SessionResponse> {
    return this.request<SessionResponse>(
      'PATCH',
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      patch,
      signal
    )
  }

  /** Not idempotent by the engine's reckoning; a repeat simply 404s. */
  deleteSession(sessionId: string, signal?: AbortSignal): Promise<void> {
    return this.request<void>(
      'DELETE',
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      undefined,
      signal
    )
  }

  /** Not idempotent — never retried; each call makes a new session. */

  async listJobs(includeDisabled = true, signal?: AbortSignal): Promise<CronJob[]> {
    const query = includeDisabled ? '?include_disabled=true' : ''
    const { jobs } = await this.request<JobListResponse>('GET', `/api/jobs${query}`, undefined, signal)
    return jobs ?? []
  }

  /** Not idempotent — never retried. */
  createJob(body: CreateJobRequest, signal?: AbortSignal): Promise<CronJob> {
    return this.request<JobResponse>('POST', '/api/jobs', body, signal).then(r => r.job)
  }

  /**
   * Change a job in place. The engine accepts only the fields on `UpdateJobRequest` and drops
   * anything else, so the caller builds the body rather than spreading a form.
   */
  updateJob(jobId: string, body: UpdateJobRequest, signal?: AbortSignal): Promise<CronJob> {
    return this.request<JobResponse>(
      'PATCH',
      `/api/jobs/${encodeURIComponent(jobId)}`,
      body,
      signal
    ).then(r => r.job)
  }


  deleteJob(jobId: string, signal?: AbortSignal): Promise<void> {
    return this.request<void>('DELETE', `/api/jobs/${encodeURIComponent(jobId)}`, undefined, signal)
  }

  pauseJob(jobId: string, signal?: AbortSignal): Promise<CronJob> {
    return this.request<JobResponse>(
      'POST',
      `/api/jobs/${encodeURIComponent(jobId)}/pause`,
      {},
      signal
    ).then(r => r.job)
  }

  resumeJob(jobId: string, signal?: AbortSignal): Promise<CronJob> {
    return this.request<JobResponse>(
      'POST',
      `/api/jobs/${encodeURIComponent(jobId)}/resume`,
      {},
      signal
    ).then(r => r.job)
  }

  /** Fire a job now, out of schedule. Not idempotent — never retried. */
  runJob(jobId: string, signal?: AbortSignal): Promise<unknown> {
    return this.request('POST', `/api/jobs/${encodeURIComponent(jobId)}/run`, {}, signal)
  }

  /**
   * Subscribe to a run's events. Resumes from `lastSeq` when given, so a dropped
   * connection does not lose the turn. The caller owns the abort signal.
   */
  async *streamRun(
    runId: string,
    options: { lastSeq?: number | null; signal?: AbortSignal } = {}
  ): AsyncGenerator<SseFrame> {
    const headers = this.headers({ Accept: 'text/event-stream' })
    if (options.lastSeq !== null && options.lastSeq !== undefined) {
      headers['Last-Event-ID'] = String(options.lastSeq)
    }

    let response: Response
    try {
      response = await fetch(this.url(`/v1/runs/${runId}/events`), {
        method: 'GET',
        headers,
        signal: options.signal
      })
    } catch (error) {
      throw new SeamUnreachable('Lost the connection to the engine.', error)
    }

    if (!response.ok) {
      const { message, code } = await describeError(response)
      throw new SeamError(message, response.status, code)
    }
    if (!response.body) {
      throw new SeamError('The engine returned no event stream.', response.status)
    }

    const reader = response.body.getReader()
    const textDecoder = new TextDecoder()
    const decoder = new SseDecoder()

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = textDecoder.decode(value, { stream: true })
        for (const frame of decoder.push(chunk)) yield frame
      }
    } finally {
      // A normal completion breaks the loop on the terminal frame and lands here — the engine
      // closes its side, but this is the only deterministic teardown on our side
      // (the internal audit WEB-17).
      await reader.cancel().catch(() => undefined)
      reader.releaseLock()
    }
  }
}

async function describeError(response: Response): Promise<{ message: string; code?: string }> {
  let message = `HTTP ${response.status}`
  let code: string | undefined
  try {
    const body = (await response.json()) as { error?: { message?: string; code?: string }; message?: string }
    if (body?.error?.message) message = body.error.message
    else if (typeof body?.message === 'string') message = body.message
    code = body?.error?.code
  } catch {
    // A non-JSON error body is still an error; keep the status line.
  }

  if (response.status === 403) {
    message =
      'The engine refused this origin or key (403). Check the API key, and that this page’s origin is in API_SERVER_CORS_ORIGINS.'
  } else if (response.status === 401) {
    message = 'The API key was rejected (401).'
  }

  return { message, code }
}
