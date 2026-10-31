/**
 * The pack — the domain layer's vocabulary (the design notes §8).
 *
 * The front end is domain-neutral: the shell supplies the screens, the pack supplies the words.
 * pantler serves regenerative and conscious businesses as a whole — small and medium-scale
 * farming, health food, food producers, not-for-profits — and every market arrives as a pack.
 *
 * This file is where that *should* land. What it holds today is narrower: `MONEY_PACK` is the
 * money plugin's vocabulary, and the shell imports it by name (`cards.tsx`, `activity.ts`), so a
 * second market would touch the shell. Threading the vocabulary through from `/api/packs` is the
 * change that makes the claim below true; until then it is a direction, not a description
 * (the internal audit CON-4).
 *
 * Phase 0 carries exactly one interpretation rule, and it is a heuristic worth naming:
 * a tool returns a **string**, and we tell a refusal-to-guess from a failure by reading
 * it. That is brittle. The durable fix is structured tool results; until then the
 * prefixes are declared here, in one place, instead of being smeared across components.
 */

export interface PackVocabulary {
  id: string
  /** Human-facing words the UI uses for this market. */
  words: {
    customer: string
    customers: string
    item: string
    items: string
    record: string
    records: string
    priceBook: string
  }
  /**
   * A tool result starting with one of these is the ledger refusing to guess — the
   * model must ask, never pick. Rendered as a question, never as an error.
   */
  questionPrefixes: readonly string[]
  /** A tool result starting with one of these is a genuine failure. */
  errorPrefixes: readonly string[]
}

/**
 * The money vocabulary — **not** the farm pack's.
 *
 * `packs/farm/pack.toml` declares `block`, `input`, `application`, `harvest` and `certificate`:
 * no invoice, no customer, no item. This constant describes the *money* plugin
 * (`plugins/pantler/tools.py`), which is where its words and its refusal prefixes come from, and
 * it used to be called `FARM_PACK` — a name that sent a reader to the wrong file and implied the
 * pack's vocabulary was threaded through here (the internal audit CON-4).
 *
 * Phase 0 has this one hardcoded vocabulary. Threading a real pack through from `/api/packs` is
 * the change that makes "adding a market is adding a pack and not touching the shell" true; until
 * then the shell imports this constant by name, and a second market *would* touch it.
 */
export const MONEY_PACK: PackVocabulary = Object.freeze({
  id: 'farm',
  words: {
    customer: 'customer',
    customers: 'customers',
    item: 'item',
    items: 'items',
    record: 'invoice',
    records: 'invoices',
    priceBook: 'price book'
  },
  // plugins/pantler/tools.py:_question — "I need to check one thing before I bill this. …"
  questionPrefixes: ['I need to check one thing before I bill this.'],
  // plugins/pantler/tools.py error paths.
  errorPrefixes: ["I couldn't build that invoice:", "I can't reach the price book:"]
})

export type ToolResultKind = 'question' | 'error' | 'ok' | 'empty'

/**
 * Classify a tool result for rendering. Pure, and deliberately conservative: anything
 * unrecognised is `ok`, so an unknown shape is shown verbatim rather than mislabelled.
 */
export function classifyToolResult(
  result: string | undefined | null,
  pack: PackVocabulary = MONEY_PACK
): ToolResultKind {
  const text = (result ?? '').trim()
  if (!text) return 'empty'

  // Six of the seven tools answer `{success, message, …}` and the two invoice tools used to
  // answer prose; they answer the same shape now, and this reads it first
  // (the internal audit PLUG-15). `success: false` carries the sentence to say, so the
  // only judgement left is whether that sentence is a question or a failure.
  const envelope = parseEnvelope(text)
  if (envelope) {
    if (envelope.success === false) {
      return envelope.question || envelope.refusal ? 'question' : 'error'
    }
    return 'ok'
  }

  // A result recorded before the tools answered JSON, still in the transcript.
  if (pack.questionPrefixes.some(prefix => text.startsWith(prefix))) return 'question'
  if (pack.errorPrefixes.some(prefix => text.startsWith(prefix))) return 'error'
  // A bare question is still a question: "Which invoice number should I show?"
  if (text.endsWith('?')) return 'question'
  return 'ok'
}

interface ToolEnvelope {
  success?: boolean
  message?: string
  question?: string
  refusal?: string
  note?: string
  invoice?: {
    number?: string
    customer?: string
    currency?: string
    status?: string
    tax_excluded?: boolean
    tax_label?: string
    /** Rendered by the kernel's one money formatter; the shell never formats cents. */
    subtotal?: string
    tax?: string | null
    total?: string
    lines?: Array<{
      quantity?: string
      unit?: string
      description?: string
      unit_price?: string
      amount?: string
    }>
  }
}

/** A tool result as the JSON envelope the tools answer with, or null when it is not one. */
function parseEnvelope(text: string): ToolEnvelope | null {
  if (!text.startsWith('{')) return null
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as ToolEnvelope
    }
  } catch {
    // Not JSON: an older result, a truncated preview, or prose that happens to start with `{`.
  }
  return null
}

// ------------------------------------------------------------- invoice drafts

export interface InvoiceLine {
  quantity: string
  unit: string
  description: string
  unitPrice: string
  amount: string
}

export interface InvoiceDraft {
  number: string
  customer: string
  lines: InvoiceLine[]
  subtotal?: string
  taxLabel?: string
  tax?: string
  /** Set when the operator has configured no tax rate. */
  taxExcluded: boolean
  total?: string
  /** The draft's own closing sentence said it has not been sent. */
  isDraft: boolean
}

const DRAFT_HEADER = /^Draft\s+(\S+)\s+for\s+(.+?):\s*$/
const LINE = /^•\s*(\S+)\s+(\S+)\s+(.+?)\s+@\s+(\S+)\s+=\s+(\S+)\s*$/
const SUBTOTAL = /^Subtotal:\s*(.+?)\s*$/
const TAX = /^(.+?):\s*(.+?)\s*$/
const TOTAL = /^Total:\s*(.+?)\s*$/

/**
 * Read the invoice draft out of a tool result.
 *
 * The seam hands us the tool's result as TEXT (capped at 500 chars), so rendering a
 * structured card means reading the pack's own format. That is a real limitation, and it
 * is contained here on purpose: when it cannot parse, it returns `null` and the caller
 * shows the text verbatim. It must never guess — a half-parsed invoice is worse than an
 * unparsed one, because the operator would trust it.
 */
export function parseInvoiceDraft(result: string | undefined | null): InvoiceDraft | null {
  const text = (result ?? '').trim()
  if (!text) return null

  // The structured answer, when there is one: the tool already computed every figure, and a
  // card that re-read them out of prose was doing the arithmetic's reading twice.
  const envelope = parseEnvelope(text)
  if (envelope?.invoice) {
    const invoice = envelope.invoice
    const lines = (invoice.lines ?? [])
      .filter(line => line && line.description)
      .map(line => ({
        quantity: String(line.quantity ?? ''),
        unit: String(line.unit ?? ''),
        description: String(line.description ?? ''),
        unitPrice: String(line.unit_price ?? ''),
        amount: String(line.amount ?? '')
      }))
    if (lines.length === 0) return null
    return {
      number: String(invoice.number ?? ''),
      customer: String(invoice.customer ?? ''),
      lines,
      subtotal: invoice.subtotal,
      taxLabel: invoice.tax_label,
      tax: invoice.tax_excluded ? undefined : (invoice.tax ?? undefined),
      taxExcluded: Boolean(invoice.tax_excluded),
      total: invoice.total,
      isDraft: invoice.status === 'draft' || /has not been sent/i.test(envelope.message ?? '')
    }
  }

  const lines = text.split('\n').map(l => l.replace(/\s+$/, ''))
  const header = lines[0]?.match(DRAFT_HEADER)
  if (!header) return null

  const draft: InvoiceDraft = {
    number: header[1],
    customer: header[2],
    lines: [],
    taxExcluded: false,
    isDraft: /has not been sent/i.test(text)
  }

  for (const raw of lines.slice(1)) {
    const line = raw.trim()
    if (!line) continue

    const item = line.match(LINE)
    if (item) {
      draft.lines.push({
        quantity: item[1],
        unit: item[2],
        description: item[3],
        unitPrice: item[4],
        amount: item[5]
      })
      continue
    }

    const subtotal = line.match(SUBTOTAL)
    if (subtotal) {
      draft.subtotal = subtotal[1]
      continue
    }

    const total = line.match(TOTAL)
    if (total) {
      draft.total = total[1]
      continue
    }

    const tax = line.match(TAX)
    if (tax && !/^Draft\b/.test(line)) {
      draft.taxLabel = tax[1]
      if (/not applied/i.test(tax[2])) {
        draft.taxExcluded = true
      } else {
        draft.tax = tax[2]
      }
      continue
    }
  }

  // A draft with no lines parsed is not a draft we understand; show the raw text instead.
  if (draft.lines.length === 0) return null
  return draft
}
