/**
 * The draft's attachments — everything chosen but not yet sent.
 *
 * Three decisions are in here, and they are the ones worth stating:
 *
 *   1. **Upload happens when the file is chosen.** That is what lets a chip say "uploading",
 *      "too large" or "ready" before the operator has committed to a turn, and it is what the
 *      reference does. Removing a chip deletes the file, so an abandoned draft leaves nothing.
 *   2. **Nothing is sent on the strength of a name.** Every file is one raw POST to the BFF,
 *      which decides the mime, the stored name and the caps. The browser's guesses are hints.
 *   3. **A removed chip is gone.** An upload that finishes after its chip was removed deletes
 *      what it stored rather than resurrecting anything — the same rule the desktop learned
 *      the expensive way (its `updateIfCurrent`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AttachmentKind, WireAttachment } from '@shared/attachments'
import type { BffClient } from '../seam/bff'
import { SeamError } from '../seam/client'

/** Mirrors the BFF's own cap (`MAX_FILE_BYTES` in app/server/attachments.py). */
export const MAX_FILE_BYTES = 25 * 1024 * 1024
/** Mirrors `MAX_FILES_PER_TURN`. */
export const MAX_FILES_PER_TURN = 20
/** Long pasted text becomes a file rather than a wall of text in the composer. */
export const LARGE_PASTE_CHARS = 3000
/** Uploads in flight at once. Enough to overlap, few enough not to swamp a local server. */
const CONCURRENCY = 3

const IMAGE_TYPES = /^image\//i
const IMAGE_EXTENSIONS = /\.(png|jpe?g|gif|webp|bmp|tiff?)$/i

export type DraftStatus = 'uploading' | 'ready' | 'error'

export interface DraftAttachment {
  /** Local identity for this occurrence. Two copies of one file are two chips. */
  key: string
  name: string
  size: number
  kind: AttachmentKind
  mime: string
  status: DraftStatus
  error?: string
  record?: WireAttachment
  /** An object URL, for an image the browser can show before the server sees it. */
  previewUrl?: string
  /** Set for a Folder… pick, so the whole tree lands as one record. */
  relPath?: string
  folderToken?: string
  folderName?: string
}

export interface AddOutcome {
  added: number
  refused: Array<{ name: string; reason: string }>
}

/** A file on its way in, with the path inside its folder when it came from one. */
export interface FileInput {
  file: File
  relPath?: string
}

/** A kind the chip can render before the server has spoken. Replaced by the server's answer. */
export function draftKind(name: string, mime: string): AttachmentKind {
  if (IMAGE_TYPES.test(mime) || IMAGE_EXTENSIONS.test(name)) return 'image'
  if (mime.startsWith('text/')) return 'text'
  if (mime === 'application/pdf') return 'document'
  return 'other'
}

export function isImageDraft(draft: DraftAttachment): boolean {
  return draft.kind === 'image'
}

/** Pasted screenshots have no name; give them one a person can recognise in a listing. */
export function pastedName(mime: string, at: Date = new Date()): string {
  const stamp = [
    at.getFullYear(),
    String(at.getMonth() + 1).padStart(2, '0'),
    String(at.getDate()).padStart(2, '0')
  ].join('')
  const time = [at.getHours(), at.getMinutes(), at.getSeconds()]
    .map(part => String(part).padStart(2, '0'))
    .join('')
  return `pasted-${stamp}-${time}.${extensionFor(mime)}`
}

/** The subtype is usually the extension; where it is not, the file needs a real one. */
function extensionFor(mime: string): string {
  const known: Record<string, string> = {
    'text/plain': 'txt',
    'image/jpeg': 'jpg',
    'image/svg+xml': 'svg',
    'image/tiff': 'tiff',
    'application/json': 'json',
    'application/pdf': 'pdf'
  }
  const cleaned = (mime || '').split(';')[0].trim().toLowerCase()
  return known[cleaned] ?? (cleaned.split('/')[1] || 'bin').replace(/\+.*$/, '')
}

export function largePasteName(at: Date = new Date()): string {
  return pastedName('text/plain', at)
}

/** The folder a picker reported, from the first segment of any relative path. */
export function folderNameFromPaths(paths: readonly string[]): string | undefined {
  const first = paths.find(path => path.includes('/'))
  return first?.split('/')[0]
}

function uniqueKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `a-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function uniqueToken(): string {
  return uniqueKey().replace(/-/g, '').slice(0, 24)
}

function describeError(error: unknown, name: string): string {
  if (error instanceof SeamError) return error.message
  if (error instanceof Error) return `${name}: ${error.message}`
  return `${name}: could not be attached`
}

export interface UseDraftAttachments {
  attachments: DraftAttachment[]
  /** The uploaded ones, in the order they were chosen. */
  readyIds: string[]
  busy: boolean
  /** A message about the last refusal, for the composer's hint line. */
  notice?: string
  addFiles: (inputs: readonly FileInput[], options?: { folder?: boolean }) => AddOutcome
  addBlob: (blob: Blob, name: string) => void
  addUrl: (url: string) => Promise<void>
  remove: (key: string) => void
  /**
   * Hand the ready attachments to a turn and empty the tray.
   *
   * The files stay on disk on purpose — the agent reads them by path, and the transcript
   * shows them again after a reload. Only a chip the operator removed, or one that never
   * finished uploading, is deleted.
   */
  take: () => string[]
}

export function useDraftAttachments(
  sessionId: string,
  bff: BffClient,
  onError?: (message: string) => void
): UseDraftAttachments {
  const [attachments, setAttachments] = useState<DraftAttachment[]>([])
  const [notice, setNotice] = useState<string | undefined>()
  const drafts = useRef(new Map<string, DraftAttachment>())
  // Uploads that started before their chip was removed: when they land, the file they stored
  // is deleted rather than adopted.
  const removed = useRef(new Set<string>())
  const queue = useRef<Array<() => void>>([])
  const active = useRef(0)

  const remember = useCallback((next: DraftAttachment[]) => {
    drafts.current = new Map(next.map(draft => [draft.key, draft]))
    setAttachments(next)
  }, [])

  const patch = useCallback(
    (key: string, changes: Partial<DraftAttachment>) => {
      setAttachments(current => {
        const next = current.map(draft =>
          draft.key === key ? { ...draft, ...changes } : draft
        )
        drafts.current = new Map(next.map(draft => [draft.key, draft]))
        return next
      })
    },
    []
  )

  const pump = useCallback(() => {
    while (active.current < CONCURRENCY && queue.current.length > 0) {
      const task = queue.current.shift()
      if (!task) break
      active.current += 1
      task()
    }
  }, [])

  const enqueue = useCallback(
    (task: () => Promise<void>) => {
      queue.current.push(() => {
        void task().finally(() => {
          active.current -= 1
          pump()
        })
      })
      pump()
    },
    [pump]
  )

  const upload = useCallback(
    (key: string, blob: Blob, name: string, relPath?: string, folderToken?: string) => {
      enqueue(async () => {
        try {
          const record = await bff.uploadAttachment(sessionId, { name, blob, relPath, folderToken })
          if (removed.current.has(key)) {
            // The chip is gone; the file should be too. The id is the store's, not ours.
            await bff.removeAttachment(record.id).catch(() => undefined)
            return
          }
          patch(key, { status: 'ready', record, mime: record.mime, kind: record.kind })
        } catch (error) {
          if (removed.current.has(key)) return
          const message = describeError(error, name)
          patch(key, { status: 'error', error: message })
          onError?.(message)
        } finally {
          // The key is only consulted while this upload is landing, so it is dropped as soon as
          // it has. Without this the set grew for the life of the conversation, one entry per
          // chip the operator ever removed (the internal audit WEB-17).
          removed.current.delete(key)
        }
      })
    },
    [bff, enqueue, onError, patch, sessionId]
  )

  const addFiles = useCallback(
    (inputs: readonly FileInput[], options: { folder?: boolean } = {}): AddOutcome => {
      const current = drafts.current
      const refused: Array<{ name: string; reason: string }> = []
      const accepted: Array<{ draft: DraftAttachment; file: File }> = []

      const folderToken = options.folder ? uniqueToken() : undefined
      const folderName = options.folder
        ? folderNameFromPaths(inputs.map(input => input.relPath ?? ''))
        : undefined

      for (const input of inputs) {
        const file = input.file
        const relPath = input.relPath || file.webkitRelativePath || file.name || 'file'
        const name = file.name || 'file'
        if (file.size === 0) {
          refused.push({ name, reason: 'that file is empty' })
          continue
        }
        if (file.size > MAX_FILE_BYTES) {
          refused.push({ name, reason: `${name} is larger than 25 MB` })
          continue
        }
        if (current.size + accepted.length >= MAX_FILES_PER_TURN) {
          refused.push({ name, reason: `a turn can carry ${MAX_FILES_PER_TURN} attachments` })
          continue
        }
        const isImage = IMAGE_TYPES.test(file.type) || IMAGE_EXTENSIONS.test(name)
        accepted.push({
          file,
          draft: {
            key: uniqueKey(),
            name: options.folder ? `${folderName ?? 'folder'}/${name}` : name,
            size: file.size,
            kind: draftKind(name, file.type),
            mime: file.type || 'application/octet-stream',
            status: 'uploading',
            previewUrl: isImage ? URL.createObjectURL(file) : undefined,
            relPath: options.folder ? relPath : undefined,
            folderToken,
            folderName
          }
        })
      }

      if (accepted.length > 0) {
        remember([...current.values(), ...accepted.map(entry => entry.draft)])
        for (const { draft, file } of accepted) {
          // The store's name is the file's own: the folder prefix is display only, and the
          // relative path already carries the tree.
          upload(draft.key, file, file.name || 'file', draft.relPath, draft.folderToken)
        }
      }

      setNotice(
        refused.length === 0
          ? undefined
          : refused.length === 1
            ? `Could not attach ${refused[0].name}: ${refused[0].reason}`
            : `Could not attach ${refused.length} files — ${refused[0].reason}`
      )
      return { added: accepted.length, refused }
    },
    [remember, upload]
  )

  const addBlob = useCallback(
    (blob: Blob, name: string) => {
      const current = drafts.current
      if (blob.size === 0) {
        setNotice('That paste was empty — nothing was attached')
        return
      }
      if (blob.size > MAX_FILE_BYTES) {
        setNotice(`${name} is larger than 25 MB, so it was not attached`)
        return
      }
      // The same cap the picker enforces. A pasted image, a dropped file and a fetched page all
      // end up in the same turn, and the BFF refuses the turn at send time with a 413 if there
      // are more than it carries (`select_for_turn`) — so the refusal belongs here, where it can
      // still be read (the internal audit WEB-10).
      if (current.size >= MAX_FILES_PER_TURN) {
        setNotice(`a turn can carry ${MAX_FILES_PER_TURN} attachments`)
        return
      }
      const isImage = IMAGE_TYPES.test(blob.type)
      const draft: DraftAttachment = {
        key: uniqueKey(),
        name,
        size: blob.size,
        kind: draftKind(name, blob.type),
        mime: blob.type || 'application/octet-stream',
        status: 'uploading',
        previewUrl: isImage ? URL.createObjectURL(blob) : undefined
      }
      remember([...current.values(), draft])
      upload(draft.key, blob, name)
    },
    [remember, upload]
  )

  const addUrl = useCallback(
    async (url: string) => {
      if (drafts.current.size >= MAX_FILES_PER_TURN) {
        setNotice(`a turn can carry ${MAX_FILES_PER_TURN} attachments`)
        return
      }
      const draft: DraftAttachment = {
        key: uniqueKey(),
        name: url,
        size: 0,
        kind: 'url',
        mime: 'text/html',
        status: 'uploading'
      }
      remember([...drafts.current.values(), draft])
      try {
        const record = await bff.attachUrl(sessionId, url)
        if (removed.current.has(draft.key)) {
          await bff.removeAttachment(record.id).catch(() => undefined)
          return
        }
        patch(draft.key, { status: 'ready', record, name: record.name, size: record.size })
      } catch (error) {
        const message = describeError(error, url)
        patch(draft.key, { status: 'error', error: message })
        onError?.(message)
      }
    },
    [bff, onError, patch, remember, sessionId]
  )

  const remove = useCallback(
    (key: string) => {
      const draft = drafts.current.get(key)
      removed.current.add(key)
      if (draft?.previewUrl) URL.revokeObjectURL(draft.previewUrl)
      remember([...drafts.current.values()].filter(candidate => candidate.key !== key))
      if (draft?.record) void bff.removeAttachment(draft.record.id).catch(() => undefined)
    },
    [bff, remember]
  )

  const take = useCallback((): string[] => {
    const ready = [...drafts.current.values()]
      .filter(draft => draft.status === 'ready' && draft.record)
      .map(draft => draft.record!.id)
    for (const draft of drafts.current.values()) {
      if (draft.previewUrl) URL.revokeObjectURL(draft.previewUrl)
      // A draft that never landed has nothing a turn can use; if its upload is still in
      // flight, delete whatever it stores rather than leave an orphan behind.
      if (draft.status !== 'ready') removed.current.add(draft.key)
    }
    remember([])
    setNotice(undefined)
    return ready
  }, [remember])

  // Leaving a conversation takes the chips with it. It does *not* take the files: a turn
  // that was just sent is about to read them, and the transcript still shows them. What is
  // left behind is swept by age (`--attachments-keep-days`), which is the honest trade — an
  // orphaned upload costs disk, a deleted one costs the answer.
  useEffect(() => {
    return () => {
      for (const draft of drafts.current.values()) {
        if (draft.previewUrl) URL.revokeObjectURL(draft.previewUrl)
        if (draft.status === 'uploading') removed.current.add(draft.key)
      }
      drafts.current = new Map()
      queue.current = []
    }
  }, [sessionId])

  const readyIds = useMemo(
    () =>
      attachments
        .filter(draft => draft.status === 'ready' && draft.record)
        .map(draft => draft.record!.id),
    [attachments]
  )

  const busy = attachments.some(draft => draft.status === 'uploading')

  return { attachments, readyIds, busy, notice, addFiles, addBlob, addUrl, remove, take }
}
