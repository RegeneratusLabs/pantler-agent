/**
 * Finding the files a tool call is actually about.
 *
 * `activity.ts` already decides what a call *says* on screen; this decides which files it names,
 * and it exists as its own module because that answer has to be the same after a reload as it was
 * live. It is, because both feeds end up in the same place: a `ToolCall` with `args` filled in
 * from the transcript (`withToolArguments`), `argsPreview` from the stream, and `result` whole in
 * both cases.
 *
 * Two rules from the file-preview design §4 are enforced here rather than downstream:
 *
 *   - **Only structured places are read.** A tool's arguments and its result envelope. Never a
 *     sentence: a path guessed out of prose is how a renderer ends up offering to open the word
 *     "notebook.md" in a paragraph about notebooks.
 *   - **Only an absolute path is a candidate.** A transcript carries no working directory
 *     (`SessionMessage` has no `cwd`), so a relative path cannot be resolved honestly; it stays
 *     plain text on screen and the server never sees it.
 *
 * The engine's own shapes are what is read, and they are known: `write_file` answers with
 * `resolved_path` and `files_modified` (`tools/file_tools.py:900-918`), `read_file` with `path`,
 * and `patch` with the paths it touched.
 */

import { embeddedJson } from './tool-result'

/** A file a call named, and which side of the call it was on. */
export interface FileReference {
  path: string
  name: string
  /** `produced` is a deliverable — the thing the turn made. `read` is context it looked at. */
  role: 'produced' | 'read'
}

/**
 * Tools whose files are worth a card. Named, not inferred, so the list can be read and argued
 * with: a tool that starts naming files and is not here shows its path as plain text, which is
 * the safe way to be wrong.
 */
const REFERENCE_TOOLS: ReadonlySet<string> = new Set([
  'read_file',
  'write_file',
  'patch',
  'vision_analyze',
  'image_generate'
])

/** The tools whose file is the turn's output rather than its input. */
const PRODUCERS: ReadonlySet<string> = new Set(['write_file', 'patch', 'image_generate'])

/** Envelope keys that hold one path. Ordered: the most specific answer first. */
const PATH_KEYS = [
  'resolved_path',
  'saved_path',
  'output_path',
  'file_path',
  'filepath',
  'path',
  'file'
] as const

/** Envelope keys that hold a list of paths. */
const LIST_KEYS = ['files_modified', 'files_written', 'files_created', 'paths'] as const

const MAX_REFERENCES = 3

/** The files one call named, de-duplicated, most specific first, capped. */
export function referencesInTool(
  tool: string,
  source: { argsPreview?: string; args?: string; result?: string }
): FileReference[] {
  const name = (tool ?? '').trim().toLowerCase()
  if (!REFERENCE_TOOLS.has(name)) return []

  const found: string[] = []

  // The tool's own arguments: the request, which is present even when the call failed.
  collectFromJson(source.args, found)
  const preview = (source.argsPreview ?? '').trim()
  if (preview) {
    const parsed = embeddedJson(preview)
    if (parsed) collectFromValue(parsed, found)
    else if (isAbsolutePath(preview)) found.push(preview)
  }

  // The result: which file it actually touched, which is not always the one it was asked for.
  collectFromJson(source.result, found)

  const role: FileReference['role'] = PRODUCERS.has(name) ? 'produced' : 'read'
  const seen = new Set<string>()
  const references: FileReference[] = []
  for (const path of found) {
    if (seen.has(path)) continue
    seen.add(path)
    references.push({ path, name: basenameOf(path), role })
    if (references.length >= MAX_REFERENCES) break
  }
  return references
}

function collectFromJson(text: string | undefined, into: string[]): void {
  const parsed = embeddedJson(text)
  if (parsed) collectFromValue(parsed, into)
}

/** Walk one envelope. Not recursive by design: these are flat tool results, and a deep walk is
 *  how a `path` belonging to some nested diagnostic ends up offered as the turn's deliverable. */
function collectFromValue(value: unknown, into: string[]): void {
  if (!value || typeof value !== 'object') return
  const record = value as Record<string, unknown>

  for (const key of PATH_KEYS) {
    const candidate = record[key]
    if (typeof candidate === 'string' && isAbsolutePath(candidate)) into.push(candidate.trim())
  }
  for (const key of LIST_KEYS) {
    const list = record[key]
    if (!Array.isArray(list)) continue
    for (const entry of list) {
      if (typeof entry === 'string' && isAbsolutePath(entry)) into.push(entry.trim())
    }
  }
}

/**
 * An absolute path, and nothing that merely looks like one.
 *
 * A URL is not a path (`https://x.dev/a` starts with a scheme, not a slash), a Windows drive
 * letter is (`C:\notes.md`), and a bare word is not. The length bound is a guard against a
 * result that holds a whole file of text in a `path`-shaped key.
 */
export function isAbsolutePath(value: string): boolean {
  const text = (value ?? '').trim()
  if (!text || text.length > 4096) return false
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) return false
  if (text.startsWith('/')) return !text.startsWith('//')
  return /^[A-Za-z]:[\\/]/.test(text)
}

export function basenameOf(path: string): string {
  const trimmed = (path ?? '').replace(/[\\/]+$/, '')
  const parts = trimmed.split(/[\\/]/)
  return parts[parts.length - 1] || trimmed
}
