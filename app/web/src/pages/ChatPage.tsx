import { useQueryClient } from '@tanstack/react-query'
import { ArrowDown } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { qk, useApp, useSessionLearning, useSessionTranscript } from '../state/app-context'
import { makeSessionId, useConversation, type Turn } from '../state/useConversation'
import { useDraftAttachments } from '../state/attachments'
import { exampleAsks } from '../chat/examples'
import { useOperatorProfile } from '../onboarding/profile'
import { mascotStateFor } from '../brand/mascot'
import { PantlerMark } from '../brand/PantlerMark'
import { usePresenceReport } from '../state/presence'
import { Button } from '../ui/button'
import { CHAT_COLUMN, CHAT_GUTTER } from '../ui/chat-layout'
import { cn } from '../ui/cn'
import { AttachmentDropZone } from '../components/AttachDropZone'
import { Composer } from '../components/Composer'
import { PreviewHost } from '../components/preview-context'
import { LearningStrip } from '../components/LearningStrip'
import { TurnView } from '../components/TurnView'

/** `/chat` has no name yet: mint one and make it the address, so a reload resumes. */
export function NewChatRedirect() {
  const id = useMemo(() => makeSessionId(), [])
  return <Navigate to={`/chat/${id}`} replace />
}

export function ChatPage() {
  const { sessionId = '' } = useParams()
  // Keyed on the session so switching sessions is a remount, not a state migration.
  return <ChatSession key={sessionId} sessionId={sessionId} />
}

function ChatSession({ sessionId }: { sessionId: string }) {
  const { client, bff } = useApp()
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const transcript = useSessionTranscript(sessionId)
  const messages = transcript.data?.messages
  const mayBeIncomplete = Boolean(transcript.data?.incomplete)
  const messagesError = transcript.error
  const messagesPending = transcript.isPending
  const messagesFailed = transcript.isError
  const { turns, waiting, questions, submit, answer, answerClarify, stop, hydrate } = useConversation(
    client,
    bff,
    sessionId
  )

  // A draft handed over by another screen — Scheduled jobs → “Ask the assistant”. It is read
  // once and cleared from history, so a reload does not resurrect it and a later turn cannot
  // overwrite what the operator has typed since.
  const handedDraft = useMemo(() => {
    const state = location.state as { draft?: unknown } | null
    return typeof state?.draft === 'string' ? state.draft : undefined
  }, [location.state])

  useEffect(() => {
    if (handedDraft) navigate(location.pathname, { replace: true, state: null })
  }, [handedDraft, location.pathname, navigate])
  // The rail and the phone header are outside this hook, so the mark's state has to travel up.
  // A parked prompt outranks a live run: the assistant is blocked on the operator, not working.
  usePresenceReport(mascotStateFor(turns, waiting.length + questions.length))
  // Drafts belong to the conversation, not to the composer: the drop zone is the whole
  // pane, and a chip has to survive a re-render of either.
  const draft = useDraftAttachments(sessionId, bff)

  useEffect(() => {
    if (messages) hydrate(messages)
  }, [messages, hydrate])

  // `transcript.data.messages` is a fresh array on every fetch, so the effect above re-hydrates
  // whenever the engine answers — which is what keeps a turn that finished in another tab from
  // being missed. `mayBeIncomplete` is the read path's half of `replay.truncated`.

  const refreshRail = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.sessions }),
    [queryClient]
  )

  const send = useCallback(
    (input: string, attachmentIds: string[]) => {
      void submit(input, { attachmentIds, onStarted: refreshRail }).then(() => {
        void refreshRail()
        // A turn can teach it something after it has finished answering — the background review
        // and the curator both run on their own thread — so the ledger is re-read once the run
        // has landed rather than only when the conversation is reopened.
        void queryClient.invalidateQueries({ queryKey: qk.sessionLearning(sessionId) })
        void queryClient.invalidateQueries({ queryKey: qk.learning })
        // And the transcript the engine just wrote: the next open must read it, not the copy
        // cached before this turn existed (the internal audit WEB-5).
        void queryClient.invalidateQueries({ queryKey: qk.messages(sessionId) })
      })
    },
    [submit, refreshRail, queryClient, sessionId]
  )

  const streaming = turns.some(turn => turn.streaming)
  const pending = waiting.length + questions.length
  const blocked = streaming || pending > 0
  // The turn the composer's stop button ends. At most one run streams at a time in a session,
  // and the newest is the one the operator is watching (`useConversation` keeps them in order).
  let runningTurn: Turn | undefined
  for (const turn of turns) if (turn.streaming) runningTurn = turn

  // Only asked once the conversation has a turn in it, and never mid-run: what it answers is a
  // record of finished work, and a request per keystroke would be noise.
  const learning = useSessionLearning(sessionId, turns.length > 0 && !streaming)

  const scrollRef = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)

  // Follow the stream, but only while the operator is already at the bottom — scrolling up
  // to read something must not be yanked away by the next delta.
  useEffect(() => {
    const node = scrollRef.current
    if (node && pinned) node.scrollTop = node.scrollHeight
  }, [turns, pinned])

  const onScroll = () => {
    const node = scrollRef.current
    if (!node) return
    setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 80)
  }

  return (
    <AttachmentDropZone
      onFiles={({ inputs, folder }) => draft.addFiles(inputs, { folder })}
    >
      {/* The preview pane is mounted once, here, and everything inside the conversation asks
          for it (the file-preview design §4 D3). Opening a file must not re-render the turns. */}
      <PreviewHost>
      {mayBeIncomplete && turns.length > 0 && (
        // The same fact as `replay.truncated`, on the read path: the engine sent a full page, so
        // there is older conversation it did not send (the internal audit CON-2).
        <div className="border-b border-line bg-raised/60">
          <p className={cn(CHAT_COLUMN, 'py-2 text-xs text-ink-3', CHAT_GUTTER)}>
            This is the newest part of the conversation. Older messages are in the engine but are
            not shown here yet.
          </p>
        </div>
      )}

      {pending > 0 && (
        <div className="border-b border-warning/30 bg-warning/10">
          <p className={cn(CHAT_COLUMN, 'py-2 text-xs text-warning', CHAT_GUTTER)}>
            {pending === 1
              ? 'The assistant is waiting on your answer.'
              : `The assistant is waiting on ${pending} answers.`}
          </p>
        </div>
      )}

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn(CHAT_COLUMN, 'flex flex-col gap-6 py-6', CHAT_GUTTER)}>
          {turns.length === 0 && messagesFailed && (
            <div className="flex flex-col items-start gap-2 rounded-card border border-warning/40 bg-warning/5 p-4">
              <p className="text-sm text-ink-2">
                This conversation could not be read, so it may not be empty.
              </p>
              <p className="text-xs text-ink-3">{describeReadFailure(messagesError)}</p>
              <Button variant="ghost" size="sm" onClick={() => void transcript.refetch()}>
                Try again
              </Button>
            </div>
          )}

          {turns.length === 0 && !messagesPending && !messagesFailed && (
            <EmptyChat onPick={input => send(input, [])} />
          )}

          {turns.map(turn => (
            <TurnView
              key={turn.id}
              turn={turn}
              onAnswer={(choice, requestId, executionGeneration) =>
                answer(turn.id, choice, requestId, executionGeneration)
              }
              onClarify={(clarifyAnswer, promptId, executionGeneration) =>
                answerClarify(turn.id, clarifyAnswer, promptId, executionGeneration)
              }
              onStop={() => stop(turn.id)}
              // The connect card's "Check now": a real turn in the operator's own words, sent by
              // their own click, because only the engine's status action can witness a connection.
              // Guarded like the composer: a "Check now" click while a turn is streaming used to
              // send a second run into a session the engine is already writing to
              // (the internal audit WEB-17). `blocked` is the composer's own condition.
              onAsk={text => {
                if (!blocked) send(text, [])
              }}
            />
          ))}
        </div>
      </div>

      {!pinned && turns.length > 0 && (
        <div className="pointer-events-none relative">
          <Button
            variant="secondary"
            size="icon"
            aria-label="Scroll to latest"
            className="pointer-events-auto absolute -top-11 left-1/2 -translate-x-1/2 rounded-full shadow-lg"
            onClick={() => {
              setPinned(true)
              const node = scrollRef.current
              if (node) node.scrollTop = node.scrollHeight
            }}
          >
            <ArrowDown className="size-4" />
          </Button>
        </div>
      )}

      <LearningStrip rows={learning.data?.data ?? []} />

      <div className="shrink-0 border-t border-line bg-surface/60 backdrop-blur-sm">
        <div className={cn(CHAT_COLUMN, 'py-3', CHAT_GUTTER)}>
          <Composer
            disabled={blocked}
            disabledReason={
              questions.length > 0
                ? 'Answer the question above first'
                : waiting.length > 0
                  ? 'Answer the approval above first'
                  : undefined
            }
            running={Boolean(runningTurn)}
            onStop={() => {
              if (runningTurn) void stop(runningTurn.id)
            }}
            draft={draft}
            onSend={send}
            initialValue={handedDraft}
          />
          <p className="mt-2 flex items-center gap-2 font-mono text-[0.65rem] text-ink-disabled">
            <span className="truncate">session {sessionId}</span>
          </p>
        </div>
      </div>
      </PreviewHost>
    </AttachmentDropZone>
  )
}

function EmptyChat({ onPick }: { onPick: (input: string) => void }) {
  // The examples follow the business the operator described in setup. Reading the profile here
  // rather than in `ChatSession` keeps a settings change from re-rendering the transcript.
  const { work } = useOperatorProfile()
  const examples = exampleAsks(work)
  return (
    <div className="flex flex-col items-center gap-5 py-12 text-center">
      {/* 32px of clear space below the 64px mark: 20px of the column's gap plus this padding.
          The mark is a pat, not a control with a consequence; the composer below is the way in. */}
      <div className="pb-3">
        <PantlerMark state="idle" size={64} interactive enter label="Pantler" />
      </div>
      <h2 className="brand-display text-[1.75rem] leading-[1.15] text-ink sm:text-4xl">
        What needs doing?
      </h2>
      <p className="max-w-xl text-sm text-ink-2">
        Say it the way you would say it to someone helping in the office. Prices, tax and
        customer details come from your own records, and nothing goes out that you did not
        ask for.
      </p>
      <ul className="flex w-full max-w-2xl flex-col gap-1.5">
        {examples.map(example => (
          <li key={example}>
            <button
              type="button"
              onClick={() => onPick(example)}
              className={cn(
                'w-full rounded-lg border border-line bg-raised px-3 py-2 text-left text-sm',
                'text-ink-2 transition-colors hover:border-line-strong hover:text-ink'
              )}
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Why a transcript could not be read, in the operator's words rather than the client's. */
function describeReadFailure(error: unknown): string {
  if (!error) return ''
  if (error instanceof Error) return error.message
  return String(error)
}
