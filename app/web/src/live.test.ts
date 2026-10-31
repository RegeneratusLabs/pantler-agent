/**
 * The live check — Phase 0's definition of done, executed against a real engine.
 *
 * This is the front end's half of the golden-conversation suite. It drives the SAME
 * client and the SAME reducer the screens use, against the running dev gateway, and
 * asserts on what an operator would have seen. `scripts/golden.py` asserts on the tool calls
 * the engine made; this asserts on the rendering of them.
 *
 * Each scenario gets its OWN session. Sharing one session across scenarios leaves the
 * conversation mid-thread (for example, parked on an unanswered ambiguity question), and
 * a follow-up then has no context to refer to.
 *
 * Skipped unless PANTLER_LIVE=1, because it costs real model calls:
 *
 *     PANTLER_LIVE=1 npx vitest run src/live.test.ts
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { classifyToolResult, parseInvoiceDraft } from '@shared/pack'
import type { ApprovalChoice, RunEvent } from '@shared/wire'
import { SeamClient } from './seam/client'
import { applyFrame, createRunState, displayText, type RunState } from './seam/reducer'

const live = process.env.PANTLER_LIVE === '1'
// The dev profile's key file, relative to this file so a fresh clone can run the suite with
// PANTLER_LIVE=1. `PANTLER_ENV_FILE` overrides it for a profile installed elsewhere.
const ENV_FILE =
  process.env.PANTLER_ENV_FILE ??
  fileURLToPath(new URL('../../../.hermes-dev/profiles/pantler/.env', import.meta.url))
const BASE_URL = process.env.PANTLER_API ?? 'http://127.0.0.1:8644'
// The host gateway answers on `/p/<name>/`; the bare route is the default profile, which has no
// pantler plugins. Derived from the key file's profile in scripts/golden.py the same way.
const PROFILE = process.env.PANTLER_PROFILE ?? 'pantler'

function apiKey(): string {
  const raw = readFileSync(ENV_FILE, 'utf8')
  for (const line of raw.split('\n')) {
    if (line.startsWith('API_SERVER_KEY=')) return line.slice('API_SERVER_KEY='.length).trim()
  }
  throw new Error(`no API_SERVER_KEY in ${ENV_FILE}`)
}

interface Outcome {
  state: RunState
  events: RunEvent[]
  approvalsAnswered: { choice: ApprovalChoice; description: string }[]
}

/** A short description of what actually happened, for when an assertion fails. */
function diagnose(outcome: Outcome): string {
  const tools = outcome.state.tools.map(tool => `${tool.tool}:${tool.status}`).join(', ') || '(none)'
  return [
    `phase=${outcome.state.phase}`,
    `tools=[${tools}]`,
    `approvals=${outcome.state.approvals.length}`,
    `reply=${JSON.stringify(displayText(outcome.state).slice(0, 300))}`
  ].join('\n')
}

/**
 * Run one turn to completion. Mirrors what the hook does in the browser, minus React.
 *
 * `decide` answers an approval if one arrives. Nothing in this plugin is outbound so none
 * should, but answering keeps a surprise from hanging the run — and the surprise is then
 * caught by the assertion in "parks nothing for approval" rather than by a timeout.
 */
async function runTurn(
  client: SeamClient,
  sessionId: string,
  input: string,
  decide: (description: string) => ApprovalChoice = () => 'deny'
): Promise<Outcome> {
  const started = await client.startRun(input, sessionId)
  let state = createRunState(started.run_id)
  const events: RunEvent[] = []
  const approvalsAnswered: Outcome['approvalsAnswered'] = []

  for await (const frame of client.streamRun(started.run_id, { lastSeq: state.lastSeq })) {
    state = applyFrame(state, frame)
    events.push(frame.data)

    if (frame.data.event === 'approval.request') {
      const event = frame.data as {
        description?: string
        request_id?: string
        prompt_id?: string
        execution_generation?: number
      }
      const description = event.description ?? ''
      const choice = decide(description)
      approvalsAnswered.push({ choice, description })
      await client.respondToApproval(
        started.run_id,
        choice,
        event.request_id ?? event.prompt_id ?? null,
        event.execution_generation ?? null
      )
    }

    if (
      state.phase === 'completed' ||
      state.phase === 'failed' ||
      state.phase === 'cancelled' ||
      state.phase === 'interrupted'
    ) {
      break
    }
  }

  return { state, events, approvalsAnswered }
}

describe.runIf(live)('live: the Phase 0 definition of done', () => {
  // When the dev server supplies the key through the proxy, the client can hold nothing —
  // which is exactly the browser's situation. Set PANTLER_CLIENT_KEY='' to exercise it.
  // `describe.runIf` still runs this callback to collect the tests, so the key is only read when
  // the suite will actually run: a runner has no dev profile and no key file, and must skip.
  const clientKey = !live
    ? ''
    : process.env.PANTLER_CLIENT_KEY !== undefined
      ? process.env.PANTLER_CLIENT_KEY
      : apiKey()
  const client = new SeamClient({ baseUrl: BASE_URL, apiKey: clientKey, profile: PROFILE })
  const session = (name: string) => `live-${name}-${Date.now().toString(16)}`

  it('probes the engine and finds the records toolset', async () => {
    const health = await client.health()
    expect(health).toBeTruthy()

    const capabilities = await client.capabilities()
    expect(capabilities.features.run_events_sse).toBe(true)

    const { data } = await client.toolsets()
    const records = data.find(toolset => toolset.name === 'records')
    expect(records?.enabled).toBe(true)
    expect(records?.tools).toContain('invoice_create')
    expect(records?.tools).toContain('invoice_show')
    // Retired deliberately: money handling is not a centred feature, and a send tool
    // without a delivery path only told the operator something untrue.
    expect(records?.tools).not.toContain('invoice_send')
  }, 30_000)

  it('renders the golden draft from the tool result, not the prose', async () => {
    const outcome = await runTurn(
      client,
      session('draft'),
      'Invoice Bellview CSA for 12 kilos of beans and four dozen eggs'
    )
    const { state } = outcome

    expect(state.phase, diagnose(outcome)).toBe('completed')

    const created = state.tools.find(tool => tool.tool === 'invoice_create')
    expect(created, diagnose(outcome)).toBeDefined()
    expect(created!.status, diagnose(outcome)).toBe('ok')

    // The card renders from the tool's result, which is the deterministic ledger output.
    const draft = parseInvoiceDraft(created!.result)
    expect(draft, `could not parse the draft from: ${created!.result}`).not.toBeNull()
    expect(draft!.customer).toBe('Bellview CSA')
    expect(draft!.lines).toHaveLength(2)
    expect(draft!.subtotal).toBe('$180.00')
    expect(draft!.tax).toBe('$18.00')
    expect(draft!.total).toBe('$198.00')
    expect(draft!.isDraft).toBe(true)
  }, 180_000)

  it('refuses to guess an ambiguous customer and asks instead', async () => {
    const outcome = await runTurn(client, session('ambiguous'), 'Invoice Bellview for 12 kilos of beans')
    const { state } = outcome

    const asked = state.tools.filter(
      tool => tool.result && classifyToolResult(tool.result) === 'question'
    )
    expect(asked.length, diagnose(outcome)).toBeGreaterThan(0)
    expect(asked[0].result).toMatch(/which|did you mean|Bellview/i)

    // The tool DID run — and that is the point. `invoice_create` is what refuses to guess;
    // it returns the question instead of a draft. So the assertion is that no draft came
    // back, not that the tool never ran.
    const drafts = state.tools
      .map(tool => parseInvoiceDraft(tool.result))
      .filter((draft): draft is NonNullable<typeof draft> => draft !== null)
    expect(drafts, `should not have produced a draft: ${diagnose(outcome)}`).toHaveLength(0)
  }, 180_000)

  it('parks nothing for approval, because nothing here is outbound', async () => {
    // A regression guard for the decision to retire the gate. If a `pre_tool_call` hook is
    // ever added back, or an outbound tool reappears, this fails — which is the point: it
    // should be a deliberate act, not a quiet drift.
    const outcome = await runTurn(
      client,
      session('nogate'),
      'Invoice Bellview CSA for 12 kilos of beans and then send it to them'
    )

    expect(outcome.approvalsAnswered, diagnose(outcome)).toHaveLength(0)
    expect(
      outcome.events.some(event => event.event === 'approval.request'),
      `something asked for approval:\n${diagnose(outcome)}`
    ).toBe(false)
    expect(outcome.state.approvals, diagnose(outcome)).toHaveLength(0)

    // And the request to send must not be reported as done.
    expect(outcome.state.tools.some(tool => tool.tool === 'invoice_send')).toBe(false)
    expect(outcome.state.phase, diagnose(outcome)).toBe('completed')
  }, 180_000)
})
