/**
 * What a tool call looks like on screen — the one place that decides.
 *
 * the front-end design §4 gives a tool card authority because for a *pack* tool the
 * result IS the record: the lines, prices and total the ledger resolved. That authority is
 * the point of the card and it stays.
 *
 * What does not belong on screen is the engine's plumbing. `web_search` answers with a JSON
 * envelope, `read_file` with a file, `terminal` with a shell transcript — none of it is a
 * record, all of it is the assistant working. Printing it put raw JSON in front of a
 * operator: a rendering of the implementation rather than of the work.
 *
 * So a tool call is one of four things, and only the first three are printed:
 *
 *   record    → the pack's deterministic output        → the structural card (§4)
 *   question  → the ledger refusing to guess           → the question card
 *   error     → a failure we cannot put into words     → the error card
 *   activity  → the assistant working                  → one quiet line, in words
 *
 * An activity line is spoken, never dumped. Its subject comes from the tool's own argument
 * preview — the engine sends the *primary argument* (`agent/display.py:build_tool_preview`),
 * a search query rather than JSON — and what sits behind the line is human-readable (which
 * pages were read), never the raw payload.
 *
 * The wording tracks the engine's own verb catalog (`locales/en.yaml` `display.verb.*`)
 * because the same conversation can be read in the engine's client, and two vocabularies for
 * one action is a bug. Where the engine's verb is a fragment ("Reading"), pantler's is a
 * whole phrase ("Reading a page").
 *
 * A known tool that fails is still an activity line: "Couldn't search the web" is the honest
 * sentence, and the tool's own message is one click away. A tool we cannot name keeps the
 * error card, because the only truthful thing left to show is what it said. And a command's
 * exact text is not hidden by this — the approval card (§4) still prints the payload when
 * the engine asks before running something.
 */

import { classifyToolResult, parseInvoiceDraft, MONEY_PACK } from '@shared/pack'
import type { ToolCall } from '../seam/reducer'
import { isLearningTool, learningMoment, type LearningMoment } from './learning'
import { parseCapture } from './capture'
import { CONNECT_TOOL, connectOffers } from './connect'
import { referencesInTool, type FileReference } from './files'
import { MAX_JSON_CHARS, effectiveStatus, embeddedJson, errorEnvelope } from './tool-result'

// Re-exported so the screens keep importing the vocabulary from the module that routes with it
// (`Activity.tsx`, `activity.test.ts`), while the reading of a result lives in one place.
export { MAX_JSON_CHARS, effectiveStatus, embeddedJson, errorEnvelope }

export type ToolPresentation = 'record' | 'question' | 'error' | 'activity' | 'learning' | 'connect'

/** The visual family — which icon a line wears, and where its detail comes from. */
export type ToolFamily = 'web' | 'file' | 'media' | 'code' | 'help' | 'memory' | 'schedule'

export interface Phrase {
  family: ToolFamily
  /** Present continuous: what is happening now. */
  doing: string
  /** Past: what happened. */
  done: string
  /** What did not happen, when the tool failed. */
  failed: string
  /**
   * Whether the call's own subject reads naturally inline. Only the search-style tools,
   * which is the engine's own split (`_TOOL_VERBS_FOR_CONNECTOR` in `agent/display.py`):
   * "Searching the web for 'organic insecticides'". A path or a command is not a sentence.
   */
  subject?: 'for'
}

/**
 * The engine tools an operator's install actually has, named from `baseline/farm-toolsets.json`
 * rather than guessed. A pack tool is deliberately absent: it is classified from its result,
 * so the shell never has to know a market's tool names (the design notes §8).
 */
const BY_TOOL: Readonly<Record<string, Phrase>> = {
  web_search: {
    family: 'web',
    doing: 'Searching the web',
    done: 'Searched the web',
    failed: 'Couldn’t search the web',
    subject: 'for'
  },
  web_extract: {
    family: 'web',
    doing: 'Reading a page',
    done: 'Read a page',
    failed: 'Couldn’t read that page'
  },
  browser_navigate: {
    family: 'web',
    doing: 'Opening a page',
    done: 'Opened a page',
    failed: 'Couldn’t open that page'
  },

  search_files: {
    family: 'file',
    doing: 'Searching your files',
    done: 'Searched your files',
    failed: 'Couldn’t search your files',
    subject: 'for'
  },
  read_file: {
    family: 'file',
    doing: 'Reading a file',
    done: 'Read a file',
    failed: 'Couldn’t read that file'
  },
  write_file: {
    family: 'file',
    doing: 'Writing a file',
    done: 'Wrote a file',
    failed: 'Couldn’t write that file'
  },
  patch: {
    family: 'file',
    doing: 'Updating a file',
    done: 'Updated a file',
    failed: 'Couldn’t update that file'
  },

  vision_analyze: {
    family: 'media',
    doing: 'Looking at the image',
    done: 'Looked at the image',
    failed: 'Couldn’t look at that image'
  },
  image_generate: {
    family: 'media',
    doing: 'Making an image',
    done: 'Made an image',
    failed: 'Couldn’t make that image'
  },

  terminal: {
    family: 'code',
    doing: 'Running a command',
    done: 'Ran a command',
    failed: 'Couldn’t run that command'
  },
  process_manage: {
    family: 'code',
    doing: 'Checking what’s running',
    done: 'Checked what’s running',
    failed: 'Couldn’t check what’s running'
  },
  execute_code: {
    family: 'code',
    doing: 'Working something out',
    done: 'Worked something out',
    failed: 'Couldn’t work that out'
  },

  skill_view: {
    family: 'help',
    doing: 'Checking how to do this',
    done: 'Checked how to do this',
    failed: 'Couldn’t check how to do this'
  },
  skills_list: {
    family: 'help',
    doing: 'Checking what it can do',
    done: 'Checked what it can do',
    failed: 'Couldn’t check what it can do'
  },
  skill_manage: {
    family: 'help',
    doing: 'Updating what it knows',
    done: 'Updated what it knows',
    failed: 'Couldn’t update what it knows'
  },
  todo_list: {
    family: 'help',
    doing: 'Making a plan',
    done: 'Made a plan',
    failed: 'Couldn’t make a plan'
  },
  delegate_task: {
    family: 'help',
    doing: 'Asking for a hand',
    done: 'Asked for a hand',
    failed: 'Couldn’t get a hand with that'
  },

  memory: {
    family: 'memory',
    doing: 'Checking what it remembers',
    done: 'Checked what it remembers',
    failed: 'Couldn’t check what it remembers'
  },
  session_search: {
    family: 'memory',
    doing: 'Looking back through your history',
    done: 'Looked back through your history',
    failed: 'Couldn’t look back through your history'
  },
  manage_connections: {
    family: 'memory',
    doing: 'Checking your connections',
    done: 'Checked your connections',
    failed: 'Couldn’t check your connections'
  },

  cronjob_manage: {
    family: 'schedule',
    doing: 'Checking your schedule',
    done: 'Checked your schedule',
    failed: 'Couldn’t check your schedule'
  }
}

/** Families with too many tools to name one at a time. */
const BY_PREFIX: ReadonlyArray<{ prefix: string; phrase: Phrase }> = [
  {
    prefix: 'browser_',
    phrase: {
      family: 'web',
      doing: 'Using the browser',
      done: 'Used the browser',
      failed: 'Couldn’t use the browser'
    }
  },
  {
    prefix: 'mcp__',
    phrase: {
      family: 'help',
      doing: 'Using a connected tool',
      done: 'Used a connected tool',
      failed: 'Couldn’t use that connected tool'
    }
  }
]

/** A tool we cannot name is still work; it just gets the plainest true sentence. */
const GENERIC: Phrase = {
  family: 'help',
  doing: 'Working on it',
  done: 'Worked on it',
  failed: 'Couldn’t finish that'
}

/** The named phrase for a tool, or `undefined` when we cannot name it. */
export function phraseFor(tool: string): Phrase | undefined {
  const name = tool.trim().toLowerCase()
  return BY_TOOL[name] ?? BY_PREFIX.find(entry => name.startsWith(entry.prefix))?.phrase
}

/** Whether the shell can say what this tool is doing, rather than only what it returned. */
export function isNamedTool(tool: string): boolean {
  return phraseFor(tool) !== undefined
}

export function familyOf(tool: string): ToolFamily {
  return (phraseFor(tool) ?? GENERIC).family
}

/**
 * Which of the five things this call is.
 *
 * The learning tools come first, and they are the one place this module looks at a tool's
 * *name* rather than its result: `memory` and `skill_manage` are writes to what the assistant
 * knows about the business, and they are the only two calls in a turn that are about the
 * assistant rather than about the operator's work (`learning.ts`). They get their own card even
 * when they fail, because "it did not manage to write that down" is exactly as worth seeing.
 *
 * The named-tool test comes next and is deliberately narrow: when we know the tool is
 * plumbing, its failure is still plumbing, and the line says so in words. Everything else —
 * a pack tool, an MCP tool we have never seen — is read from its *result*, which is the only
 * domain-neutral signal the shell has.
 */
export function presentationOf(call: ToolCall): ToolPresentation {
  if (isLearningTool(call.tool)) return 'learning'

  // A connection offer is a card, and it comes before the named-tool test: this tool has a phrase
  // ("Checking your connections") because a *status* answer is the assistant working, but an answer
  // carrying a link is an action for the operator — and a link inside a folded activity line is a
  // login that does not happen. `connect.ts` refuses any address that is not http(s), so a hostile
  // result cannot reach a button through here.
  if (call.tool === CONNECT_TOOL && connectOffers(call.result).length > 0) return 'connect'

  // A capture is the operator's raw words, kept before a typed record exists. It gets a card
  // because the id and the words are the point; the generic activity line would hide both.
  if (call.tool === 'capture_save' && parseCapture(call.result)) return 'record'

  if (isNamedTool(call.tool)) return 'activity'

  if (effectiveStatus(call) === 'error') return 'error'

  const kind = classifyToolResult(call.result, MONEY_PACK)
  if (kind === 'question') return 'question'
  if (kind === 'error') return 'error'
  if (kind === 'ok' && parseInvoiceDraft(call.result) !== null) return 'record'

  // Unrecognised output is not a record and not a failure: it is the assistant working.
  // Printing it verbatim is what this module exists to stop.
  return 'activity'
}

// ------------------------------------------------------------------- the sentence

const MAX_SUBJECT = 70

/**
 * The tool's own argument preview, made safe to print.
 *
 * It arrives one-lined and secret-redacted already (`build_tool_preview` runs
 * `redact_tool_args_for_display` first). What it is not is a sentence: it can be long, it can
 * be quoted, and for a tool whose arguments are a structured object it can be JSON — which
 * would put the code straight back on screen. Anything that looks like a payload is dropped
 * rather than shown.
 */
export function subjectOf(preview: string | undefined): string | undefined {
  const text = (preview ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return undefined
  if (text.startsWith('{') || text.startsWith('[')) return undefined

  const unquoted = text.replace(/^["'“‘]|["'”’]$/g, '').trim()
  if (!unquoted) return undefined
  if (unquoted.length > MAX_SUBJECT) return `${unquoted.slice(0, MAX_SUBJECT - 1).trimEnd()}…`
  return unquoted
}

/**
 * The line itself: what is happening, in the operator's words, at the tense the call is in.
 */
export function activityLine(
  call: Pick<ToolCall, 'tool' | 'status' | 'result' | 'argsPreview'>
): string {
  const phrase = phraseFor(call.tool) ?? GENERIC
  const status = effectiveStatus(call)
  const running = status === 'running'

  if (status === 'error') return phrase.failed

  const base = running ? phrase.doing : phrase.done
  const subject = phrase.subject ? subjectOf(call.argsPreview) : undefined
  const line = subject ? `${base} ${phrase.subject} “${subject}”` : base
  return running ? `${line}…` : line
}

// --------------------------------------------------------------------- the detail

export interface ActivityItem {
  label: string
  url?: string
  /**
   * A file the call named, when it named one that can be resolved.
   *
   * Only an absolute path reaches here (`files.ts` explains why), and the row renders as a card
   * that opens the preview sheet rather than as text. The list itself stays `{label, url?}`-shaped
   * because a source is a link and a file is not.
   */
  path?: string
}

export interface ActivityDetail {
  /** What was looked at, in words. Never the raw payload. */
  items: ActivityItem[]
  /** The tool's own message when it failed — plain text, clipped. */
  message?: string
  /** The engine's timing, shown only once the line is opened. */
  duration?: number
}

/**
 * Tools whose file is worth a card behind the line.
 *
 * `files.ts` owns which tools count and where in the envelope the path is read from; this is only
 * the list the activity line consults, so a tool that names a file and is not here shows its path
 * as plain text — which is the safe way to be wrong.
 */
const PATH_TOOLS = new Set(['read_file', 'write_file', 'patch', 'vision_analyze', 'image_generate'])

const MAX_SOURCES = 5
const MAX_MESSAGE = 400
const MAX_NODES = 200

/**
 * What sits behind an activity line.
 *
 * Deliberately thin. The only structured reading is the web family's result, because
 * "which pages did it read" is the one question an operator actually asks about a search — and
 * even then the answer is titles and links, not the envelope they arrived in. Everything
 * unrecognised yields nothing, and the line stands on its own.
 */
export function activityDetail(call: ToolCall): ActivityDetail {
  const detail: ActivityDetail = { items: [] }
  const failed = effectiveStatus(call) === 'error'

  if (failed) {
    // The envelope's own message when there is one — "Refusing to overwrite …" reads; the
    // JSON it arrived in does not.
    const message = (errorEnvelope(call.result) ?? call.result ?? '').trim()
    if (message) detail.message = clip(message, MAX_MESSAGE)
  }
  if (typeof call.duration === 'number') detail.duration = call.duration

  const family = familyOf(call.tool)
  const tool = call.tool.trim().toLowerCase()
  if (family === 'web') {
    detail.items = sourcesFrom(call.result)
  } else if (PATH_TOOLS.has(tool)) {
    // The path from the arguments *and* the one from the result: `write_file` answers with the
    // absolute path it actually wrote (`resolved_path`), which can differ from the one it was
    // asked for, and the result is the source of truth for what happened.
    const references = referencesInTool(call.tool, {
      argsPreview: call.argsPreview,
      args: call.args,
      result: call.result
    })
    // `read` only. A file the turn *produced* is not context to dig for — it is the turn's
    // output, and `producedFiles` puts it on screen where the answer is, untouched by the folding
    // that a run of activity lines goes through.
    const context = references.filter(reference => reference.role === 'read')
    if (context.length > 0) {
      detail.items = context.map(reference => ({
        label: reference.path,
        path: reference.path
      }))
    } else {
      // Nothing resolvable: the preview of the argument is still worth naming, as text.
      const path = subjectOf(call.argsPreview)
      if (path) detail.items = [{ label: path }]
    }
  }

  return detail
}

/**
 * The files a turn made, in the order it made them.
 *
 * A deliverable is not context, and it must not be lost to a fold: `segmentTools` collapses a run
 * of activity lines into one summary past three steps, which is right for "Ran a command ×6" and
 * wrong for the invoice PDF the operator asked for. So a produced file is collected here and
 * rendered beside the answer, where an output belongs — and it is still a card, not a document:
 * looking at it is a click (the file-preview design §4 D3).
 */
export function producedFiles(calls: readonly ToolCall[]): FileReference[] {
  const seen = new Set<string>()
  const files: FileReference[] = []
  for (const call of calls) {
    for (const reference of referencesInTool(call.tool, {
      argsPreview: call.argsPreview,
      args: call.args,
      result: call.result
    })) {
      if (reference.role !== 'produced' || seen.has(reference.path)) continue
      seen.add(reference.path)
      files.push(reference)
    }
  }
  return files
}

/** The label on the disclosure — the one thing worth promising before it opens. */
export function detailLabel(detail: ActivityDetail, family: ToolFamily): string | undefined {
  if (detail.message) return 'what happened'
  if (detail.items.length > 0) {
    if (family === 'web') {
      return detail.items.length === 1 ? '1 source' : `${detail.items.length} sources`
    }
    return 'which one'
  }
  if (detail.duration !== undefined) return 'details'
  return undefined
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return url
  }
}

/**
 * Pull page titles and links out of a web tool's result.
 *
 * The shape is the engine's, not ours — the screenshot that started this was
 * `{"success": true, "data": {"web": [{"url": …, "title": …}]}}` — so rather than pin a
 * shape that can move, this walks the parsed value for any `{url, title}` pair. It is
 * bounded, it only ever runs for the web family, and it yields nothing rather than guessing.
 */
function sourcesFrom(result: string | undefined): ActivityItem[] {
  const parsed = embeddedJson(result)
  if (parsed === undefined) return looseSources(result)

  const found: ActivityItem[] = []
  collectSources(parsed, found, { nodes: MAX_NODES })
  return found
}

/** `"url": "…"` … `"title": "…"`, the shape of one result inside the envelope. */
const SOURCE_PAIR =
  /"url"\s*:\s*"(https?:\/\/[^"\\]*)"[\s\S]{0,400}?"title"\s*:\s*"((?:[^"\\]|\\.)*)"/g

/**
 * A last resort for a LIVE result, which the engine caps at 500 characters
 * (`_tool_completed_preview`, `api_server_runs.py:101`) and so cuts mid-object — the
 * screenshot that started this ends at `"position…`. The first result's url and title sit
 * well inside that cap, so they are read as text rather than thrown away.
 *
 * Reached only when the JSON did not parse, so it can never shadow a real answer, and it
 * accepts only http(s) urls — a title without a link is not a source.
 */
function looseSources(result: string | undefined): ActivityItem[] {
  const text = (result ?? '').trim()
  if (!text || text.length > MAX_JSON_CHARS || !text.includes('"url"')) return []

  const found: ActivityItem[] = []
  for (const match of text.matchAll(SOURCE_PAIR)) {
    const url = match[1]
    if (found.some(item => item.url === url)) continue
    const title = unescapeJson(match[2]).trim()
    found.push({ label: title || hostOf(url), url })
    if (found.length >= MAX_SOURCES) break
  }
  return found
}

/** The escapes a JSON string can hold that matter in a page title. */
function unescapeJson(value: string): string {
  return value.replace(/\\"/g, '"').replace(/\\u([0-9a-f]{4})/gi, (_, code: string) =>
    String.fromCharCode(parseInt(code, 16))
  )
}

function collectSources(node: unknown, out: ActivityItem[], budget: { nodes: number }): void {
  if (budget.nodes <= 0 || out.length >= MAX_SOURCES) return

  if (Array.isArray(node)) {
    for (const item of node) collectSources(item, out, budget)
    return
  }
  if (!node || typeof node !== 'object') return

  budget.nodes -= 1
  const record = node as Record<string, unknown>
  const url = typeof record.url === 'string' ? record.url : undefined

  if (url && /^https?:\/\//i.test(url) && !out.some(item => item.url === url)) {
    const title = typeof record.title === 'string' ? record.title.trim() : ''
    out.push({ label: title || hostOf(url), url })
    if (out.length >= MAX_SOURCES) return
  }

  for (const value of Object.values(record)) collectSources(value, out, budget)
}

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`
}

// -------------------------------------------------------------------- the grouping

export type TurnSegment =
  | { kind: 'card'; key: string; seq: number; call: ToolCall }
  | { kind: 'learning'; key: string; seq: number; moment: LearningMoment }
  | { kind: 'activity'; key: string; seq: number; calls: ToolCall[] }

/**
 * Split a turn's tool calls into what is printed and what is spoken.
 *
 * Consecutive activity calls become ONE segment, because a run of five plumbing calls is one
 * piece of work and five separate rows is the noise this removes. A card ends the run: a
 * record, a question or an error is a thing the operator is meant to look at, and burying it
 * inside a list of errands would be the opposite of §4's authority. A learning moment ends it
 * for the same reason and one more: it is the only thing in the turn that is about the
 * assistant rather than about the work, and it must not scroll past inside a list of errands.
 *
 * Each segment carries the `seq` of the call it opens on, which is how a thought is placed
 * beside the work it belongs to without this module having to know that thinking exists
 * (`thought.ts`).
 */
export function segmentTools(tools: readonly ToolCall[]): TurnSegment[] {
  const segments: TurnSegment[] = []

  for (const call of tools) {
    const moment = learningMoment(call)
    if (moment) {
      segments.push({ kind: 'learning', key: call.key, seq: call.seq, moment })
      continue
    }
    if (presentationOf(call) !== 'activity') {
      segments.push({ kind: 'card', key: call.key, seq: call.seq, call })
      continue
    }
    const last = segments[segments.length - 1]
    if (last?.kind === 'activity') last.calls.push(call)
    else segments.push({ kind: 'activity', key: call.key, seq: call.seq, calls: [call] })
  }

  return segments
}

/**
 * Past this many steps, a run is summarised rather than listed.
 *
 * A research turn makes thirty-odd calls. Thirty rows of prose is better than thirty JSON
 * blobs and still not an answer to "what did it do?" — so the shape of the work is said in
 * one line and the steps are one click away.
 */
export const COLLAPSE_AT = 3

/** The most steps worth naming before the line stops being a summary. */
const MAX_KINDS = 3

/**
 * One line for a long run: how much of it there was, and what it mostly was.
 *
 * Counts rather than a list, because "Searched the web ×12" is what an operator wants to know
 * and twelve identical rows is not.
 */
export function summarise(calls: readonly ToolCall[]): string {
  const counts = new Map<string, number>()

  for (const call of calls) {
    const phrase = phraseFor(call.tool) ?? GENERIC
    const label = effectiveStatus(call) === 'error' ? phrase.failed : phrase.done
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, MAX_KINDS)
    .map(([label, count]) => (count === 1 ? label : `${label} ×${count}`))
    .join(' · ')
}

/**
 * The steps a folded run still shows: the ones that did not happen.
 *
 * Deliberately failures only, and the running call is deliberately not one of them. It used to
 * include whatever was not finished, on the argument that the step in flight must never be
 * hidden — and that was right about a *live* run, which is never folded (it ticks, and the call
 * in flight is the line the ticker shows). It was wrong about a settled one. Calls run in
 * parallel, so a run that a card has just ended can still hold three or four calls that have not
 * answered yet; each was printed as a row, and every one of them vanished the moment its call
 * completed. Measured on a live turn: 104 pixels of rows gone in a single frame, mid-turn — the
 * contraction this fix is about. A settled run says what it did in one line and admits what
 * failed; a call that is still running is the summary's business, not a row's (`liveSummary`).
 */
export function failures(calls: readonly ToolCall[]): ToolCall[] {
  return calls.filter(call => effectiveStatus(call) === 'error')
}

// ------------------------------------------------------------- the live run

/**
 * The one line that stands in for a run while it is still going.
 *
 * The call still in flight is the ticker's job, not this line's, so it is left out: counting it
 * with the finished ones would say "Read a page" about a page that is still being read. Failures
 * stay in, because "Couldn't read that page" is as much a part of the shape of the run as a
 * success — and they are also printed as rows of their own (`failures`).
 */
export function liveSummary(calls: readonly ToolCall[]): string {
  return summarise(calls.filter(call => effectiveStatus(call) !== 'running'))
}

/** Whether any call in a run has not answered yet. */
export function anyRunning(calls: readonly ToolCall[]): boolean {
  return calls.some(call => effectiveStatus(call) === 'running')
}

/** How a run of activity prints. */
export type ActivityMode =
  /** Every call has its own row. */
  | 'rows'
  /** One summary line plus a one-line reel that ticks over in place (a live run). */
  | 'ticker'
  /** One summary line, with the failures behind it and the rest a click away. */
  | 'folded'

export interface ActivityLayout {
  mode: ActivityMode
  /** Whether the summary line — and with it the disclosure — is shown above the rows. */
  header: boolean
}

/**
 * Which of the three shapes a run takes, given whether the turn is still working on it.
 *
 * **A live run ticks instead of growing.** Past one call, the run is a summary line and a
 * one-line reel showing the call in flight; each new call slides the previous one up and out.
 * Thirty errands then read as one line changing in place rather than a list growing down the
 * page — and, more importantly, the run never folds underneath the operator mid-turn. The old
 * rule folded at the fourth call, so the three rows that had just been read were replaced by a
 * summary line in one frame: that is the contraction this replaces, exactly as Hermes' tool run
 * does it.
 *
 * **A settled run folds once.** Past `COLLAPSE_AT` calls the summary is the whole of it until
 * the operator opens it — the shape of the work, not the list. Below that, the rows are short
 * enough to be the whole of it.
 *
 * `expanded` is the operator's click and outranks the live reel: they asked for the steps, so
 * they get the steps. The header stays either way, so there is always a way back.
 */
export function activityLayout({
  count,
  live,
  expanded
}: {
  count: number
  /** The turn is still working, and this is the newest run in it. */
  live: boolean
  /** The operator has asked for every step. */
  expanded: boolean
}): ActivityLayout {
  const header = count > 1 && (live || count > COLLAPSE_AT)
  if (expanded) return { mode: 'rows', header }
  if (live && count > 1) return { mode: 'ticker', header }
  if (count > COLLAPSE_AT) return { mode: 'folded', header }
  return { mode: 'rows', header: false }
}
