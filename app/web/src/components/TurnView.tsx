import type { ApprovalChoice } from '@shared/wire'
import { PantlerMark } from '../brand/PantlerMark'
import { displayText } from '../seam/reducer'
import type { Turn } from '../state/useConversation'
import { ActivityGroup } from './Activity'
import { TurnAttachmentContext, TurnAttachments } from './AttachChips'
import { ApprovalCard, ToolCard } from './cards'
import { ClarifyCard } from './ClarifyCard'
import { ConnectCard } from './ConnectCard'
import { LearningCard } from './LearningCard'
import { Markdown } from './Markdown'
import { markdownToText } from './markdown'
import { MessageCopy } from './MessageCopy'
import { Prose } from './Prose'
import { FileCard } from './FileCard'
import { MediaFigures } from './MediaFigure'
import { learningLine, learningMoments } from './learning'
import { splitMedia } from './media'
import { ThoughtRow } from './Thought'
import { presentationOf, producedFiles } from './activity'
import { stepsOf } from './thought'

/**
 * One turn. The things it can render are visually distinct on purpose: they carry
 * different authority (the front-end design §4). The operator's words are a bubble; the
 * assistant's answer is rendered markdown; a tool card is the raised, structural thing that is
 * the actual record; an approval is the thing that is blocking.
 *
 * The work behind the answer — searching the web, reading a file — is the fifth thing, and
 * it is deliberately the quietest: a line of words, not a payload (`activity.ts`).
 *
 * The sixth is the one about the assistant itself: the moment it wrote something into its own
 * memory, or changed one of its own skills. It gets a card rather than a line, because unlike
 * the work behind an answer it is a durable change the operator may want to check — and a
 * one-line roll-up of the whole turn, which is what the engine's own client shows for the same
 * reason: a change to what the assistant knows should not be lost to a scroll.
 *
 * The thinking is not a seventh thing beside those: it is the shape of the turn. Each step is
 * some thinking followed by the calls it made, so both are rendered in one sequence by `seq`
 * (`thought.ts`) rather than being collected at the bottom — the reason for a search belongs
 * next to the search.
 *
 * What the turn carried rides with the bubble, and it is the same chips whether the turn was
 * just sent or reloaded from the engine's transcript.
 */
export function TurnView({
  turn,
  onAnswer,
  onClarify,
  onStop,
  onAsk
}: {
  turn: Turn
  onAnswer: (
    choice: ApprovalChoice,
    requestId: string | null,
    executionGeneration: number | null
  ) => Promise<boolean>
  onClarify: (
    answer: string,
    promptId: string | null,
    executionGeneration: number | null
  ) => Promise<boolean>
  onStop: () => void
  /** Send a turn as if the operator typed it. The connect card's "Check now" is the one caller. */
  onAsk?: (text: string) => void
}) {
  const { state } = turn
  // The engine hands a file over with a `MEDIA:` line, which the runs surface passes through
  // verbatim — so the directive is read out of the answer here rather than shown as a path
  // (`components/media.ts`). The prose that is left is the answer; the paths are its attachments.
  const said = splitMedia(displayText(state))
  const answer = said.text
  const attachments = turn.attachments ?? []
  // An attachment-only turn still has a bubble: the chips are the message.
  const hasBubble = Boolean(turn.input) || attachments.length > 0

  const learned = learningMoments(state.tools)
  const produced = producedFiles(state.tools)
  // Only worth a line once there is more than the card already shows: one moment is the card.
  const rollUp = learned.length > 1 ? learningLine(learned) : undefined
  const steps = stepsOf(state.thoughts, state.tools)
  // The run is parked on the operator rather than working. The face says so, and the strip's
  // words match the approval card above rather than claiming work that is not happening.
  const parked = state.phase === 'awaiting_approval' || state.phase === 'awaiting_clarify'

  return (
    <article className="flex flex-col gap-3">
      {hasBubble && (
        <div className="flex max-w-[85%] flex-col items-end gap-1.5 self-end">
          {turn.input && (
            // Linkified for the same reason the answer is: a URL a person pasted is a URL they
            // meant to be able to open (the file-preview design §4 D7).
            <>
              <Prose
                text={turn.input}
                className="rounded-card bg-hover px-3.5 py-2.5 text-sm text-ink"
              />
              <MessageCopy text={turn.input} label="Copy your message" className="-mt-1" />
            </>
          )}
          {attachments.length > 0 && <TurnAttachments attachments={attachments} />}
        </div>
      )}

      <TurnAttachmentContext context={turn.context ?? ''} />

      {steps.map((step, index) => {
        // Only the newest step can still be happening. A card, or a thought that arrived after
        // this run, means the run has settled — which is what lets a live tool run tick and a
        // finished one fold, without either changing shape under the operator mid-turn.
        const live = turn.streaming && index === steps.length - 1

        return step.kind === 'thought' ? (
          <ThoughtRow key={step.key} thought={step.thought} />
        ) : step.kind === 'learning' ? (
          <LearningCard key={step.key} moment={step.moment} />
        ) : step.kind === 'card' ? (
          // A connection offer is its own card: it asks the operator to do something in a browser,
          // which is a different thing from the record a tool card holds (`ConnectCard.tsx`).
          presentationOf(step.call) === 'connect' ? (
            <ConnectCard key={step.key} result={step.call.result} onAsk={onAsk} />
          ) : (
            <ToolCard key={step.key} call={step.call} />
          )
        ) : (
          <ActivityGroup key={step.key} calls={step.calls} live={live} />
        )
      })}

      {produced.length > 0 && (
        // The turn's output, where an output belongs. Deliberately outside the step sequence: a
        // run of activity lines folds into a summary past three steps, and the PDF someone asked
        // for must not fold with it (components/activity.ts `producedFiles`).
        //
        // A file the turn *also* handed over with `MEDIA:` is left out of this row: it is on
        // screen above as the thing it is, and the same deliverable twice reads as two files.
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[0.68rem] text-ink-3">
            {produced.length === 1 ? 'Made' : 'Made these'}
          </span>
          {produced
            .filter(file => !said.paths.includes(file.path))
            .map(file => (
              <FileCard key={file.path} path={file.path} name={file.name} />
            ))}
        </div>
      )}

      {rollUp && (
        <p className="flex items-center gap-2 text-xs text-ink-3">
          <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-accent/70" />
          {rollUp}
        </p>
      )}

      {state.approvals.map(approval => (
        <ApprovalCard
          key={approval.key}
          approval={approval}
          intent={state.interim}
          onAnswer={onAnswer}
        />
      ))}

      {state.clarifies.map(prompt => (
        <ClarifyCard
          key={prompt.key}
          prompt={prompt}
          onAnswer={answer => onClarify(answer, prompt.promptId, prompt.executionGeneration)}
        />
      ))}

      {state.interim && (
        // The interim is a status line, not the answer: plain and quiet, so a rendered heading
        // cannot make it compete with the answer that lands below it.
        <Prose
          text={state.interim}
          className="border-l-2 border-line pl-3 text-sm text-ink-3 italic"
        />
      )}

      {answer && (
        // Rendered markdown, and still subordinate to the card underneath: formatting is
        // presentation, not authority (the front-end design §4; the file-preview design D7).
        // The column fills the pane now, so the answer has no measure cap of its own. Copy takes
        // the readable text, not the markdown source, so a paste into an email is not `**bold**`.
        <div className="flex flex-col gap-1">
          <Markdown variant="chat" text={answer} />
          <MessageCopy text={markdownToText(answer)} label="Copy answer" className="self-start" />
        </div>
      )}

      {/* What the turn handed over. Beside the answer rather than inside the work, because a
          file the assistant made is the turn's output — and the same reasoning that keeps a
          produced file out of a fold (`components/activity.ts`). An image is painted; anything
          else is a card, and the server decides which (`MediaFigure.tsx`). */}
      <MediaFigures paths={said.paths} />

      {turn.needsRefetch && (
        <p className="rounded-card border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          The engine dropped some events, so this turn may be incomplete. The transcript is
          refetched on the next open.
        </p>
      )}

      {state.phase === 'failed' && (
        <p className="rounded-card border border-danger/40 px-3 py-2 text-xs text-danger">
          The run failed{state.error ? `: ${state.error}` : '.'}
        </p>
      )}

      {turn.error && (
        <p className="rounded-card border border-danger/40 px-3 py-2 text-xs text-danger">
          {turn.error}
        </p>
      )}

      {turn.streaming && (
        // The old working line, with the mark in it. 32px of mark in 16px of padding is its
        // half-height clear space, and the row's height is fixed so a change from working to
        // listening cannot move the transcript under the reader.
        <div className="flex min-h-16 items-center gap-4 py-4 text-xs text-ink-3">
          <PantlerMark state={parked ? 'listening' : 'working'} size={32} />
          <span>{parked ? 'Waiting on you' : 'Working'}</span>
          <button
            type="button"
            onClick={onStop}
            className="ml-auto shrink-0 text-accent underline underline-offset-2 hover:brightness-110"
          >
            stop
          </button>
        </div>
      )}
    </article>
  )
}
