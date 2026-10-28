/**
 * `MEDIA:` — the engine's own way of handing a file to the chat, and how a turn's prose is split
 * around it.
 *
 * The engine teaches the model this directive (`agent/prompt_builder.py`: *"You can send files
 * natively: write MEDIA:/absolute/path/to/file in your response"*), and every one of its own
 * surfaces intercepts it: the desktop renders an image inline and anything else as a card, and
 * the API server rewrites the tag into a base64 data URL before the reply leaves the process
 * (`gateway/platforms/api_server.py:_resolve_media_to_data_urls`). The runs surface this app
 * consumes does not — `run.completed.output` carries the assistant's text verbatim — so a
 * pantler operator was reading the raw directive and an absolute host path:
 *
 *     MEDIA:/home/you/projects/pantler/output/instagram/markets/pomona-saturdays.png
 *
 * That is a rendering of the implementation, not of the work, and it is the one thing the
 * reference clients do not make their user read. This module is the reading.
 *
 * Three rules, and they are the whole design:
 *
 *  - **Only the directive is recognised, never a path in a sentence.** A bare `/some/path.png`
 *    in prose stays words. `MEDIA:` is a deliberate, unambiguous act by the assistant; a path
 *    is a thing it happened to mention, and sniffing those is how a renderer turns prose into
 *    broken image icons (the file-preview design §4 D7, `links.ts`).
 *  - **A directive is a line of its own.** The engine's own regex allows a tag mid-sentence,
 *    but in practice the model writes them as their own lines and a directive inside a sentence
 *    is not something to guess at: a line is removed from the prose only when the whole line is
 *    the directive, so no sentence ever loses a word.
 *  - **Nothing here decides whether a file can be shown.** That answer is the server's
 *    (`/api/files/meta` → `render`/`inline`), and the component asks it. This module only says
 *    *which paths the turn asked for* and *what prose is left*.
 */

/** The file extension set the engine itself treats as a deliverable media path. */
const MEDIA_PATH = /^MEDIA:\s*(\S.*?)\s*$/

/**
 * The extensions the engine will deliver (`gateway/platforms/base.py:MEDIA_DELIVERY_EXTS`).
 *
 * Requiring one is not decoration, it is what makes a *streaming* reply safe. The answer arrives
 * a delta at a time, so a directive is briefly a half-written path — `MEDIA:/home/you/proj` —
 * and a rule that accepted any absolute path would render a card for that fragment, ask the
 * server about it, be refused, and redraw as the path grew. The engine's own regex has the same
 * requirement for the same reason; matching it means a directive becomes visible at the moment
 * it is complete and not one delta before.
 */
const MEDIA_EXTENSIONS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'svg',
  'mp4', 'mov', 'avi', 'mkv', 'webm', '3gp',
  'mp3', 'm2a', 'wav', 'ogg', 'opus', 'm4a', 'flac',
  'pdf', 'docx', 'doc', 'odt', 'rtf', 'txt', 'md', 'epub',
  'xlsx', 'xls', 'ods', 'csv', 'tsv', 'json', 'xml', 'yaml', 'yml',
  'kmz', 'kml', 'geojson', 'gpx',
  'pptx', 'ppt', 'odp', 'key',
  'zip', 'tar', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar', 'apk', 'ipa',
  'html', 'htm'
])

/**
 * One `MEDIA:` directive's path.
 *
 * The engine's own regex tolerates wrapping quotes, backticks and trailing sentence punctuation
 * (`gateway/platforms/base.py:MEDIA_TAG_CLEANUP_RE`), and a model that copies a path out of a
 * terminal result will often bring a quote or a full stop with it. Stripping those is not
 * leniency — it is the same normalisation the engine does before it looks for the file.
 */
export function mediaPath(line: string): string | undefined {
  const match = MEDIA_PATH.exec(line.trim())
  if (!match) return undefined

  let path = match[1].trim()
  // A wrapping quote or backtick, or trailing punctuation a sentence would end with.
  path = path.replace(/^[`"']+|[`"']+$/g, '').replace(/[.,;:]+$/, '').trim()
  if (!path) return undefined

  // Absolute only: the transcript carries no working directory (`SessionMessage` has no `cwd`),
  // so a relative path cannot be resolved honestly — it would be a request the server must
  // refuse, and offering it as a card would promise something that cannot open.
  if (!path.startsWith('/')) return undefined

  // A deliverable file type, which is also what keeps a half-streamed path from rendering
  // (`MEDIA_EXTENSIONS`).
  const extension = /\.([A-Za-z0-9]{1,8})$/.exec(path)
  if (!extension || !MEDIA_EXTENSIONS.has(extension[1].toLowerCase())) return undefined

  return path
}

/** The turn's prose, and the files its `MEDIA:` directives asked for, in the order written. */
export interface MediaSplit {
  /** The prose with every directive line removed. Never contains a `MEDIA:` line. */
  text: string
  /** Absolute paths, in the order the assistant wrote them, de-duplicated. */
  paths: string[]
}

/**
 * Split a reply into what it says and what it hands over.
 *
 * The directive lines are removed rather than left behind, because a path is not part of the
 * sentence that introduced it: `"Two cards are ready.\nMEDIA:/…/a.png"` is a sentence and an
 * attachment, and the sentence is what the operator reads.
 *
 * Blank lines left behind by a removed directive are collapsed, so a turn that was mostly
 * attachments does not render as a column of gaps. Interior paragraph breaks the assistant
 * actually wrote are kept — only a run of blank lines where a directive used to be is dropped.
 */
export function splitMedia(text: string): MediaSplit {
  const source = (text ?? '').replace(/\r\n?/g, '\n')
  if (!source.trim()) return { text: '', paths: [] }

  const paths: string[] = []
  const kept: string[] = []
  let removed = false

  for (const line of source.split('\n')) {
    const path = mediaPath(line)
    if (path === undefined) {
      kept.push(line)
      continue
    }
    removed = true
    if (!paths.includes(path)) paths.push(path)
  }

  if (!removed) return { text: source, paths: [] }

  // A removed line leaves the blank line that separated it from the prose. Collapse runs of
  // blanks to the single paragraph break the writer meant, and trim the ends.
  const collapsed: string[] = []
  for (const line of kept) {
    const blank = line.trim() === ''
    if (blank && collapsed.length > 0 && collapsed[collapsed.length - 1].trim() === '') continue
    collapsed.push(line)
  }

  return { text: collapsed.join('\n').trim(), paths }
}
