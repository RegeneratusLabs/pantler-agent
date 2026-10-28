/**
 * The run reducer — one pure function, `event → state`.
 *
 * No browser, no React, no fetch. The golden-conversation suite asserts on tool calls;
 * this module is what lets the same suite assert on what the *screen* would show.
 *
 * Semantics that matter (all verified against the pinned engine — the front-end design §2):
 *
 *  - `approval.request` PARKS the run. Approval is a state, not a modal: the rest of the
 *    app stays usable while an operator answers.
 *  - A denial is not a failure. The run resumes and the gated tool never ran, so the
 *    resolution is recorded and the UI says "nothing was sent".
 *  - `message.interim` is a SNAPSHOT of mid-turn commentary, not a delta. Appending it
 *    would duplicate text.
 *  - `run.completed.output` is the authoritative final reply; streamed deltas are what the
 *    operator watched arrive. They are kept apart so neither duplicates the other.
 *  - `replay.truncated` means the client fell behind. The state is now untrustworthy and
 *    the UI must refetch the transcript — it is not a warning to ignore.
 *  - **Thinking never arrives on this stream.** `reasoning.available` relays the assistant's own
 *    text, capped at 500 characters (`agent/turn_response_intake.py:103-116` →
 *    `api_server_runs.py:97`), so a turn built from events alone has no thoughts at all;
 *    `state/transcript.ts` is where they come from (the front-end design §2).
 */

import type { ApprovalChoice, RunEvent } from '@shared/wire'

export type RunPhase =
  | 'queued'
  | 'running'
  | 'stopping'
  | 'awaiting_approval'
  | 'awaiting_clarify'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface ToolCall {
  /** Stable key. Tools can run more than once in a turn. */
  key: string
  /**
   * Where this call sits in the turn's own order, from zero.
   *
   * The wire has neither a call id nor a sequence number (`settleTool` explains the first), so
   * the order a call was recorded in IS its sequence. That is what lets a thought be placed
   * among the calls of its step (`components/thought.ts`) whether the calls were streamed or
   * read back out of the transcript.
   */
  seq: number
  tool: string
  argsPreview?: string
  /**
   * The call's arguments in full, from the transcript.
   *
   * The stream never carries them: `tool.started` sends a display preview and `tool.completed`
   * a result capped at 500 characters, redacted before the cap (`api_server_runs.py:101`). The
   * persisted message does have them, so a turn that has been reconciled with the transcript
   * fills this in — which is what lets a card show *what* was remembered rather than the first
   * twenty-five characters of it.
   */
  args?: string
  /** The tool's result text — the source of truth for the card. */
  result?: string
  status: 'running' | 'ok' | 'error'
  duration?: number
  startedAt: number
}

export interface ApprovalRequest {
  key: string
  /**
   * The id the answer must name. A plain run uses `request_id`; the host-multiplex (authority)
   * run uses `prompt_id`. Keeping both in one field is what lets the card answer either shape.
   */
  requestId: string | null
  /** The authority run's generation, which its approval endpoint requires beside the id. */
  executionGeneration: number | null
  /**
   * The engine's own label for why it stopped — one of its 117 command patterns
   * (`tools/approval_detection.py`), so it reads like a rule name, not a sentence.
   * `approval.ts` is where it gets said in words.
   */
  description: string
  /**
   * The command it wants to run, redacted before egress (`api_server.py:113` calls
   * `_redact_approval_command`), so it is safe to show. This is the only ground truth about
   * what is about to happen, and it was being dropped on the floor.
   */
  command?: string
  /**
   * The engine's guardian model already refused this one, so the only choices left are
   * `once` and `deny` — an owner override for a single operation
   * (`_approval_event_choices`, `api_server.py:108`).
   */
  smartDenied?: boolean
  /**
   * Exactly the choices the engine will honour. It derives them from its own
   * `allow_session`/`allow_permanent`, so those two flags need no separate field here.
   */
  choices: ApprovalChoice[]
  patternKey?: string
  resolution?: { choice: ApprovalChoice; at: number }
  /**
   * The run ended without this ever being answered.
   *
   * The engine's `approvals.timeout` (default 300s, `tools/approval_context.py:259`) blocks
   * the action and lets the run continue, and it emits NO `approval.responded` when it does
   * — so without this the card would read "waiting on you" forever on a finished run, and
   * block the composer with it. Not a decision by the operator, and not a failure: the action
   * was blocked.
   */
  expired?: boolean
}

export interface SubagentRun {
  key: string
  id?: string
  goal?: string
  status: 'running' | 'complete'
  summary?: string
}

/**
 * One step's thinking.
 *
 * The stream has none of this (§2 status note), so a thought is always something the durable
 * transcript recorded and the shell read back — which is why it is addressed by the message it
 * came from rather than by anything the run surfaces.
 */
export interface Thought {
  /** Stable key — the persisted message id. Re-reading the same transcript adds nothing. */
  key: string
  text: string
  /**
   * `streaming` marks the newest thought of a turn that has not finished.
   *
   * It does not mean characters are arriving: the engine persists thinking per step, so the
   * text lands whole. It means *this is the step still being read*, and the screen opens its
   * body for that reason. A thought that has been shown stays open after it settles; `status`
   * is what says whether the body is still following the text (`components/Thought.tsx`).
   */
  status: 'streaming' | 'settled'
  /**
   * How many of this turn's tool calls came before this thought.
   *
   * An anchor rather than a position, because a step's reasoning and the calls it produced are
   * written on the same assistant message: a thought always sits ahead of its own calls, and
   * counting calls keeps that true for a streamed turn and a reloaded one alike.
   */
  seq: number
}

/**
 * One clarifying question, as `clarify.request` carries it. The engine asks at most five in one
 * tool call, one prompt at a time; each prompt is answered by `prompt_id` and the generation.
 */
export interface ClarifyPrompt {
  key: string
  promptId: string | null
  executionGeneration: number | null
  question: string
  /** Engine-decorated choices; empty means the question is open-ended. */
  choices: string[]
  multiSelect: boolean
  /** The engine closed it (`clarify.settled`) — answered elsewhere, timed out, or cancelled. */
  settled?: boolean
  /** The run ended first, so nothing can answer it now. */
  expired?: boolean
}

export interface RunState {
  runId: string
  phase: RunPhase
  /** Assistant prose streamed this turn. */
  text: string
  /** Mid-turn commentary snapshot. */
  interim: string
  /** Per-step thinking, in step order. Read from the transcript, never from the stream. */
  thoughts: Thought[]
  tools: ToolCall[]
  approvals: ApprovalRequest[]
  clarifies: ClarifyPrompt[]
  subagents: SubagentRun[]
  /** The authoritative final reply, from `run.completed`. */
  output?: string
  error?: string
  /** SSE `id:` cursor, for `Last-Event-ID` resume. */
  lastSeq: number | null
  truncated: boolean
  eventCount: number
}

const TERMINAL_PHASES: ReadonlySet<RunPhase> = new Set<RunPhase>([
  'completed',
  'failed',
  'cancelled',
  'interrupted'
])

export function isTerminal(phase: RunPhase): boolean {
  return TERMINAL_PHASES.has(phase)
}

export function createRunState(runId: string): RunState {
  return {
    runId,
    phase: 'queued',
    text: '',
    interim: '',
    thoughts: [],
    tools: [],
    approvals: [],
    clarifies: [],
    subagents: [],
    lastSeq: null,
    truncated: false,
    eventCount: 0
  }
}

/**
 * The approvals in this run that are still waiting on the operator.
 *
 * The composer counts these to decide whether to block, and the count is the same rule the
 * transcript renders by: an approval with no resolution that has not expired. The three
 * selectors that used to live here were referenced only from tests — one of them claiming to be
 * "the UI's 'nothing was sent' signal" while `ApprovalCard` writes that sentence itself — and
 * `useConversation` re-implemented this filter inline (the internal audit WEB-17).
 */
export function waitingApprovals(state: RunState): ApprovalRequest[] {
  return state.approvals.filter(approval => !approval.resolution && !approval.expired)
}

/**
 * Close out anything still unanswered once the run has ended.
 *
 * Nothing else will arrive for these: the engine does not emit `approval.responded` on a
 * timeout, so the only reliable signal that an approval will never be answered is the run
 * reaching a terminal state with the approval still open.
 */
function expireUnanswered(approvals: ApprovalRequest[]): ApprovalRequest[] {
  return approvals.map(a => (a.resolution || a.expired ? a : { ...a, expired: true }))
}

/**
 * Expire every approval still waiting in this run state.
 *
 * The terminal events below do this for themselves, but there is one path they cannot cover:
 * the operator stops a run, or its stream drops, and the turn ends *without* a terminal event
 * ever arriving. The approval then stays open for ever, `waiting` never empties, and the
 * composer is disabled with "Answer the approval above first" until the page is reloaded
 * (the internal audit WEB-2). This is that path's way to say the same thing.
 */
export function settleApprovals(state: RunState): RunState {
  const open = state.approvals.some(a => !a.resolution && !a.expired)
  return open ? { ...state, approvals: expireUnanswered(state.approvals) } : state
}

/** The questions in this run still waiting on the operator. */
export function waitingClarifies(state: RunState): ClarifyPrompt[] {
  return state.clarifies.filter(prompt => !prompt.settled && !prompt.expired)
}

function expireClarifies(clarifies: ClarifyPrompt[]): ClarifyPrompt[] {
  return clarifies.map(prompt =>
    prompt.settled || prompt.expired ? prompt : { ...prompt, expired: true }
  )
}

/**
 * Expire every question still waiting in this run state.
 *
 * The same path as `settleApprovals`: a stop or a dropped stream ends the turn without a terminal
 * event, and an open question would otherwise keep the composer disabled for ever.
 */
export function settleClarifies(state: RunState): RunState {
  const open = state.clarifies.some(prompt => !prompt.settled && !prompt.expired)
  return open ? { ...state, clarifies: expireClarifies(state.clarifies) } : state
}

/** The text the UI should render as the assistant's answer. */
export function displayText(state: RunState): string {
  return state.output?.trim() ? state.output : state.text
}

function toolKey(state: RunState, tool: string): string {
  const n = state.tools.filter(t => t.tool === tool).length
  return `${tool}#${n}`
}

/**
 * Mark the oldest still-running call of `tool` as settled.
 *
 * FIFO, not LIFO, and that is forced by the wire: `tool.started`/`tool.completed` carry
 * only the tool NAME — there is no `tool_call_id` to match on (api_server_runs.py:94-96).
 * Tools execute sequentially within a turn, so completions arrive in start order. If the
 * engine ever runs two calls of one tool concurrently, this is the line that breaks.
 */
function settleTool(
  state: RunState,
  tool: string,
  patch: Partial<Pick<ToolCall, 'result' | 'status' | 'duration'>>
): ToolCall[] {
  const tools = [...state.tools]
  for (let i = 0; i < tools.length; i++) {
    if (tools[i].tool === tool && tools[i].status === 'running') {
      tools[i] = { ...tools[i], ...patch }
      return tools
    }
  }
  // No open call — the engine emitted a completion we never saw start. Record it anyway
  // rather than dropping a result the operator needs to see.
  tools.push({
    key: toolKey(state, tool),
    seq: state.tools.length,
    tool,
    status: patch.status ?? 'ok',
    result: patch.result,
    duration: patch.duration,
    startedAt: Date.now()
  })
  return tools
}

export function reduce(state: RunState, event: RunEvent): RunState {
  const e = event as Record<string, unknown>
  const type = String(e.event ?? '')
  const next: RunState = { ...state, eventCount: state.eventCount + 1 }

  switch (type) {
    // ------------------------------------------------------------- lifecycle
    case 'run.queued':
      next.phase = 'queued'
      break

    case 'run.started':
      next.phase = 'running'
      break

    case 'run.stopping':
      next.phase = 'stopping'
      break

    case 'run.steered':
      // A steer is not a state change; the run keeps going.
      break

    case 'run.completed':
      next.phase = 'completed'
      if (typeof e.output === 'string') next.output = e.output
      next.approvals = expireUnanswered(state.approvals)
      next.clarifies = expireClarifies(state.clarifies)
      break

    case 'run.failed':
      next.phase = 'failed'
      next.error = String(e.error ?? e.turn_exit_reason ?? 'The run failed.')
      next.approvals = expireUnanswered(state.approvals)
      next.clarifies = expireClarifies(state.clarifies)
      break

    case 'run.cancelled':
      next.phase = 'cancelled'
      next.approvals = expireUnanswered(state.approvals)
      next.clarifies = expireClarifies(state.clarifies)
      break

    case 'run.interrupted':
      next.phase = 'interrupted'
      next.error = String(e.error ?? 'The run was interrupted.')
      next.approvals = expireUnanswered(state.approvals)
      next.clarifies = expireClarifies(state.clarifies)
      break

    // ---------------------------------------------------------------- text
    case 'message.started':
      next.interim = ''
      break

    case 'message.delta':
    case 'assistant.delta':
      next.text = state.text + String(e.delta ?? '')
      break

    case 'message.interim':
    case 'assistant.commentary':
      // A snapshot, not a delta — and when the engine says the same text also arrived as
      // deltas, storing it as well is what renders the paragraph twice, once in italics and
      // once in the answer. The flag's whole purpose is to prevent that
      // (the internal audit CON-3).
      // The slot is cleared rather than filled when the same text was also streamed: the answer
      // above already carries it, and a snapshot left here is the paragraph shown twice.
      next.interim = e.already_streamed ? '' : String(e.text ?? e.delta ?? '')
      break

    case 'assistant.completed':
      // The Responses API's authoritative final text. We consume the runs surface, but
      // honour it if it ever arrives.
      if (typeof e.text === 'string') next.output = e.text
      break

    case 'reasoning.available':
      // Deliberately produces nothing, and that is a finding rather than an oversight.
      //
      // On this surface the event does not carry thinking: `_relay_thinking` sends the
      // assistant's own message content — reasoning tags stripped, **capped at 500 characters**
      // (`agent/turn_response_intake.py:103-116`) — and the runs surface maps it straight to
      // `{text}` (`api_server_runs.py:97`). A live probe caught exactly that: one event for a
      // whole turn, carrying the ANSWER, arriving after `message.delta`. The genuine thinking
      // exists only per step in the durable transcript (`GET /api/sessions/{id}/messages` →
      // `reasoning`, uncapped), which is where `state/transcript.ts` reads it. The event stays
      // here, tolerated rather than thrown on, so an engine that changes its mind cannot blank
      // a screen.
      break

    // --------------------------------------------------------------- tools
    case 'tool.started': {
      const tool = String(e.tool ?? 'unknown')
      next.tools = [
        ...state.tools,
        {
          key: toolKey(state, tool),
          seq: state.tools.length,
          tool,
          argsPreview: typeof e.preview === 'string' ? e.preview : undefined,
          status: 'running',
          startedAt: Date.now()
        }
      ]
      break
    }

    case 'tool.progress': {
      const tool = e.tool === undefined ? undefined : String(e.tool)
      if (tool === undefined) break
      const tools = [...state.tools]
      for (let i = 0; i < tools.length; i++) {
        if (tools[i].tool === tool && tools[i].status === 'running') {
          tools[i] = { ...tools[i], argsPreview: String(e.preview ?? tools[i].argsPreview ?? '') }
          break
        }
      }
      next.tools = tools
      break
    }

    case 'tool.completed': {
      const tool = String(e.tool ?? 'unknown')
      next.tools = settleTool(state, tool, {
        status: e.error ? 'error' : 'ok',
        result: typeof e.preview === 'string' ? e.preview : undefined,
        duration: typeof e.duration === 'number' ? e.duration : undefined
      })
      break
    }

    case 'tool.failed': {
      const tool = String(e.tool ?? 'unknown')
      next.tools = settleTool(state, tool, {
        status: 'error',
        result: typeof e.error === 'string' ? e.error : undefined
      })
      break
    }

    // -------------------------------------------------- the money gate
    case 'approval.request': {
      const requestId = e.request_id
        ? String(e.request_id)
        : e.prompt_id
          ? String(e.prompt_id)
          : null
      const request: ApprovalRequest = {
        key: `${state.approvals.length}:${requestId ?? ''}`,
        requestId,
        executionGeneration:
          typeof e.execution_generation === 'number' ? e.execution_generation : null,
        description: String(e.description ?? 'This needs your approval.'),
        command: typeof e.command === 'string' && e.command.trim() ? e.command : undefined,
        smartDenied: e.smart_denied === true,
        choices: (Array.isArray(e.choices) ? e.choices : ['once', 'deny']) as ApprovalChoice[],
        patternKey: e.pattern_key ? String(e.pattern_key) : undefined
      }
      next.approvals = [...state.approvals, request]
      next.phase = 'awaiting_approval'
      break
    }

    case 'approval.responded': {
      const choice = String(e.choice ?? '') as ApprovalChoice
      const requestId = e.request_id
        ? String(e.request_id)
        : e.prompt_id
          ? String(e.prompt_id)
          : null
      const approvals = [...state.approvals]
      // Match the exact request when named; otherwise the oldest still-pending one.
      let index = requestId ? approvals.findIndex(a => a.requestId === requestId && !a.resolution) : -1
      if (index === -1) index = approvals.findIndex(a => !a.resolution)
      if (index !== -1) {
        approvals[index] = { ...approvals[index], resolution: { choice, at: Date.now() } }
      }
      next.approvals = approvals
      next.phase = 'running'
      break
    }

    // -------------------------------------------------- clarifying questions
    case 'clarify.request': {
      const promptId = e.prompt_id
        ? String(e.prompt_id)
        : e.request_id
          ? String(e.request_id)
          : null
      const prompt: ClarifyPrompt = {
        key: `${state.clarifies.length}:${promptId ?? ''}`,
        promptId,
        executionGeneration:
          typeof e.execution_generation === 'number' ? e.execution_generation : null,
        question: String(e.question ?? 'The assistant has a question.'),
        choices: Array.isArray(e.choices) ? e.choices.map(String) : [],
        multiSelect: e.multi_select === true
      }
      next.clarifies = [...state.clarifies, prompt]
      if (!isTerminal(state.phase)) next.phase = 'awaiting_clarify'
      break
    }

    case 'clarify.settled': {
      const promptId = e.prompt_id ? String(e.prompt_id) : null
      const clarifies = [...state.clarifies]
      let index = promptId
        ? clarifies.findIndex(prompt => prompt.promptId === promptId && !prompt.settled)
        : -1
      if (index === -1) index = clarifies.findIndex(prompt => !prompt.settled && !prompt.expired)
      if (index !== -1) clarifies[index] = { ...clarifies[index], settled: true }
      next.clarifies = clarifies
      if (!isTerminal(state.phase)) {
        next.phase = clarifies.some(prompt => !prompt.settled && !prompt.expired)
          ? 'awaiting_clarify'
          : 'running'
      }
      break
    }

    // ------------------------------------------------------------ delegation
    case 'subagent.start': {
      const id = e.subagent_id ? String(e.subagent_id) : undefined
      next.subagents = [
        ...state.subagents,
        {
          key: `${state.subagents.length}:${id ?? ''}`,
          id,
          goal: e.goal ? String(e.goal) : undefined,
          status: 'running'
        }
      ]
      break
    }

    case 'subagent.complete': {
      const id = e.subagent_id ? String(e.subagent_id) : undefined
      const subs = [...state.subagents]
      let index = id ? subs.findIndex(s => s.id === id && s.status === 'running') : -1
      if (index === -1) index = subs.map(s => s.status).lastIndexOf('running')
      if (index !== -1) {
        subs[index] = {
          ...subs[index],
          status: 'complete',
          summary: e.summary ? String(e.summary) : undefined
        }
        next.subagents = subs
      }
      break
    }

    // -------------------------------------------------------- the client lagged
    case 'replay.truncated':
      next.truncated = true
      break

    default:
      // Unknown events are counted and otherwise ignored — never thrown on. An upstream
      // addition must not blank an operator's screen.
      break
  }

  return next
}

/** Apply a decoded SSE frame, advancing the resume cursor. */
export function applyFrame(
  state: RunState,
  frame: { id: number | null; data: RunEvent }
): RunState {
  const next = reduce(state, frame.data)
  if (frame.id !== null) next.lastSeq = frame.id
  return next
}
