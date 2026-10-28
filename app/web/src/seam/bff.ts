/**
 * The BFF client — ours, not Hermes'.
 *
 * Two backends, one origin, and the split is deliberate (the front-end design §3):
 * conversation goes through the engine seam under `/seam`; records, the pack registry and
 * the engine's local settings go through `app/server` under `/api`. Listing a pack's records
 * must never cost a model call or wait on a run.
 *
 * One request path, one error path. Reads may be retried; writes may not — a retried settings
 * write is a second write to a file the engine reads at startup.
 */

import type {
  CapabilityRegistry,
  CapabilityWriteResponse,
  ConnectorConnectResponse,
  ConnectorDisconnectResponse,
  ConnectorsResponse,
  ConnectorToolsResponse,
  EngineSettings,
  JobRunResponse,
  JobRunsResponse,
  KeyWriteResponse,
  LearningIndex,
  ModelWriteResponse,
  Pack,
  PackListResponse,
  PreviewMeta,
  RecordListResponse,
  StoredRecord,
  ReasoningEffortSetting,
  ReasoningEffortWriteResponse,
  SessionLearning,
  SkillWriteResponse,
  SkillsIndex,
  ToolsetWriteResponse,
  UrlSnapshot
} from '@shared/wire'
import type { WireAttachment } from '@shared/attachments'
import { SeamError, SeamUnreachable } from './client'

export interface AttachmentListResponse {
  data: WireAttachment[]
}

export interface ComposedTurn {
  input: string
  attachments: WireAttachment[]
}

/** What the browser knows about a file before it is uploaded. */
export interface UploadSource {
  /** The store name. A folder upload overrides it with the relative path's last segment. */
  name: string
  /** Only for a Folder… gesture: which folder, and where this file sits inside it. */
  relPath?: string
  folderToken?: string
  blob: Blob
}

export interface BffHealth {
  status?: string
  store?: { schema_version?: number }
  packs?: string[]
  record_types?: string[]
  [key: string]: unknown
}

/**
 * One profile as `/api/profiles` lists it.
 *
 * `served` is the running engine's answer, not a property of the directory: a profile can exist
 * and be selectable while the gateway is still serving only one. `null` means the server could
 * not read a live gateway record, which is different from a confident "no".
 */
export interface ProfileSummary {
  name: string
  display_name: string
  description: string
  is_install: boolean
  active: boolean
  provider: string | null
  model: string | null
  has_env: boolean
  served: boolean | null
}

export interface ProfileGateway {
  multiplex: boolean
  served: string[] | null
  live: boolean
}

export interface ProfilesResponse {
  available: boolean
  reason?: string
  active: string | null
  profiles: ProfileSummary[]
  gateway: ProfileGateway
  /** True when the engine must restart before a non-installed profile can hold a conversation. */
  restart_required: boolean
  install?: string
}

export interface ProfileWriteResponse {
  profile: ProfileSummary
  active?: string
  gateway?: ProfileGateway
  restart_required?: boolean
}

export interface CreateProfileInput {
  name: string
  display_name?: string
  description?: string
  clone_from?: string
}

export class BffClient {
  constructor(
    private readonly baseUrl = '/api',
    /** The profile every request is about; the server falls back to its active profile. */
    private readonly profile: string | null = null
  ) {}

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/$/, '')}${path}`
  }

  /** The one header that tells the BFF which profile a request is about. */
  private scoped(headers: Record<string, string>): Record<string, string> {
    return this.profile ? { ...headers, 'X-Pantler-Profile': this.profile } : headers
  }

  // ----------------------------------------------------------------- profiles
  //
  // The registry is the shell's own: profiles are engine directories, but the engine's profile
  // routes live on the dashboard server, which this app deliberately does not use. These are
  // the writes that create a business, rename it, select it and remove it.

  profiles(signal?: AbortSignal): Promise<ProfilesResponse> {
    return this.request<ProfilesResponse>('GET', '/profiles', undefined, signal)
  }

  activeProfile(signal?: AbortSignal): Promise<{ active: string | null; profile: ProfileSummary | null }> {
    return this.request('GET', '/profiles/active', undefined, signal)
  }

  /** Select the profile every screen and every engine call is about. Never retried. */
  setActiveProfile(name: string, signal?: AbortSignal): Promise<ProfileWriteResponse> {
    return this.request<ProfileWriteResponse>('POST', '/profiles/active', { name }, signal)
  }

  /** A new business, cloned from the installed payload unless another source is named. */
  createProfile(input: CreateProfileInput, signal?: AbortSignal): Promise<ProfileWriteResponse> {
    return this.request<ProfileWriteResponse>('POST', '/profiles', input, signal)
  }

  updateProfile(
    name: string,
    patch: { new_name?: string; display_name?: string; description?: string },
    signal?: AbortSignal
  ): Promise<ProfileWriteResponse> {
    return this.request<ProfileWriteResponse>(
      'PATCH',
      `/profiles/${encodeURIComponent(name)}`,
      patch,
      signal
    )
  }

  async deleteProfile(name: string, signal?: AbortSignal): Promise<void> {
    await this.request<void>('DELETE', `/profiles/${encodeURIComponent(name)}`, undefined, signal)
  }


  async packs(signal?: AbortSignal): Promise<Pack[]> {
    const { data } = await this.request<PackListResponse>('GET', '/packs', undefined, signal)
    return data ?? []
  }

  /**
   * One type's records, newest first. Read-only: the page is a viewer, not a second writer.
   *
   * `limit`/`offset` are the BFF's own paging; the server clamps `limit` to 500.
   */
  records(
    type: string,
    options: { limit?: number; offset?: number; order?: string } = {},
    signal?: AbortSignal
  ): Promise<RecordListResponse> {
    const query = new URLSearchParams()
    if (options.limit !== undefined) query.set('limit', String(options.limit))
    if (options.offset !== undefined) query.set('offset', String(options.offset))
    if (options.order) query.set('order', options.order)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return this.request<RecordListResponse>(
      'GET',
      `/records/${encodeURIComponent(type)}${suffix}`,
      undefined,
      signal
    )
  }

  /** One record, by its store id. */
  record(type: string, id: string, signal?: AbortSignal): Promise<StoredRecord> {
    return this.request<StoredRecord>(
      'GET',
      `/records/${encodeURIComponent(type)}/${encodeURIComponent(id)}`,
      undefined,
      signal
    )
  }

  /**
   * The profile's skills, read from its own files. The engine's `GET /v1/skills` answers 500 on
   * this build, so this is the honest source rather than a route that cannot work.
   */
  skills(signal?: AbortSignal): Promise<SkillsIndex> {
    return this.request<SkillsIndex>('GET', '/skills', undefined, signal)
  }

  /**
   * What the assistant has learned: its memory, the skills it wrote itself, and the ledger that
   * says which conversation caused each change.
   *
   * From the BFF for the same reason the skills index is: the engine's own memory, curator and
   * learning-graph surfaces are not on the seam this app talks to at all
   * (`app/server/learning.py` argues it in full). `available: false` is a normal answer — no
   * profile configured — not a failure to retry.
   */
  learning(signal?: AbortSignal): Promise<LearningIndex> {
    return this.request<LearningIndex>('GET', '/learning', undefined, signal)
  }

  /** What one conversation taught it. An empty `data` is the common, honest answer. */
  sessionLearning(session: string, signal?: AbortSignal): Promise<SessionLearning> {
    return this.request<SessionLearning>(
      'GET',
      `/learning/session/${encodeURIComponent(session)}`,
      undefined,
      signal
    )
  }

  // -------------------------------------------------------------- capabilities
  //
  // The registry is one read model over the files this profile owns, and one write path over the
  // switches those files already carry (the internal capability plan §2). The write rewrites a file the
  // engine reads, so it is not idempotent in effect and is never retried.

  /**
   * Every switchable thing in this profile, in one shape.
   *
   * `available: false` is a normal answer — the server was started without a profile directory —
   * not a failure to retry, the same contract as `/api/skills`.
   */
  capabilities(signal?: AbortSignal): Promise<CapabilityRegistry> {
    return this.request<CapabilityRegistry>('GET', '/capabilities', undefined, signal)
  }

  /**
   * Switch one capability, whichever kind it is. The answer's `applies_to` says when the change
   * becomes real, which the row repeats rather than promising a live effect: a plugin answers
   * `next_restart`, and a skill answers `new_conversations`.
   */
  async setCapability(
    id: string,
    enabled: boolean,
    signal?: AbortSignal
  ): Promise<CapabilityWriteResponse> {
    return this.request<CapabilityWriteResponse>(
      'PUT',
      `/capabilities/${encodeURIComponent(id)}`,
      { enabled },
      signal
    )
  }

  // -------------------------------------------------------------- connectors
  //
  // Rail C of the Composio notes. The state is read from Composio through the BFF; the shell
  // never infers `connected` from a click, and the key itself only ever travels one way.

  connectors(signal?: AbortSignal): Promise<ConnectorsResponse> {
    return this.request<ConnectorsResponse>('GET', '/connectors', undefined, signal)
  }

  /** An offer, not a connection: the answer carries the link the operator opens. */
  connectConnector(id: string, signal?: AbortSignal): Promise<ConnectorConnectResponse> {
    return this.request<ConnectorConnectResponse>(
      'POST',
      `/connectors/${encodeURIComponent(id)}/connect`,
      {},
      signal
    )
  }

  disconnectConnector(id: string, signal?: AbortSignal): Promise<ConnectorDisconnectResponse> {
    return this.request<ConnectorDisconnectResponse>(
      'DELETE',
      `/connectors/${encodeURIComponent(id)}`,
      undefined,
      signal
    )
  }

  /** The tools a connected app offers. Read-only, and used by the assistant plugin too. */
  connectorTools(id: string, signal?: AbortSignal): Promise<ConnectorToolsResponse> {
    return this.request<ConnectorToolsResponse>(
      'GET',
      `/connectors/${encodeURIComponent(id)}/tools`,
      undefined,
      signal
    )
  }

  // ---------------------------------------------------------------- settings
  //
  // The engine has no settings API on the seam, so these read and write the files it reads
  // at startup. Every one of them is local-only by construction — the server refuses anything
  // that did not arrive over loopback, and the write routes do not exist at all unless the
  // server was started with an explicit profile directory.

  settings(signal?: AbortSignal): Promise<EngineSettings> {
    return this.request<EngineSettings>('GET', '/settings', undefined, signal)
  }

  /** Not idempotent in effect (it rewrites a file), and never retried. */
  async saveModel(
    values: Record<string, string>,
    signal?: AbortSignal
  ): Promise<ModelWriteResponse> {
    return this.request<ModelWriteResponse>('PUT', '/settings/model', values, signal)
  }

  /**
   * Set `agent.reasoning_effort` — how hard the engine thinks before it answers, or `false` to
   * switch thinking off. The engine clamps a level to the nearest one the model accepts, so this
   * writes a preference. Live on the next conversation, like the toolset write. Never retried.
   */
  async saveReasoningEffort(
    value: ReasoningEffortSetting,
    signal?: AbortSignal
  ): Promise<ReasoningEffortWriteResponse> {
    return this.request<ReasoningEffortWriteResponse>(
      'PUT',
      '/settings/reasoning',
      { reasoning_effort: value },
      signal
    )
  }

  /**
   * Replace `agent.disabled_toolsets` — the engine's own suppression list, so a capability
   * switched off here really is absent from the agent rather than hidden in this UI.
   */
  async saveDisabledToolsets(
    disabled: string[],
    signal?: AbortSignal
  ): Promise<ToolsetWriteResponse> {
    return this.request<ToolsetWriteResponse>(
      'PUT',
      '/settings/toolsets',
      { disabled_toolsets: disabled },
      signal
    )
  }

  /** The engine's own skill switch — `skills.disabled` in the profile's config.yaml. */
  async saveDisabledSkills(
    disabled: string[],
    signal?: AbortSignal
  ): Promise<SkillWriteResponse> {
    return this.request<SkillWriteResponse>(
      'PUT',
      '/settings/skills',
      { disabled_skills: disabled },
      signal
    )
  }

  /** Writes `.env`. The value goes out; it never comes back. */
  async saveKey(name: string, value: string, signal?: AbortSignal): Promise<KeyWriteResponse> {
    return this.request<KeyWriteResponse>(
      'PUT',
      `/settings/keys/${encodeURIComponent(name)}`,
      { value },
      signal
    )
  }

  async clearKey(name: string, signal?: AbortSignal): Promise<KeyWriteResponse> {
    return this.request<KeyWriteResponse>(
      'DELETE',
      `/settings/keys/${encodeURIComponent(name)}`,
      undefined,
      signal
    )
  }

  // ------------------------------------------------------------- attachments
  //
  // The engine will not carry a file for us, so the BFF does: the bytes go up as one raw
  // body per file, and the turn is composed server-side. Nothing here decides where a file
  // ends up or what the assistant is told about it — that is `app/server/attachments.py`,
  // and keeping it there is what makes the format testable in one place.

  /** One raw body, one file (the attachment design §3). Not idempotent: never retried. */
  async uploadAttachment(
    session: string,
    source: UploadSource,
    signal?: AbortSignal
  ): Promise<WireAttachment> {
    const headers: Record<string, string> = {
      'Content-Type': source.blob.type || 'application/octet-stream',
      Accept: 'application/json',
      // HTTP headers are latin-1; an operator's file names are not.
      'X-Attachment-Session': session,
      'X-Attachment-Name': encodeURIComponent(source.name)
    }
    if (source.relPath) headers['X-Attachment-Relpath'] = encodeURIComponent(source.relPath)
    if (source.folderToken) headers['X-Attachment-Folder'] = source.folderToken

    return this.send<WireAttachment>('POST', '/attachments', source.blob, headers, signal)
  }

  /** Fetched once, by the BFF, at attach time — not lazily at send time. */
  attachUrl(session: string, url: string, signal?: AbortSignal): Promise<WireAttachment> {
    return this.request<WireAttachment>('POST', '/attachments/url', { session, url }, signal)
  }


  async removeAttachment(id: string, signal?: AbortSignal): Promise<void> {
    await this.request<void>('DELETE', `/attachments/${encodeURIComponent(id)}`, undefined, signal)
  }

  /** The turn's engine input: the operator's words, then a listing of what they attached. */
  composeTurn(
    session: string,
    text: string,
    ids: string[],
    signal?: AbortSignal
  ): Promise<ComposedTurn> {
    return this.request<ComposedTurn>('POST', '/attachments/context', { session, text, ids }, signal)
  }

  // ------------------------------------------------------- scheduled job runs
  //
  // The gateway's `/api/jobs` has no per-run read. The BFF reads the active profile's own
  // `cron/output/<job_id>/` directory instead — read-only, strict ids, and scoped by the
  // profile header like every other route here (`app/server/job_runs.py`).

  /** The runs the engine kept for one job, newest first. */
  jobRuns(jobId: string, signal?: AbortSignal): Promise<JobRunsResponse> {
    return this.request<JobRunsResponse>(
      'GET',
      `/jobs/${encodeURIComponent(jobId)}/runs`,
      undefined,
      signal
    )
  }

  /** One run's saved markdown, capped server-side. */
  jobRun(jobId: string, runId: string, signal?: AbortSignal): Promise<JobRunResponse> {
    return this.request<JobRunResponse>(
      'GET',
      `/jobs/${encodeURIComponent(jobId)}/runs/${encodeURIComponent(runId)}`,
      undefined,
      signal
    )
  }

  // ---------------------------------------------------------------- previews
  //
  // the file-preview design. Two doors onto the same answer: an attachment is named by its id,
  // a workspace file by its path, and both come back as the same `PreviewMeta` because one
  // function on the server decides what may be rendered. Nothing here classifies a file.

  /** What a path is, without moving its bytes. The shell asks this before choosing a renderer. */
  fileMeta(path: string, signal?: AbortSignal): Promise<PreviewMeta> {
    return this.request<PreviewMeta>('GET', `/files/meta?path=${encodeURIComponent(path)}`, undefined, signal)
  }

  /** The same answer for an attachment, reached by id rather than by path. */
  attachmentMeta(id: string, signal?: AbortSignal): Promise<PreviewMeta> {
    return this.request<PreviewMeta>('GET', `/attachments/${encodeURIComponent(id)}/meta`, undefined, signal)
  }

  /** One capped fetch of a page's text, for a site that will not be framed. */
  urlSnapshot(url: string, signal?: AbortSignal): Promise<UrlSnapshot> {
    return this.request<UrlSnapshot>('POST', '/urls/snapshot', { url }, signal)
  }

  /**
   * The first `limit` bytes of a text file, as text.
   *
   * A range, so a 20 MB log costs 512 KB — the route already answers 206, and this is the one
   * caller that exists because of it. `Content-Disposition: attachment` does not matter to
   * `fetch`: the bytes are data either way, which is exactly why text can be a download on the
   * wire and a paragraph on screen (the file-preview design §4 D4).
   */
  async textPreview(url: string, limit: number, signal?: AbortSignal): Promise<string> {
    const response = await fetch(url, {
      headers: this.scoped({ Range: `bytes=0-${Math.max(0, limit - 1)}` }),
      signal
    })
    if (!response.ok && response.status !== 206) throw await this.describe(response)
    return response.text()
  }

  /**
   * Same contract as the seam client's `request`: idempotent verbs may be retried, and a
   * write may not — a retried upload is a second file, and a retried DELETE is harmless but
   * pointless.
   */
  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    signal?: AbortSignal
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    return this.send<T>(
      method,
      path,
      body === undefined ? undefined : JSON.stringify(body),
      headers,
      signal
    )
  }

  /** The one place a request is made, so there is one error path and one retry rule. */
  private async send<T>(
    method: string,
    path: string,
    body: BodyInit | undefined,
    headers: Record<string, string>,
    signal?: AbortSignal
  ): Promise<T> {
    const idempotent = method === 'GET' || method === 'HEAD' || method === 'OPTIONS'
    const attempts = idempotent ? 2 : 1
    let lastError: unknown

    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        const response = await fetch(this.url(path), {
          method,
          headers: this.scoped(headers),
          body,
          signal
        })
        if (!response.ok) throw await this.describe(response)
        if (response.status === 204) return undefined as T
        const text = await response.text()
        if (!text.trim()) return undefined as T
        try {
          return JSON.parse(text) as T
        } catch {
          // A 2xx with a body that is not JSON is the *server* misbehaving — a proxy's error
          // page, an HTML login redirect — and it must not be reported as an unreachable
          // server, or the retry below sends the same GET a second time and the operator is
          // told to start a server that is already running. `seam/client.ts` has always made
          // this distinction; this copy had drifted from it
          // (the internal audit WEB-6).
          throw new SeamError(
            `The records API answered HTTP ${response.status} with a body that is not JSON.`,
            response.status,
            'not_json'
          )
        }
      } catch (error) {
        if (error instanceof SeamError) throw error
        lastError = error
        if (attempt === attempts - 1) break
      }
    }
    throw new SeamUnreachable('Could not reach the records API. Is app/server running?', lastError)
  }

  private async describe(response: Response): Promise<SeamError> {
    let message = `The records API answered HTTP ${response.status}.`
    let code: string | undefined
    try {
      const body = (await response.json()) as { error?: { message?: string; code?: string } }
      if (body?.error?.message) message = body.error.message
      code = body?.error?.code
    } catch {
      // A non-JSON error body is still an error; keep the status line.
    }
    return new SeamError(message, response.status, code)
  }
}
