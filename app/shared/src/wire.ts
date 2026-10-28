/**
 * The wire contract for the Hermes seam.
 *
 * Verified against the pinned engine 297552a9d646119871391d202509822cd86330df (v0.22.1) — see
 * the front-end design §2. Two rules encoded here:
 *
 *   1. The event type is the JSON `event` key, NOT an SSE `event:` line.
 *   2. The sequence number lives on the SSE `id:` line, not in the payload. It is what
 *      `Last-Event-ID` resumes from, so it is modelled separately (`SseFrame`).
 */

// ------------------------------------------------------------------ run events

export type RunEventType =
  // lifecycle
  | 'run.queued'
  | 'run.started'
  | 'run.stopping'
  | 'run.steered'
  | 'run.completed'
  | 'run.failed'
  | 'run.cancelled'
  | 'run.interrupted'
  // assistant text
  | 'message.started'
  | 'message.delta'
  | 'message.interim'
  | 'assistant.delta'
  | 'assistant.commentary'
  | 'assistant.completed'
  | 'reasoning.available'
  // tools
  | 'tool.started'
  | 'tool.progress'
  | 'tool.completed'
  | 'tool.failed'
  // approvals — the engine's general mechanism, not a money-only gate
  | 'approval.request'
  | 'approval.responded'
  // clarifying questions — a prompt that parks the run on an answer, like an approval
  | 'clarify.request'
  | 'clarify.settled'
  // delegation
  | 'subagent.start'
  | 'subagent.complete'
  // the client fell behind and must refetch
  | 'replay.truncated'

/** Every event shares this envelope (`_run_event`, api_server_runs.py:176). */
export interface RunEventEnvelope {
  event: string
  run_id: string
  timestamp: number
}

/**
 * The vocabulary as a runtime value, so the reducer test can prove it handles every one
 * rather than trusting a list someone maintained by hand. The type annotation is the
 * exhaustiveness check: adding to `RunEventType` without adding here fails the build.
 */
export const RUN_EVENT_TYPES = [
  'run.queued',
  'run.started',
  'run.stopping',
  'run.steered',
  'run.completed',
  'run.failed',
  'run.cancelled',
  'run.interrupted',
  'message.started',
  'message.delta',
  'message.interim',
  'assistant.delta',
  'assistant.commentary',
  'assistant.completed',
  'reasoning.available',
  'tool.started',
  'tool.progress',
  'tool.completed',
  'tool.failed',
  'approval.request',
  'approval.responded',
  'clarify.request',
  'clarify.settled',
  'subagent.start',
  'subagent.complete',
  'replay.truncated'
] as const satisfies readonly RunEventType[]

export interface RunStartedEvent extends RunEventEnvelope {
  event: 'run.started'
}
export interface RunQueuedEvent extends RunEventEnvelope {
  event: 'run.queued'
  session_id?: string
  model?: string
}

/** Terminal events carry the same flags; `run.completed` additionally carries `output`. */
export interface RunTerminalEvent extends RunEventEnvelope {
  event: 'run.completed' | 'run.failed' | 'run.cancelled' | 'run.interrupted'
  completed?: boolean
  partial?: boolean
  interrupted?: boolean
  turn_exit_reason?: string
  pending_steer?: string
  /** The turn's reply text. Present on `run.completed`. */
  output?: string
  error?: string
  usage?: Record<string, number>
}

export interface MessageDeltaEvent extends RunEventEnvelope {
  event: 'message.delta' | 'assistant.delta'
  delta: string
}

export interface MessageInterimEvent extends RunEventEnvelope {
  event: 'message.interim' | 'assistant.commentary'
  text?: string
  delta?: string
  /**
   * True when the same text was *also* delivered through `message.delta`
   * (`api_server_runs.py:1016-1020`). The flag exists to stop the paragraph being shown twice,
   * and the contract could not see it, so the reducer stored the snapshot beside the streamed
   * answer and `TurnView` rendered both (the internal audit CON-3).
   */
  already_streamed?: boolean
}

export interface ReasoningEvent extends RunEventEnvelope {
  event: 'reasoning.available'
  text: string
}

export interface ToolStartedEvent extends RunEventEnvelope {
  event: 'tool.started'
  tool: string
  /** The call's arguments, as a short preview. */
  preview?: string
}

export interface ToolCompletedEvent extends RunEventEnvelope {
  event: 'tool.completed'
  tool: string
  duration?: number
  error?: boolean
  /**
   * The tool's RESULT text — secret-redacted before truncation, capped at 500 chars
   * (api_server_runs.py:101). This is the source of truth for a tool card; the
   * assistant's prose is not.
   */
  preview?: string
}

export interface ToolFailedEvent extends RunEventEnvelope {
  event: 'tool.failed'
  tool: string
  error?: string
}

export interface ToolProgressEvent extends RunEventEnvelope {
  event: 'tool.progress'
  tool?: string
  preview?: string
}

export type ApprovalChoice = 'once' | 'session' | 'always' | 'deny'

export interface ApprovalRequestEvent extends RunEventEnvelope {
  event: 'approval.request'
  /** The non-authority run shape. */
  request_id?: string
  /** The authority-run shape: the prompt id and the generation the answer must name. */
  prompt_id?: string
  execution_generation?: number
  /** The sentence the engine's approval machinery wrote, shown to the operator as-is. */
  description?: string
  choices?: ApprovalChoice[]
  pattern_key?: string
  command?: string
  smart_denied?: boolean
  allow_session?: boolean
  allow_permanent?: boolean
}

export interface ApprovalRespondedEvent extends RunEventEnvelope {
  event: 'approval.responded'
  choice: ApprovalChoice
  request_id?: string
  prompt_id?: string
  execution_generation?: number
  resolved?: number
}

/**
 * The clarify tool's prompt, one card per question (`session_pending_controls.register_clarify`).
 * The answer names `prompt_id` and the generation; the engine projects `clarify.settled` when the
 * prompt is answered, times out, or the run ends.
 */
export interface ClarifyRequestEvent extends RunEventEnvelope {
  event: 'clarify.request'
  prompt_id?: string
  execution_generation?: number
  question?: string
  /** Engine-decorated: the recommended choice carries "(Recommended)". Empty for free text. */
  choices?: string[]
  multi_select?: boolean
  timeout_s?: number
}

export interface ClarifySettledEvent extends RunEventEnvelope {
  event: 'clarify.settled'
  prompt_id?: string
  execution_generation?: number
}

export interface ReplayTruncatedEvent extends RunEventEnvelope {
  event: 'replay.truncated'
  oldest_retained_seq?: number
  requested_seq?: number
}

/**
 * A delegation's own events. The engine sends up to twenty-two fields
 * (`_SUBAGENT_EVENT_KEYS`, `api_server_runs.py:80-85`); this modelled six of them, so a typed
 * consumer could not show what a delegation cost or did — the tokens, the calls, the files it
 * read and wrote, or the tail of its output (the internal audit CON-8). Anything not
 * listed still arrives through `UnknownRunEvent`'s index signature, which is why the omission
 * was invisible.
 */
export interface SubagentEvent extends RunEventEnvelope {
  event: 'subagent.start' | 'subagent.complete'
  subagent_id?: string
  goal?: string
  status?: string
  summary?: string
  duration_seconds?: number
  cost_usd?: number
  /** How many tasks this delegation was split into, and which one this event is about. */
  task_count?: number
  task_index?: number
  child_session_id?: string | null
  delegation_id?: string | null
  parent_id?: string | null
  depth?: number
  model?: string | null
  tool_count?: number
  input_tokens?: number
  output_tokens?: number
  reasoning_tokens?: number
  api_calls?: number
  files_read?: number
  /** The last lines of its output, as the engine sends them. */
  files_written?: number
  output_tail?: string
}

/** Any event we do not model explicitly still reaches the reducer intact. */
export interface UnknownRunEvent extends RunEventEnvelope {
  [key: string]: unknown
}

export type RunEvent =
  | RunQueuedEvent
  | RunStartedEvent
  | RunTerminalEvent
  | MessageDeltaEvent
  | MessageInterimEvent
  | ReasoningEvent
  | ToolStartedEvent
  | ToolCompletedEvent
  | ToolFailedEvent
  | ToolProgressEvent
  | ApprovalRequestEvent
  | ApprovalRespondedEvent
  | ClarifyRequestEvent
  | ClarifySettledEvent
  | ReplayTruncatedEvent
  | SubagentEvent
  | UnknownRunEvent

/** One decoded SSE frame. `id` is the resume cursor. */
export interface SseFrame {
  id: number | null
  data: RunEvent
}

// ---------------------------------------------------------------- run requests

export interface StartRunRequest {
  input: string
  session_id?: string
  model?: string
  /**
   * The voice's own overlay on the system prompt — how the operator chose to be spoken to.
   *
   * It rides on every turn (`onboarding/personalities.ts`), and the engine accepts it, but it
   * was missing here: the client sent it from a hand-built `Record<string, string>`, so nothing
   * checked the field and no other consumer of this contract could see that the engine takes it
   * (the internal audit WEB-12).
   */
  instructions?: string
}

export interface StartRunResponse {
  run_id: string
  status: string
  replayed?: boolean
}

export interface ApprovalResponse {
  object: string
  run_id: string
  choice: ApprovalChoice
  request_id?: string
  resolved: number
}

/** `POST /v1/runs/{id}/clarify` — the authority run's answer receipt. */
export interface ClarifyResponse {
  run_id: string
  status: string
  prompt_id: string
}

// ---------------------------------------------------------------- capabilities

export interface Capabilities {
  object: string
  platform: string
  model: string
  auth: { type: string; required: boolean }
  runtime: {
    mode: string
    tool_execution: string
    split_runtime: boolean
    description?: string
  }
  features: Record<string, unknown>
  endpoints: Record<string, { method: string; path: string }>
}

export interface ToolsetEntry {
  name: string
  label?: string
  description?: string
  enabled: boolean
  configured?: boolean
  tools?: string[]
}

/**
 * A skill entry. These come from the BFF's `GET /api/skills`, not the engine's `GET /v1/skills`:
 * that route answers 500 on engine 0.22.1, as it did on 0.21.4 and 0.21.6 (its handler passes a keyword this build's
 * `_find_all_skills` does not accept), so the installed tier reads the profile's skill files
 * instead — see `app/server/skills_index.py`.
 */
export interface SkillEntry {
  name: string
  description?: string
  category?: string
  /** False when the engine's `skills.disabled` holds this skill. */
  enabled?: boolean
  [key: string]: unknown
}

/** The skills index as the BFF answers it: `available: false` is a normal answer, not a failure. */
export interface SkillsIndex {
  available: boolean
  reason?: string
  profile?: string
  data: SkillEntry[]
}

// ------------------------------------------------------- the capability registry
//
// `GET /api/capabilities` on our BFF — not the engine's `/v1/capabilities` above, which describes
// the gateway itself. The registry is derived from the files this profile already owns, so a row
// cannot drift from the thing it describes (the internal capability plan §2). Toolsets are deliberately
// absent: their names and their state live on the engine's `GET /v1/toolsets`, and the shell
// composes the two sources into one screen rather than the BFF inventing a second one.

/** What a capability is. The id's prefix is the kind the write path dispatches on. */
export type CapabilityKind = 'skill' | 'plugin' | 'mcp_server' | 'connector'

/**
 * When a write lands: live on the next conversation the engine builds, or only after the gateway
 * is restarted. Skills and toolsets are re-read per agent; plugins and MCP servers are read at
 * load, so their switches answer the second.
 */
export type CapabilityAppliedAt = 'new_conversations' | 'next_restart'

/** Who put the file here — and therefore who may replace it on update. */
export type CapabilityProvenance = 'shipped' | 'bundled' | 'local' | 'user'

export interface Capability {
  /** `<kind>:<name>`, e.g. `skill:invoicing`. The only value ever written back. */
  id: string
  kind: CapabilityKind
  /** The exact engine-facing name — what the engine's own lists hold. */
  name: string
  /** Operator words. Displayed, never written. */
  label: string
  description: string
  /** The skill's category, or `Plugins` / `MCP servers` / `Connectors`. */
  group: string
  enabled: boolean
  /** False ⇒ no switch may be drawn, ever. */
  toggleable: boolean
  /** Why not, when `toggleable` is false — shown instead of a switch. */
  reason: string | null
  applied_at: CapabilityAppliedAt
  /** `credential:NAME` · `credential:NAME?` (optional) · `auth` · `dependencies`. */
  needs: string[]
  provenance: CapabilityProvenance
}

/** The registry as the BFF answers it: `available: false` is a normal answer, not a failure. */
export interface CapabilityRegistry {
  available: boolean
  profile?: string
  reason?: string
  data: Capability[]
}

/** What one write answers: the state it wrote, and when that state becomes real. */
export interface CapabilityWriteResponse {
  id: string
  enabled: boolean
  applies_to: CapabilityAppliedAt
}

// ---------------------------------------------------------------------- health

export interface HealthResponse {
  status?: string
  [key: string]: unknown
}

// -------------------------------------------------------------------- sessions
//
// Probed live against engine 0.22.1, not read from capabilities flags
// (the front-end design §2 — a capability flag is a claim, not a promise):
//
//   GET    /api/sessions                    → { object: 'list', data: SessionSummary[] }
//   POST   /api/sessions                    → { object, session: SessionSummary }
//   GET    /api/sessions/{id}               → { object, session: SessionSummary }
//   PATCH  /api/sessions/{id}               → { object, session: SessionSummary }
//   DELETE /api/sessions/{id}               → 200
//   GET    /api/sessions/{id}/messages      → { object, session_id, data: SessionMessage[] }
//   POST   /api/sessions/{id}/fork          → a new session
//
// `PATCH` accepts exactly these fields and rejects anything else with 400
// `unsupported_session_field`: title · end_reason · pinned · archived · hidden · unread.

export interface SessionSummary {
  id: string
  source?: string
  user_id?: string | null
  model?: string | null
  title?: string | null
  started_at?: number
  ended_at?: number | null
  end_reason?: string | null
  message_count?: number
  tool_call_count?: number
  input_tokens?: number
  output_tokens?: number
  /**
   * Cache reads and writes ride along in the engine's usage payload "so a cost poller does not
   * book them as full-price input" (`api_server_runs.py:86-91`), and they were not modelled
   * here (the internal audit CON-8).
   */
  cache_read_tokens?: number
  cache_write_tokens?: number
  reasoning_tokens?: number
  estimated_cost_usd?: number | null
  /** What the provider actually charged, when it has been reconciled. */
  actual_cost_usd?: number | null
  api_call_count?: number
  last_active?: number
  preview?: string | null
  pinned?: boolean
  archived?: boolean
  hidden?: boolean
  parent_session_id?: string | null
  is_internal_child?: boolean
}

/**
 * `GET /api/sessions` — and the window it is showing.
 *
 * The engine answers the newest `limit` (50 by default) and says whether there are more, with
 * pinned sessions deliberately excluded from the count ("back-filled pins arrive PAST the limit,
 * so counting them would report another page that doesn't exist" — `api_server.py:3061-3065`).
 * The shell modelled only `data`, so the rail presented the newest fifty as the whole list
 * (the internal audit CON-1).
 */
export interface SessionListResponse {
  object: string
  data: SessionSummary[]
  limit?: number
  offset?: number
  /** True when the engine held back sessions past this window. */
  has_more?: boolean
}

export interface SessionResponse {
  object: string
  session: SessionSummary
}

export type SessionRole = 'user' | 'assistant' | 'tool' | 'system' | (string & {})

export interface SessionMessage {
  id: number
  session_id: string
  role: SessionRole
  content: string
  tool_call_id?: string | null
  tool_calls?: Array<{ id?: string; function?: { name?: string; arguments?: string } }> | null
  tool_name?: string | null
  timestamp?: number
  reasoning?: string | null
  reasoning_content?: string | null
  display_kind?: string | null
  /** Why the model stopped, and how many tokens the message cost (both verified on a transcript). */
  finish_reason?: string | null
  token_count?: number | null
}

/**
 * `GET /api/sessions/{id}/messages` — with the page it came from.
 *
 * The engine returns the newest 500 by default (`api_server.py:3241-3252`) and reports the page
 * it served rather than a boolean, so a full page is the signal that older messages exist and
 * were not sent. `replay.truncated` already taught the shell that a transcript can be
 * incomplete; this is the same fact on the read path
 * (the internal audit CON-2).
 */
export interface SessionMessagesResponse {
  object: string
  session_id: string
  data: SessionMessage[]
  pagination?: {
    limit?: number
    offset?: number
    order?: string
    /** How many messages this page carries. `returned === limit` means there may be more. */
    returned?: number
  }
}

/** The fields `PATCH /api/sessions/{id}` will accept, and no others. */
export interface SessionPatch {
  title?: string | null
  end_reason?: string
  pinned?: boolean
  archived?: boolean
  hidden?: boolean
  unread?: boolean
}

export interface CreateSessionRequest {
  id?: string
  title?: string
  model?: string
  source?: string
}

// ------------------------------------------------------------------------ jobs
//
// `GET/POST/PATCH/DELETE /api/jobs` + `…/pause` · `…/resume` · `…/run`.
//
// ⚠ `/api/cron/jobs` is NOT this. That route belongs to the `hermes dashboard`
// server (port 9119) and 404s on the gateway seam. The gateway serves `/api/jobs`.

/**
 * The engine's parsed schedule, as stored on a job. `display` is what the operator typed (or
 * the expression, for a cron schedule) and is mirrored to `schedule_display`.
 *
 * `run_at` is an absolute ISO instant for a one-shot, so a relative form such as `in 30m` can
 * be edited later without being re-evaluated.
 */
export interface CronSchedule {
  kind?: 'once' | 'interval' | 'cron'
  expr?: string
  minutes?: number
  run_at?: string
  display?: string
}

/** `completed` counts finished runs; `times: null` means forever. */
export interface CronRepeat {
  times: number | null
  completed?: number
}

/** The latest attempt from the engine's execution ledger. */
export interface CronExecution {
  status?: string
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface CronJob {
  id: string
  name: string
  prompt?: string
  /** The parsed schedule (not the text — that is `schedule_display`). */
  schedule?: CronSchedule
  /** The schedule as written: a phrase, a cron expression, or an ISO one-shot. */
  schedule_display?: string
  /** Operator-facing, derived from `enabled` plus pause markers. */
  state?: string
  enabled?: boolean
  paused?: boolean
  paused_reason?: string | null
  next_run_at?: string | number | null
  last_run_at?: string | number | null
  /** `ok`, `error`, `delivery_failed`, `blocked_config`, … — absent until the first run. */
  last_status?: string | null
  last_error?: string | null
  /** Consecutive agent failures; delivery failures do not count. */
  failure_streak?: number
  /** The most recent failure, kept after a later success. */
  last_failure?: { at?: string; detail?: string } | null
  run_count?: number
  repeat?: CronRepeat | null
  skills?: string[]
  deliver?: string
  origin?: Record<string, unknown>
  latest_execution?: CronExecution | null
  [key: string]: unknown
}

export interface JobListResponse {
  jobs: CronJob[]
}

export interface JobResponse {
  job: CronJob
}

export interface CreateJobRequest {
  name: string
  schedule: string
  prompt: string
  skills?: string[]
  repeat?: number
  deliver?: string
  paused?: boolean
}

/**
 * `PATCH /api/jobs/{id}` accepts only these fields (the engine's whitelist). An omitted field is
 * left alone; an empty `repeat` clears the limit (forever).
 */
export interface UpdateJobRequest {
  name?: string
  schedule?: string
  prompt?: string
  repeat?: number
  paused?: boolean
}

/**
 * A run's saved output, read by the BFF from the active profile's own cron output directory.
 * This is not an engine route: the gateway exposes `/api/jobs` but no per-run read.
 */
export interface JobRun {
  /** The engine's filename stem, `YYYY-MM-DD_HH-MM-SS`. */
  id: string
  /** When the file was written, as an ISO instant. */
  at: string
  size: number
  /** The first line or two, for the picker. */
  preview?: string
}

export interface JobRunsResponse {
  /** False when the BFF has no profile to read, with the reason rather than an error. */
  available: boolean
  reason?: string
  job_id?: string
  runs: JobRun[]
}

export interface JobRunResponse {
  job_id: string
  run: JobRun & {
    content: string
    /** True when the file is larger than the read cap and `content` is its head. */
    truncated: boolean
  }
}

// ------------------------------------------------------------------- BFF packs

export interface PackField {
  name: string
  label: string
  kind: string
  required?: boolean
  options?: string[]
  reference?: string
  help?: string
}

export interface PackRecordType {
  type: string
  label: string
  plural?: string
  fields: PackField[]
  /** The field(s) that name a record in a list, when the pack declares them. */
  title_field?: string[]
  id_prefix?: string
  id_sequence?: boolean
}

export interface PackScreen {
  id: string
  title: string
  kind?: string
  record_type?: string
  columns?: string[]
}

export interface Pack {
  id: string
  name: string
  version?: string
  description?: string
  enabled?: boolean
  /** True for an operator-authored pack from the profile's custom-packs tree. */
  custom?: boolean
  records?: PackRecordType[]
  screens?: PackScreen[]
}

export interface PackListResponse {
  data: Pack[]
}

// ------------------------------------------------------------------ records
//
// The BFF's read shape for a record: the store envelope plus the pack's fields, already
// flattened into `data`. These are reads only; the page does not write.

export interface StoredRecord {
  id: string
  type: string
  pack: string
  data: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface RecordListResponse {
  data: StoredRecord[]
  total: number
  limit?: number
  offset?: number
}

// ------------------------------------------------------------- engine settings
//
// Two different backends feed the settings screen, and the split is the point:
//
//   * the **seam** (`/api/model/options`) knows the model catalogue — 52 providers, the
//     current one, and its model list. It is read-only.
//   * the **BFF** (`/api/settings`) owns the local files the engine reads at startup,
//     because the engine exposes no settings API at all (`admin_config_rw: false`, and
//     /api/config, /api/env and /api/model/set are all 404 on the gateway).

export interface ModelProvider {
  slug: string
  name: string
  is_current?: boolean
  is_user_defined?: boolean
  /** Only ever populated for the current provider; the rest need authenticating first. */
  models?: string[]
  total_models?: number
  source?: string
  authenticated?: boolean
  /** `api_key`, `oauth_device_code`, … */
  auth_type?: string | null
  /** The env var this provider reads its credential from, when the engine names one. */
  key_env?: string | null
  /** The engine's own one-line instruction, shown verbatim. */
  warning?: string
  featured_models?: string[]
  capabilities?: Record<string, unknown>
}

export interface ModelOptions {
  /** The model in effect. */
  model?: string
  /** The provider in effect. */
  provider?: string
  providers: ModelProvider[]
}

export interface KeyInfo {
  name: string
  is_set: boolean
}

/**
 * One reasoning level the engine accepts, in the engine's own spelling
 * (`agent/reasoning_effort.py`, mirrored by `engine_settings.REASONING_EFFORTS`). `xhigh` is
 * the engine's name for it; a UI may say "Extra high", but this is what gets written.
 */
export type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max' | 'ultra'

/**
 * What `agent.reasoning_effort` holds: a level, or `false` for "do not think".
 *
 * The engine's reader also accepts `none` and `disabled` for the same thing; the BFF normalises
 * all three to `false`, which is the spelling the engine's own writer emits, so this is the only
 * disabled form that ever reaches a file or this page.
 */
export type ReasoningEffortSetting = ReasoningEffort | 'false'

export interface EngineProfileInfo {
  name: string
  dir: string
  config_path: string
  env_path: string
  config_exists: boolean
  env_exists: boolean
  /** False when the `model:` block is not a flat mapping we are willing to rewrite. */
  model_editable: boolean
  /** False when `agent.disabled_toolsets` is not a shape we are willing to rewrite. */
  agent_editable?: boolean
  /** False when `agent.reasoning_effort` is not a shape we are willing to rewrite. */
  reasoning_editable?: boolean
  /** False when `skills.disabled` is not a shape we are willing to rewrite. */
  skills_editable?: boolean
}

export interface EngineSettings {
  available: boolean
  reason?: string
  profile?: EngineProfileInfo
  model?: Record<string, string>
  /**
   * `agent.reasoning_effort`: a `ReasoningEffortSetting`, or — when the file holds something the
   * engine does not recognise — that value verbatim, so the page can say the engine is ignoring
   * it rather than showing a level that is not in force. `null` when the key is unset.
   *
   * A level here is a preference, not a promise: the engine clamps it down to the nearest level
   * the chosen model accepts.
   */
  reasoning_effort?: string | null
  /** `agent.disabled_toolsets` — what the Capabilities switches have turned off. */
  disabled_toolsets?: string[]
  /** `skills.disabled` — the skills switched off. */
  disabled_skills?: string[]
  keys?: KeyInfo[]
  /** The engine reads these files at startup, so a save is inert until it restarts. */
  restart_required?: boolean
}

export interface SettingsWriteResponse {
  restart_required: boolean
}

export interface ModelWriteResponse extends SettingsWriteResponse {
  model: Record<string, string>
}

export interface KeyWriteResponse extends SettingsWriteResponse {
  name: string
  is_set: boolean
}

// ----------------------------------------------------------------- connectors
//
// the Composio notes rail C. The state is Composio's, mapped by the BFF; the shell never
// derives `connected` from a click.

export type ConnectorState =
  | 'not_connected'
  | 'pending'
  | 'connected'
  | 'needs_attention'
  | 'inactive'
  | 'unavailable'

export interface ConnectorAccount {
  id: string
  status: string
  status_reason: string
  /** The provider's own label, when it gave one. Never invented from an id. */
  display_name: string
  created_at: string
  toolkit: string
}

export interface ConnectorStatus {
  id: string
  name: string
  slug: string
  available: boolean
  managed_oauth: boolean
  note: string
  state: ConnectorState
  account: ConnectorAccount | null
  can_connect: boolean
  reason: string | null
}

/** `GET /api/connectors` — `configured: false` is a normal answer, not a failure. */
export interface ConnectorsResponse {
  available: boolean
  configured: boolean
  error: { code: string; message: string } | null
  connectors: ConnectorStatus[]
}

/** `POST /api/connectors/{id}/connect` — an offer, not a connection. */
export interface ConnectorConnectResponse {
  connector: string
  state: ConnectorState
  account: ConnectorAccount | null
  connect_url: string | null
  connected_account_id: string | null
  expires_at: string | null
}

/** `DELETE /api/connectors/{id}`. */
export interface ConnectorDisconnectResponse {
  connector: string
  disconnected: number
  state: ConnectorState
}

export interface ConnectorTool {
  slug: string
  name: string
  description: string
  /** False is the safe default: an unknown tool asks for approval rather than running. */
  read_only: boolean
  /** Present on the single-tool `?tool=` answer: the tool's own input schema. */
  parameters?: Record<string, unknown>
}

/** `GET /api/connectors/{id}/tools` — a list, or one tool with its parameters. */
export interface ConnectorToolsResponse {
  connector: string
  tools?: ConnectorTool[]
  tool?: ConnectorTool
}

/** `POST /api/connectors/{id}/execute` — called by the connectors plugin, after the gate. */
export interface ConnectorExecuteResponse {
  success: boolean
  connector: string
  tool: string
  data: unknown
  error: string | null
  log_id: string | null
}

/**
 * A toolset write is not a restart-required write: the engine re-reads `config.yaml` when it
 * builds an agent, so `applies_to` says where the change lands instead of guessing.
 */
export interface ToolsetWriteResponse {
  disabled_toolsets: string[]
  applies_to: 'new_conversations' | string
}

/** The same contract for `skills.disabled` — the engine's own skill switch. */
export interface SkillWriteResponse {
  disabled_skills: string[]
  applies_to: 'new_conversations' | string
}

/**
 * A reasoning write, with the toolset contract rather than the model one: the level lives in the
 * `agent:` block, which the engine re-reads when it builds an agent, so no restart is implied.
 */
export interface ReasoningEffortWriteResponse {
  reasoning_effort: ReasoningEffortSetting
  applies_to: 'new_conversations' | string
}

// -------------------------------------------------------- what it has learned

/**
 * One memory entry, as the engine's store parses it (`\n§\n` delimited, stripped, non-empty).
 *
 * `id` is the engine's own node-id shape — `memory:<source>:<index>:<fingerprint>` — so an
 * entry here names the same card the engine's journey view names. The fingerprint is a digest
 * of the text, which is what makes the id survive an earlier entry being removed.
 */
export interface MemoryEntry {
  id: string
  source: 'memory' | 'profile' | string
  label: string
  index: number
  text: string
  chars: number
  truncated?: boolean
}

/** One memory file and the engine's own budget for it. */
export interface MemoryFile {
  source: string
  name: string
  label: string
  present: boolean
  /** False when the file exists but cannot be decoded — not the same as "nothing learned". */
  readable: boolean
  limit: number
  modified: number | null
  chars: number | null
  entries: number | null
  percent: number | null
}

export interface MemoryView {
  files: MemoryFile[]
  entries: MemoryEntry[]
  total: number
  readable: boolean
}

/** Where a skill came from. Only `learned` means the assistant wrote it itself. */
export type SkillOrigin = 'learned' | 'bundled' | 'installed' | 'external'

/** A skill, with the provenance `.usage.json` and the ledger actually record. */
export interface SkillProvenance extends SkillEntry {
  origin: SkillOrigin
  /** Epoch seconds; the ledger's own stamp, when it shows the agent creating this skill. */
  learnedAt?: number | null
  createdAt?: string | null
  lastPatchedAt?: number | null
  lastUsedAt?: string | null
  patches?: number
  uses?: number
  state?: string
  pinned?: boolean
}

/**
 * One skill write the engine recorded, with the conversation that caused it.
 *
 * This is the only session-level provenance the engine leaves anywhere
 * (`skills/.curator_ledger.jsonl`), and it is what lets the app say "this conversation is what
 * taught it that" without guessing.
 */
export interface LearningLedgerEntry {
  id: string
  /** Epoch seconds, or null when the stamp could not be read. */
  at: number | null
  atIso?: string | null
  /** `agent` (the assistant, mid-conversation) or `curator` (the background maintainer). */
  actor: string
  /** create | patch | write_file | remove_file | delete … — the engine's own vocabulary. */
  action: string
  skill: string
  session?: string | null
  file?: string | null
  files?: string[]
}

/** The background skill maintainer. Status only: its controls are not on the seam we use. */
export interface CuratorState {
  available: boolean
  paused?: boolean
  runCount?: number
  lastRunAt?: number | null
  lastRunIso?: string | null
  summary?: string | null
  intervalHours?: number | null
}

/** `GET /api/learning` — `available: false` is a normal answer, not a failure. */
export interface LearningIndex {
  available: boolean
  reason?: string
  profile?: string
  memory?: MemoryView | null
  skills?: SkillProvenance[]
  counts?: { listed: number; learned: number; changed: number }
  ledger?: LearningLedgerEntry[]
  curator?: CuratorState | null
}

/** `GET /api/learning/session/{id}` — what one conversation taught it. */
export interface SessionLearning {
  available: boolean
  reason?: string
  session?: string
  data: LearningLedgerEntry[]
}

// ------------------------------------------------------------- previews
//
// the file-preview design §5. The BFF decides what a file *is* and whether it may be served
// inline; the shell routes on the answer rather than re-deriving it from a file name, because a
// name is not evidence and the two must not be able to disagree.

/** `GET /api/files/meta?path=` · `GET /api/attachments/{id}/meta`. */
export interface PreviewMeta {
  path: string
  name: string
  mime: string
  size: number
  size_human: string
  /** The upload-side vocabulary: image · document · text · archive · folder · url · other. */
  kind: string
  /** What the preview should do: image · pdf · media · text · download. */
  render: 'image' | 'pdf' | 'media' | 'text' | 'download'
  content_type: string
  disposition: string
  /** Whether an element may point at the byte route and have the browser render it. */
  inline: boolean
}

/** `POST /api/urls/snapshot` — a page reduced to text, for a site that refuses to be framed. */
export interface UrlSnapshot {
  url: string
  title?: string | null
  mime: string
  text: string
  truncated: boolean
}
