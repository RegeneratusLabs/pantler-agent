import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject
} from 'react'
import { PanelRightOpen } from 'lucide-react'
import { cn } from '../ui/cn'
import { targetName, type PreviewTarget } from './preview'
import { PreviewSidebar } from './PreviewSidebar'
import {
  EMPTY_PREVIEW_STACK,
  closePreview,
  currentTarget,
  dismissPreview,
  openPreview,
  showPreview,
  togglePreview,
  type PreviewStack
} from './preview-stack'

/**
 * The one preview pane, and the way everything else asks for it.
 *
 * A preview can be opened from four places that have nothing to do with each other — a chip in
 * the composer, a chip in a turn, a path behind an activity line, a URL in a paragraph — and
 * threading a callback through each of those trees would mean four chances for one of them to
 * drift. So the host is mounted once, at the conversation, and everything else asks it.
 *
 * It is also the layout: the pane is a column *inside* the chat, on the right of the transcript
 * and the composer, so the operator keeps talking while a document is open (`PreviewSidebar.tsx`).
 * And it is what keeps the pane out of the turn's render path: opening a file does not re-render
 * the transcript.
 */
interface PreviewApi {
  open: (target: PreviewTarget) => void
}

const PreviewContext = createContext<PreviewApi>({ open: () => {} })

export function PreviewHost({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<PreviewStack>(EMPTY_PREVIEW_STACK)
  const tabRef = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)

  // Focus follows the pane: it was open, the operator read something, it closed — and the control
  // that closed it is gone with it. Focus goes to the tab, which is the way back, rather than to
  // nowhere (the browser's answer) or to the composer, where the next keystroke would land in a
  // message nobody meant to write.
  useEffect(() => {
    if (wasOpen.current && !stack.open) tabRef.current?.focus()
    wasOpen.current = stack.open
  }, [stack.open])

  const open = useCallback(
    (target: PreviewTarget) => setStack(state => openPreview(state, target)),
    []
  )
  const show = useCallback(
    (target: PreviewTarget) => setStack(state => showPreview(state, target)),
    []
  )
  const dismiss = useCallback(
    (target: PreviewTarget) => setStack(state => dismissPreview(state, target)),
    []
  )
  const close = useCallback(() => setStack(closePreview), [])
  const reveal = useCallback(() => setStack(togglePreview), [])

  const api = useMemo(() => ({ open }), [open])

  return (
    <PreviewContext.Provider value={api}>
      <div className="relative flex min-h-0 min-w-0 flex-1">
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Nothing is left behind when the pane is hidden: the tab is the way back, and it
              names what it would reopen. */}
          {!stack.open && (
            <PreviewTab target={currentTarget(stack)} onOpen={reveal} buttonRef={tabRef} />
          )}
          {children}
        </div>

        {stack.open && (
          <PreviewSidebar stack={stack} onShow={show} onDismiss={dismiss} onClose={close} />
        )}
      </div>
    </PreviewContext.Provider>
  )
}

export function usePreview(): PreviewApi {
  return useContext(PreviewContext)
}

/** The tab on the right edge of the conversation: the pane's way back, once it has been hidden. */
function PreviewTab({
  target,
  onOpen,
  buttonRef
}: {
  target: PreviewTarget | null
  onOpen: () => void
  buttonRef: RefObject<HTMLButtonElement | null>
}) {
  const name = target ? targetName(target) : ''
  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onOpen}
      aria-label={name ? `Show previews: ${name}` : 'Show previews'}
      title={name ? `Show ${name}` : 'Show previews'}
      className={cn(
        'absolute top-1/2 right-0 z-20 flex -translate-y-1/2 flex-col items-center gap-1.5',
        'rounded-l-md border border-r-0 border-line bg-raised/90 py-2 pr-0 pl-1',
        'text-ink-3 transition-colors hover:bg-hover hover:text-ink'
      )}
    >
      <PanelRightOpen className="size-3.5" aria-hidden />
      <span className="text-display text-[0.6rem] [writing-mode:vertical-rl]">Previews</span>
    </button>
  )
}
