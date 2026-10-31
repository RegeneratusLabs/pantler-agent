/**
 * The invoice parser reads the pack's own tool-result format. It is the one place the
 * front end interprets text rather than displaying it, so its failure mode is the thing
 * worth testing: when it cannot parse, it must return null and let the caller show the
 * text verbatim. A half-parsed invoice would be trusted and wrong.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { classifyToolResult, MONEY_PACK, parseInvoiceDraft } from '@shared/pack'

const GOLDEN_DRAFT = [
  'Draft INV-0001 for Bellview CSA:',
  '  • 12 kg Green Beans @ $12.00 = $144.00',
  '  • 4 dozen Eggs @ $9.00 = $36.00',
  '  Subtotal: $180.00',
  '  GST: $18.00',
  '  Total: $198.00',
  "It is a draft and has not been sent. Say the word and I'll send it."
].join('\n')

describe('parseInvoiceDraft', () => {
  it('parses the golden draft exactly', () => {
    const draft = parseInvoiceDraft(GOLDEN_DRAFT)
    expect(draft).not.toBeNull()
    expect(draft!.number).toBe('INV-0001')
    expect(draft!.customer).toBe('Bellview CSA')
    expect(draft!.lines).toEqual([
      { quantity: '12', unit: 'kg', description: 'Green Beans', unitPrice: '$12.00', amount: '$144.00' },
      { quantity: '4', unit: 'dozen', description: 'Eggs', unitPrice: '$9.00', amount: '$36.00' }
    ])
    expect(draft!.subtotal).toBe('$180.00')
    expect(draft!.taxLabel).toBe('GST')
    expect(draft!.tax).toBe('$18.00')
    expect(draft!.total).toBe('$198.00')
    expect(draft!.isDraft).toBe(true)
    expect(draft!.taxExcluded).toBe(false)
  })

  it('records a total that excludes tax rather than inventing a rate', () => {
    const draft = parseInvoiceDraft(
      [
        'Draft INV-0002 for Marong Road Cafe:',
        '  • 2 kg Green Beans @ $12.00 = $24.00',
        '  Subtotal: $24.00',
        '  GST: not applied — no rate configured, so this total excludes it.',
        '  Total: $24.00',
        "It is a draft and has not been sent. Say the word and I'll send it."
      ].join('\n')
    )

    expect(draft!.taxExcluded).toBe(true)
    expect(draft!.tax).toBeUndefined()
    expect(draft!.taxLabel).toBe('GST')
  })

  it('handles a customer name containing spaces', () => {
    const draft = parseInvoiceDraft(
      ['Draft INV-0003 for Bellview Farm Shop:', '  • 1 kg Green Beans @ $12.00 = $12.00'].join('\n')
    )
    expect(draft!.customer).toBe('Bellview Farm Shop')
  })

  it('returns null for a question instead of guessing', () => {
    expect(
      parseInvoiceDraft(
        'I need to check one thing before I bill this. Which customer did you mean: Bellview CSA, or Bellview Farm Shop?'
      )
    ).toBeNull()
  })

  it('returns null when the header parses but no line does', () => {
    // Better to show the raw text than a card with an empty body.
    expect(parseInvoiceDraft('Draft INV-0009 for Bellview CSA:\n  something unexpected')).toBeNull()
  })

  it('returns null for empty or unrelated results', () => {
    expect(parseInvoiceDraft('')).toBeNull()
    expect(parseInvoiceDraft(undefined)).toBeNull()
    expect(parseInvoiceDraft('Sent INV-0001 to Bellview CSA for $198.00.')).toBeNull()
  })
})

/**
 * The envelope the tools answer with now (`{success, message, invoice, …}`), and the prose they
 * answered with before it. The transcript holds both: a turn recorded last week has the prose, and
 * a card has to render it years later without the tool that wrote it
 * (the internal audit PLUG-15).
 */
const ENVELOPE = JSON.stringify({
  success: true,
  message: 'Draft INV-0042 for Bellview CSA:\n  • 12 kg Green Beans @ $12.00 = $144.00',
  invoice: {
    number: 'INV-0042',
    customer: 'Bellview CSA',
    currency: 'AUD',
    status: 'draft',
    tax_excluded: false,
    tax_label: 'GST',
    subtotal: '$144.00',
    tax: '$14.40',
    total: '$158.40',
    lines: [
      {
        quantity: '12',
        unit: 'kg',
        description: 'Green Beans',
        unit_price: '$12.00',
        amount: '$144.00'
      }
    ]
  }
})

describe('the JSON envelope', () => {
  it('reads the structured draft without re-parsing prose', () => {
    const draft = parseInvoiceDraft(ENVELOPE)
    expect(draft).not.toBeNull()
    expect(draft!.number).toBe('INV-0042')
    expect(draft!.customer).toBe('Bellview CSA')
    expect(draft!.taxLabel).toBe('GST')
    expect(draft!.tax).toBe('$14.40')
    expect(draft!.total).toBe('$158.40')
    expect(draft!.isDraft).toBe(true)
    expect(draft!.lines).toEqual([
      {
        quantity: '12',
        unit: 'kg',
        description: 'Green Beans',
        unitPrice: '$12.00',
        amount: '$144.00'
      }
    ])
  })

  it('reads a tax-excluded draft as excluded', () => {
    const payload = JSON.parse(ENVELOPE)
    payload.invoice.tax_excluded = true
    payload.invoice.tax = null
    const draft = parseInvoiceDraft(JSON.stringify(payload))
    expect(draft!.taxExcluded).toBe(true)
    expect(draft!.tax).toBeUndefined()
  })

  it('returns null when the envelope carries no lines', () => {
    const payload = JSON.parse(ENVELOPE)
    payload.invoice.lines = []
    expect(parseInvoiceDraft(JSON.stringify(payload))).toBeNull()
  })

  it('classifies a refusal envelope as a question', () => {
    expect(
      classifyToolResult(JSON.stringify({ success: false, message: 'Which customer?', question: 'Which customer?' }))
    ).toBe('question')
  })

  it('classifies a failure envelope as an error', () => {
    expect(classifyToolResult(JSON.stringify({ success: false, message: 'the store is gone' }))).toBe(
      'error'
    )
  })

  it('still reads the prose a turn recorded before the tools answered JSON', () => {
    expect(classifyToolResult(GOLDEN_DRAFT)).toBe('ok')
    expect(parseInvoiceDraft(GOLDEN_DRAFT)?.number).toBe('INV-0001')
  })
})

describe('the legacy prose vocabulary', () => {
  /**
   * The prefixes are a hand copy of three sentences in `plugins/pantler/tools.py`, and nothing
   * checked that they still agreed — a one-word change to a Python sentence would silently
   * reclassify every refusal recorded before the tools answered JSON
   * (the internal audit CON-5). This is the binding: it reads the Python and asserts the
   * literals are there.
   */
  const tools = readFileSync(
    fileURLToPath(new URL('../../../plugins/pantler/tools.py', import.meta.url)),
    'utf8'
  )

  it('still matches the sentences the plugin writes', () => {
    for (const prefix of [...MONEY_PACK.questionPrefixes, ...MONEY_PACK.errorPrefixes]) {
      expect(tools).toContain(prefix.trim())
    }
  })

  it('classifies each of them the way the pack says', () => {
    for (const prefix of MONEY_PACK.questionPrefixes) {
      expect(classifyToolResult(`${prefix} Which customer?`)).toBe('question')
    }
    for (const prefix of MONEY_PACK.errorPrefixes) {
      expect(classifyToolResult(`${prefix} no such item`)).toBe('error')
    }
  })
})

describe('classifyToolResult', () => {
  it('recognises the ledger refusing to guess', () => {
    expect(
      classifyToolResult('I need to check one thing before I bill this. Which Bellview did you mean?')
    ).toBe('question')
  })

  it('recognises a bare question', () => {
    expect(classifyToolResult('Which invoice number should I show?')).toBe('question')
  })

  it('recognises the error paths', () => {
    expect(classifyToolResult("I couldn't build that invoice: bad quantity")).toBe('error')
    expect(classifyToolResult("I can't reach the price book: not found")).toBe('error')
  })

  it('treats a real draft as ok', () => {
    expect(classifyToolResult(GOLDEN_DRAFT)).toBe('ok')
  })

  it('reports an empty result rather than calling it ok', () => {
    expect(classifyToolResult('   ')).toBe('empty')
    expect(classifyToolResult(undefined)).toBe('empty')
  })
})
