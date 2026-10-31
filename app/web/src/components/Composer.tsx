import {
  ArrowUp,
  ClipboardPaste,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Link2,
  Square
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent
} from 'react'
import { Button } from '../ui/button'
import { cn } from '../ui/cn'
import { COMPOSER_PLACEHOLDER } from '../chat/examples'
import {
  LARGE_PASTE_CHARS,
  largePasteName,
  pastedName,
  type UseDraftAttachments
} from '../state/attachments'
import { AttachChips } from './AttachChips'
import { AttachInputs, AttachMenu, type AttachMenuRow } from './AttachMenu'
import { UrlAttachDialog } from './UrlAttachDialog'

/**
 * The composer.
 *
 * Everything an operator can attach comes through here: the ATTACH menu (Files, Folder,
 * Images, Paste image, URL), the paste event, and the pickers behind each row. The drop zone
 * is one level up, on the conversation, because dropping a photograph "onto the chat" is the
 * gesture people actually make.
 *
 * An attachment alone is enough to send — the reference's attachment-only turn — and Send is
 * held while an upload is still in flight, because a turn that names a file the server has
 * not finished writing would be a lie.
 *
 * **One slot, two actions.** While a run is in flight the send button *becomes* the stop
 * button rather than gaining a neighbour: the thing in that corner is what pressing it does to
 * the conversation, and "send" is not one of the options until the turn that is running has
 * finished. Stopping is the operator's own act — it does not wait on a draft or an upload, so it
 * stays pressable while the textarea beside it does not (`ChatPage` passes `running`).
 */
export function Composer({
  disabled,
  disabledReason,
  running,
  onStop,
  draft,
  onSend,
  initialValue
}: {
  disabled: boolean
  disabledReason?: string
  /** A run is in flight: the send button is a stop button. */
  running: boolean
  onStop: () => void
  draft: UseDraftAttachments
  onSend: (input: string, attachmentIds: string[]) => void
  /**
   * A draft to start the composer with — the Scheduled jobs page's “Ask the assistant” fills a
   * task in here. Read once, on mount: the conversation is keyed by session, so a later session
   * mounts a new composer, and typing is never overwritten by a re-render.
   */
  initialValue?: string
}) {
  const [value, setValue] = useState(initialValue ?? '')
  const [urlOpen, setUrlOpen] = useState(false)
  const [clipboardNote, setClipboardNote] = useState<string | undefined>()
  const area = useRef<HTMLTextAreaElement>(null)
  const pickers = useRef<{
    files: React.RefObject<HTMLInputElement | null>
    folder: React.RefObject<HTMLInputElement | null>
    images: React.RefObject<HTMLInputElement | null>
  } | null>(null)

  // The textarea grows with its content; a draft that starts longer than one line needs the
  // same treatment it would have got if it had been typed.
  useEffect(() => {
    const node = area.current
    if (!node || !initialValue) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 200)}px`
  }, [initialValue])

  const holdPickers = useCallback(
    (refs: {
      files: React.RefObject<HTMLInputElement | null>
      folder: React.RefObject<HTMLInputElement | null>
      images: React.RefObject<HTMLInputElement | null>
    }) => {
      pickers.current = refs
    },
    []
  )

  const ready = draft.attachments.filter(attachment => attachment.status === 'ready').length
  const blocked = disabled || draft.busy

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (blocked) return
    const text = value.trim()
    // Nothing to send and nothing ready: this is not a send at all, so it must not take the
    // tray. `take()` clears the chips and revokes their object URLs, and it marks any chip that
    // is not ready as removed — so an Enter with an attachment still uploading, or one that
    // failed, used to delete it without a word (the internal audit WEB-8).
    if (!text && ready === 0) return
    const ids = draft.take()
    if (!text && ids.length === 0) return
    onSend(text, ids)
    setValue('')
    // The textarea is auto-grown by scrollHeight; reset it with the value.
    if (area.current) area.current.style.height = 'auto'
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const attachPasted = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const clipboard = event.clipboardData
      if (!clipboard) return

      // An image pasted from a screenshot has no text and no name. `clipboardData.files` is
      // the only place it appears, and the paste event is the one clipboard path that works
      // on plain HTTP — which a phone on the tailnet is.
      const images = Array.from(clipboard.files ?? []).filter(
        file => file.size > 0 && file.type.startsWith('image/')
      )
      if (images.length > 0) {
        event.preventDefault()
        for (const image of images) {
          draft.addBlob(
            image,
            image.name && image.name !== 'image.png' ? image.name : pastedName(image.type)
          )
        }
        return
      }

      // A very long paste is a document, not a message.
      const text = clipboard.getData('text') ?? ''
      if (text.length > LARGE_PASTE_CHARS) {
        event.preventDefault()
        draft.addBlob(new Blob([text], { type: 'text/plain' }), largePasteName())
      }
    },
    [draft]
  )

  const pasteFromClipboard = useCallback(async () => {
    setClipboardNote(undefined)
    const clipboard = navigator.clipboard
    if (!clipboard?.read) {
      setClipboardNote('This browser will not hand over the clipboard — press Ctrl/⌘+V instead')
      area.current?.focus()
      return
    }
    try {
      const items = await clipboard.read()
      let added = 0
      for (const item of items) {
        const type = item.types.find(candidate => candidate.startsWith('image/'))
        if (!type) continue
        const blob = await item.getType(type)
        draft.addBlob(blob, pastedName(type))
        added += 1
      }
      if (added === 0) {
        setClipboardNote('No image found in the clipboard')
        area.current?.focus()
      }
    } catch {
      setClipboardNote('The browser refused the clipboard — press Ctrl/⌘+V instead')
      area.current?.focus()
    }
  }, [draft])

  const rows: AttachMenuRow[] = [
    {
      id: 'files',
      label: 'Files…',
      icon: FileText,
      onSelect: () => pickers.current?.files.current?.click()
    },
    {
      id: 'folder',
      label: 'Folder…',
      icon: FolderOpen,
      onSelect: () => pickers.current?.folder.current?.click()
    },
    {
      id: 'images',
      label: 'Images…',
      icon: ImageIcon,
      onSelect: () => pickers.current?.images.current?.click()
    },
    {
      id: 'paste',
      label: 'Paste image',
      icon: ClipboardPaste,
      onSelect: () => void pasteFromClipboard()
    },
    {
      id: 'url',
      label: 'URL…',
      icon: Link2,
      onSelect: () => setUrlOpen(true)
    }
  ]

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div
        className={cn(
          'flex flex-col rounded-card border border-line bg-raised p-2',
          'transition-colors focus-within:border-accent'
        )}
      >
        <AttachChips drafts={draft.attachments} onRemove={draft.remove} />

        <div className="flex items-end gap-1">
          <AttachMenu rows={rows} />
          <AttachInputs
            inputs={holdPickers}
            onFiles={(files, options) =>
              draft.addFiles(
                files.map(file => ({ file, relPath: file.webkitRelativePath || undefined })),
                options
              )
            }
          />
          <textarea
            ref={area}
            value={value}
            rows={1}
            onChange={event => {
              setValue(event.target.value)
              const node = event.target
              node.style.height = 'auto'
              node.style.height = `${Math.min(node.scrollHeight, 200)}px`
            }}
            onKeyDown={onKeyDown}
            onPaste={attachPasted}
            placeholder={COMPOSER_PLACEHOLDER}
            disabled={disabled}
            className={cn(
              'max-h-[200px] min-h-6 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm',
              'text-ink placeholder:text-ink-disabled focus:outline-none disabled:opacity-50'
            )}
          />
          {running ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="Stop"
              title="Stop the assistant"
              onClick={onStop}
              className="rounded-lg"
            >
              <Square className="size-3 fill-current" aria-hidden />
            </Button>
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="icon"
              aria-label="Send"
              disabled={blocked || (!value.trim() && ready === 0)}
              className="rounded-lg"
            >
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>
      </div>

      <p className="px-1 text-[0.7rem] text-ink-3">
        {running
          ? (disabledReason ?? 'Working — stop to end the run')
          : disabled
            ? disabledReason
            : draft.busy
              ? 'Attaching…'
              : ((draft.notice ?? clipboardNote) ??
                (ready > 0
                  ? `${ready} attachment${ready === 1 ? '' : 's'} · Enter to send`
                  : 'Enter to send · Shift+Enter for a new line · drop or paste a file'))}
      </p>

      <UrlAttachDialog
        open={urlOpen}
        onClose={() => setUrlOpen(false)}
        onAttach={url => draft.addUrl(url)}
      />
    </form>
  )
}
