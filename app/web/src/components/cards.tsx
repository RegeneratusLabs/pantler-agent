/**
 * The things a turn can render, and they are visually distinct because they carry
 * different authority (the front-end design §4):
 *
 *   - assistant answer   → no authority, a summary        (rendered as markdown by TurnView)
 *   - tool card          → the source of truth: deterministic ledger output
 *   - question card      → the ledger refusing to guess
 *   - approval card      → a parked run waiting on the operator
 *
 * The fifth — the assistant working — is not a card at all and lives in `Activity.tsx`.
 * `activity.ts:presentationOf` is what routes a call here or there, so this file only ever
 * sees a record, a refusal or a failure. The raw output of an unnamed tool is not printed
 * anywhere: it was a rendering of the implementation, not of the work.
 */

import { classifyToolResult, parseInvoiceDraft, MONEY_PACK } from '@shared/pack'
import type { ApprovalChoice } from '@shared/wire'
import { useState } from 'react'
import { Link } from 'react-router'
import type { ApprovalRequest, ToolCall } from '../seam/reducer'
import { Badge } from '../ui/badge'
import { captureHref, parseCapture, type CaptureCard } from './capture'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import {
  ALWAYS_WARNING,
  choiceLabel,
  flaggedAs,
  NO_ANSWER,
  readApproval,
  resolvedLabel
} from './approval'

// ------------------------------------------------------------------ invoice

export function InvoicePreview({ text }: { text: string }) {
  const draft = parseInvoiceDraft(text)
  if (!draft) return null

  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-sm font-semibold text-ink">{draft.number}</span>
        <span className="truncate text-sm text-ink-2">{draft.customer}</span>
        {draft.isDraft && <Badge>draft</Badge>}
      </div>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border-b border-line pb-1 text-left text-[0.7rem] font-medium text-ink-3">
              Qty
            </th>
            <th className="border-b border-line pb-1 text-left text-[0.7rem] font-medium text-ink-3">
              Item
            </th>
            <th className="border-b border-line pb-1 text-right text-[0.7rem] font-medium text-ink-3">
              Unit price
            </th>
            <th className="border-b border-line pb-1 text-right text-[0.7rem] font-medium text-ink-3">
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {draft.lines.map((line, index) => (
            <tr key={index} className="border-b border-line/50">
              <td className="py-1 tabular-nums">
                {line.quantity} {line.unit}
              </td>
              <td className="py-1">{line.description}</td>
              <td className="py-1 text-right tabular-nums">{line.unitPrice}</td>
              <td className="py-1 text-right tabular-nums">{line.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <dl className="mt-2.5 grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-sm">
        {draft.subtotal && (
          <>
            <dt className="text-ink-3">Subtotal</dt>
            <dd className="text-right tabular-nums">{draft.subtotal}</dd>
          </>
        )}
        <dt className="text-ink-3">{draft.taxLabel ?? 'Tax'}</dt>
        <dd className={cn('text-right tabular-nums', draft.taxExcluded && 'text-xs text-warning')}>
          {draft.taxExcluded ? 'not applied — no rate configured' : draft.tax}
        </dd>
        {draft.total && (
          <>
            <dt className="font-semibold text-ink">Total</dt>
            <dd className="text-right font-semibold tabular-nums text-ink">{draft.total}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

// ----------------------------------------------------------------- capture

/**
 * A capture is the operator's words, not a record. The card is quiet and explicit about the
 * difference: the CAP id, when it happened, and the one action that matters — open the paper
 * trail. A promoted capture links to the typed record it became.
 */
export function CapturePreview({ capture }: { capture: CaptureCard }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-sm font-semibold text-ink">{capture.id}</span>
        <Badge tone={capture.status === 'promoted' ? 'ok' : 'warn'}>{capture.status}</Badge>
        {capture.occurredOn && <span className="text-xs text-ink-3">{capture.occurredOn}</span>}
        {capture.source && <span className="text-xs text-ink-disabled">{capture.source}</span>}
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-ink">{capture.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <Link to={captureHref(capture)} className="text-accent underline underline-offset-2 hover:brightness-110">
          Open in paper trail
        </Link>
        {capture.status === 'promoted' && capture.recordId && (
          <span className="text-ink-3">
            {capture.recordType} {capture.recordId}
          </span>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------- tool card

export function ToolCard({ call }: { call: ToolCall }) {
  const kind = classifyToolResult(call.result, MONEY_PACK)
  const [showRaw, setShowRaw] = useState(false)
  const parsed = kind === 'ok' ? parseInvoiceDraft(call.result) : null
  const capture = kind === 'ok' ? parseCapture(call.result) : null

  return (
    <section
      className={cn(
        'flex flex-col gap-2.5 rounded-card border bg-raised p-3.5',
        kind === 'question' ? 'border-warning/45 bg-warning/5' : 'border-line',
        kind === 'error' && 'border-danger/45'
      )}
    >
      <header className="flex items-center gap-2.5">
        <h3 className="min-w-0 flex-1 truncate font-mono text-xs text-ink-2">
          {capture ? 'capture' : call.tool.replace(/_/g, ' ')}
        </h3>
        <ToolStatus call={call} />
      </header>

      {kind === 'question' && (
        <>
          <p className="text-sm font-medium text-warning">{call.result}</p>
          <p className="text-xs text-ink-3">
            Answer below — nothing has been created or sent.
          </p>
        </>
      )}

      {kind === 'error' && (
        <p className="text-sm text-danger">{call.result ?? 'The tool failed.'}</p>
      )}

      {capture && !showRaw && <CapturePreview capture={capture} />}

      {capture && showRaw && (
        <pre className="max-h-72 overflow-auto font-mono text-xs whitespace-pre-wrap break-words text-ink-3">
          {call.result}
        </pre>
      )}

      {parsed && !showRaw && <InvoicePreview text={call.result ?? ''} />}

      {parsed && showRaw && (
        <pre className="max-h-72 overflow-auto font-mono text-xs whitespace-pre-wrap break-words text-ink-3">
          {call.result}
        </pre>
      )}

      {(parsed || capture) && (
        <button
          type="button"
          className="self-start text-xs text-accent underline underline-offset-2 hover:brightness-110"
          onClick={() => setShowRaw(value => !value)}
        >
          {showRaw ? 'Hide the tool’s exact output' : 'Show the tool’s exact output'}
        </button>
      )}
    </section>
  )
}

function ToolStatus({ call }: { call: ToolCall }) {
  if (call.status === 'running') return <Badge tone="warn">running</Badge>
  if (call.status === 'error') return <Badge tone="danger">failed</Badge>
  return (
    <Badge tone="ok">
      done{typeof call.duration === 'number' ? ` · ${call.duration.toFixed(2)}s` : ''}
    </Badge>
  )
}

// ------------------------------------------------------------- approval card

/** Offered on the card itself. `always` is never one of them — see below. */
const PROMINENT: ApprovalChoice[] = ['once', 'session', 'deny']

/**
 * A generic approval card — engine functionality, not a product feature.
 *
 * pantler gates nothing itself. Money handling is not a centred feature of the product, so
 * the plugin registers no `pre_tool_call` hook and nothing it exposes is outbound. The engine
 * can still stop a run for anything it likes — today that is always a shell command its own
 * detector flagged (`tools/approval_detection.py`) — so this stays a generic capability rather
 * than being deleted with the gate.
 *
 * The card used to print the engine's rule name as its body — "script execution via -e/-c
 * flag" — which asked an operator to approve a detector's vocabulary. It now says what would
 * happen, in words, and shows the command underneath, because that is the only ground truth
 * about what is about to run. `approval.ts` owns the translation and the safety rules behind
 * it; this file only lays it out.
 *
 * Two things are deliberately not softened:
 *
 *   - **The command stays.** Softening the sentence is fine; hiding the evidence is how
 *     someone approves an `rm -rf`. This is the one place code belongs on screen.
 *   - **`always` is never offered beside the others.** It persists a standing rule on the
 *     request's pattern key, so every future matching command stops asking — including
 *     unattended ones. A sticky decision must not be one click from a dialog someone is
 *     trying to dismiss.
 */
export function ApprovalCard({
  approval,
  intent,
  onAnswer
}: {
  approval: ApprovalRequest
  /** The assistant's most recent mid-turn words — its own reason for being here. */
  intent?: string
  /** Resolves true when the engine took the decision; false when it did not land. */
  onAnswer: (
    choice: ApprovalChoice,
    requestId: string | null,
    executionGeneration: number | null
  ) => Promise<boolean>
}) {
  const [advanced, setAdvanced] = useState(false)
  const [showFlag, setShowFlag] = useState(false)
  const [busy, setBusy] = useState(false)

  const read = readApproval({
    description: approval.description,
    command: approval.command,
    smartDenied: approval.smartDenied
  })

  if (approval.resolution) {
    const choice = approval.resolution.choice
    const denied = choice === 'deny'
    return (
      <section className="flex flex-col gap-2.5 rounded-card border border-line bg-surface/50 p-3.5">
        <header className="flex items-center gap-2.5">
          <h3 className="flex-1 text-display text-xs text-ink-3">Approval</h3>
          <Badge tone={denied ? 'danger' : 'ok'}>{resolvedLabel(choice)}</Badge>
        </header>
        <p className="text-sm text-ink-2">
          {denied
            ? 'You said no — nothing ran.'
            : choice === 'always'
              ? 'It ran, and this kind won’t ask again.'
              : 'It ran.'}
        </p>
      </section>
    )
  }

  // The run ended before this was answered. The engine blocks the action on timeout
  // (approvals.timeout, default 300s) and moves on, so there is nothing left to answer —
  // showing buttons here would be a lie, and blocking the composer would be worse.
  if (approval.expired) {
    return (
      <section className="flex flex-col gap-2.5 rounded-card border border-line bg-surface/50 p-3.5">
        <header className="flex items-center gap-2.5">
          <h3 className="flex-1 text-display text-xs text-ink-3">Approval</h3>
          <Badge tone="danger">not answered in time</Badge>
        </header>
        <p className="text-sm text-ink-2">
          You didn’t answer in time, so it didn’t run. Nothing happened — ask again when you
          are ready.
        </p>
      </section>
    )
  }

  const prominent = approval.choices.filter(choice => PROMINENT.includes(choice))
  const deferred = approval.choices.filter(choice => !PROMINENT.includes(choice))
  const high = read.tone === 'high'

  const send = (choice: ApprovalChoice) => {
    setBusy(true)
    // `busy` disables every button, and the only other thing that clears it is this card being
    // replaced by its answered form — which needs a resolution the engine may never send. So a
    // decision that failed to land has to clear it here, or the operator is left with a card
    // that looks live and cannot be clicked (the internal audit WEB-3).
    void onAnswer(choice, approval.requestId, approval.executionGeneration).then(
      delivered => {
        if (!delivered) setBusy(false)
      },
      () => setBusy(false)
    )
  }

  return (
    <section
      className={cn(
        'flex flex-col gap-3 rounded-card border p-3.5',
        high
          ? 'border-warning/50 bg-warning/5'
          : 'border-accent/50 bg-raised shadow-[0_0_0_1px_rgba(166,181,150,0.08)]'
      )}
    >
      <header className="flex items-center gap-2.5">
        <h3 className="flex-1 text-sm font-semibold text-ink">
          {read.override
            ? 'Something already said no'
            : read.kind === 'command'
              ? 'May I run this?'
              : 'May I do this?'}
        </h3>
        <Badge tone="warn">waiting on you</Badge>
      </header>

      {intent && (
        <p className="line-clamp-3 text-sm text-ink-3 italic">{intent}</p>
      )}

      <p className={cn('text-[1.02rem] font-medium', high ? 'text-warning' : 'text-ink')}>
        {read.what}
      </p>

      {approval.command && (
        <pre className="max-h-28 overflow-auto rounded-lg border border-line bg-surface px-3 py-2 font-mono text-xs whitespace-pre-wrap break-words text-ink-2">
          {approval.command}
        </pre>
      )}

      <div className="flex flex-wrap gap-2">
        {prominent.map(choice => (
          <Button
            key={choice}
            // A destructive command gets no highlighted default: every choice carries the
            // same weight, so nothing is nudged. An ordinary question keeps its clear one.
            variant={high ? 'secondary' : choice === 'deny' ? 'secondary' : 'primary'}
            disabled={busy}
            onClick={() => send(choice)}
          >
            {choiceLabel(choice, read.kind)}
          </Button>
        ))}
      </div>

      <p className="text-xs text-ink-3">{NO_ANSWER}</p>

      <button
        type="button"
        aria-expanded={showFlag}
        className="self-start text-xs text-ink-disabled underline underline-offset-2 hover:text-ink-3"
        onClick={() => setShowFlag(value => !value)}
      >
        {showFlag ? 'hide what the engine called it' : 'what the engine called it'}
      </button>

      {showFlag && (
        <p className="font-mono text-xs text-ink-3">{flaggedAs(approval.description)}</p>
      )}

      {deferred.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-line pt-2.5">
          <button
            type="button"
            className="self-start text-xs text-accent underline underline-offset-2 hover:brightness-110"
            onClick={() => setAdvanced(value => !value)}
          >
            {advanced ? 'Hide' : 'More options'}
          </button>
          {advanced && (
            <>
              <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                {ALWAYS_WARNING}
              </p>
              <div className="flex flex-wrap gap-2">
                {deferred.map(choice => (
                  <Button
                    key={choice}
                    variant="danger"
                    disabled={busy}
                    onClick={() => send(choice)}
                  >
                    {choiceLabel(choice, read.kind)}
                  </Button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
