/**
 * Reading a tool's result — the small, shared vocabulary two modules need.
 *
 * `activity.ts` decides what a call looks like on screen and `learning.ts` reads what it did to
 * the assistant's own memory. Both have to answer the same two questions about a result string:
 * *is there a JSON envelope in here?* and *does it say the call failed?* — and answering them
 * twice is how two screens end up disagreeing about whether an action happened.
 *
 * The engine's envelope is not always bare. A **live** preview is the JSON; a **resumed**
 * transcript wraps the same JSON in the engine's `<untrusted_tool_result>` preamble and appends
 * the closing tag after it — verified against a real session, where parsing to the end of the
 * string fails with "Extra data" on every single result. So the value is taken as a *span*:
 * braces are matched from the first one, respecting string literals, and only that slice is
 * parsed. Nothing is inferred from trailing text, and a half-read object is never returned.
 */

/** A bound against pathological input, not a functional limit: real results reach 55k. */
export const MAX_JSON_CHARS = 200_000

/** How far in a leading `{` or `[` is looked for before giving up on the result being JSON. */
const JSON_WINDOW = 600

export function embeddedJson(result: string | undefined): unknown | undefined {
  const text = (result ?? '').trim()
  if (!text || text.length > MAX_JSON_CHARS) return undefined

  const start = jsonStart(text)
  if (start === -1) return undefined

  const span = jsonSpan(text, start)
  if (span === undefined) return undefined

  try {
    return JSON.parse(span)
  } catch {
    return undefined
  }
}

function jsonStart(text: string): number {
  if (text.startsWith('{') || text.startsWith('[')) return 0
  const window = text.slice(0, JSON_WINDOW)
  const braces = [window.indexOf('{'), window.indexOf('[')].filter(index => index !== -1)
  return braces.length > 0 ? Math.min(...braces) : -1
}

/** The balanced `{…}` or `[…]` that starts at `start`, strings and escapes respected. */
function jsonSpan(text: string, start: number): string | undefined {
  const open = text[start]
  const close = open === '{' ? '}' : ']'
  let depth = 0
  let inString = false
  let escaped = false

  for (let i = start; i < text.length; i++) {
    const character = text[i]

    if (inString) {
      if (escaped) escaped = false
      else if (character === '\\') escaped = true
      else if (character === '"') inString = false
      continue
    }

    if (character === '"') inString = true
    else if (character === open) depth += 1
    else if (character === close) {
      depth -= 1
      if (depth === 0) return text.slice(start, i + 1)
    }
  }

  return undefined
}

/** The tool's own failure sentence, when its result is an envelope carrying one. */
export function errorEnvelope(result: string | undefined): string | undefined {
  const parsed = embeddedJson(result)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return undefined
  const value = (parsed as Record<string, unknown>).error
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

/**
 * The status to render, which is not always the status we were given.
 *
 * A live `tool.completed` carries a real `error` boolean, but a *resumed* transcript does
 * not: `GET /api/sessions/{id}/messages` hands back the tool's result text and nothing else,
 * so a refusal reads as a success. The engine's tools say so themselves — a refused
 * `write_file` answers `{"error": "Refusing to overwrite …"}` — so a JSON envelope carrying a
 * non-empty `error` string is read as a failure.
 *
 * This exists because of invariant 3: an action that did not happen must never be shown as
 * having happened. Before this, the raw payload was on screen and the reader could see the
 * refusal; a line of prose that says "Wrote a file" would be a lie.
 */
export function effectiveStatus(
  call: { status: 'running' | 'ok' | 'error'; result?: string }
): 'running' | 'ok' | 'error' {
  if (call.status !== 'ok') return call.status
  return errorEnvelope(call.result) ? 'error' : 'ok'
}
