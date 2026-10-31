---
name: newsletter-issue
description: Draft one customer email the operator sends themselves.
license: MIT
metadata:
  category: pantler
  source: distilled from the internal capability plan §6 and the skills and plugins notes §2.5 (draft-only as the mechanism, the consent shape, the claims law)
---

# Newsletter issue

Use this when the operator wants to write to their customers: the box-scheme note, what is ready this
week, the stall on Saturday, a recipe for the glut. They have the records and the season; what they
need is one issue, written, that they can send today without staring at a blank page at nine at night.

## The one rule

**You write one issue. The operator sends it, from their own account.** Email is one of the few paths
with nothing in front of it — no app review, no audit — and there is still no sending path here: no
account of theirs, no list, no transport, no scheduling. **Never say you sent, scheduled, queued,
published or added anyone to anything.** What you hand over is text they paste into their own mail
tool and send themselves.

That is the mechanism, not a preference we hold: with no account of the operator's and no consent
record in front of you, there is nothing here that can send, and **no promise of a mail provider, a
list tool or an integration** belongs anywhere in the draft.

## Who receives it is not your decision

The list stays the operator's, in their own mail tool — you never hold it. But **whether each person
may be written to is a check you can run**: `consent_check` takes the names and where the message
would go, and gives one decision per person — `allowed` (with the consent record), `no_record`,
`withdrawn`, or `ambiguous` — plus whether the draft is missing an unsubscribe line or a sender.

- **A `no_record` or `withdrawn` decision is the end of it.** Say who cannot be written to and what is
  missing; do not offer to send "just to the others" without the operator saying so, and never decide
  that a past purchase or an existing customer counts as consent. The tool refuses because the
  research found the same statutory gate in every jurisdiction examined — it is not a house rule.
- **Check before the send, not after.** Run it when the operator gives you the names, say who is clear,
  and name the record the consent came from.

What the tool does not do, and you must not pretend otherwise: it does not hold the list, and nothing
here sends.

- **You never assemble, import, merge, deduplicate, export or count a recipient list**, and you never
  write out an address.
- **You do not write the unsubscribe line or the sender identification.** The operator's mail tool adds
  both. If theirs does not, that is a question for their provider before anything is sent, not a
  sentence for you to invent.
- **Ask them to confirm that the people receiving this asked for it.** The record worth holding is one
  line per person: who asked, the words they saw when they asked, the date and where it happened, what
  they agreed to receive, and when they asked to stop. That record is theirs to keep; the check before
  this send is theirs to make.
- An email to someone who never asked is a breach of the rules we checked — the Spam Act 2003 (Cth),
  CAN-SPAM, ePrivacy Art 13 — and it is the worst thing this skill could help with. When in doubt, the
  answer is fewer recipients, not a softer wording.

## Where the facts come from

| In the issue | Where it comes from |
|---|---|
| what is ready, and how much | this week's availability list, or what they said walking the rows |
| what it costs | a dated price sheet, quoted with its date — or left out |
| what happened this week | the operator's own words, not yours |
| the season note | the operator. No seasonality table is held anywhere in the product |
| a variety, a block, a farm name | the harvest or product record |
| *certified organic*, provenance, an environmental line | the certificate or input record that backs it, with the scope checked against the product |
| the recipe | their own kitchen, with their amounts. You do not invent one, scale one or convert one |
| how many people get this | nobody here knows. The count is their mail tool's, and it is not printed in the issue |

**Not everything in that column is held by the product.** Nothing holds a seasonality table or a
subscriber list, and the price sheet and the availability list are documents the operator has — the
capabilities that generate them are not built. When a document is not in front of you, the line it
would carry does not go in.

If a fact is in none of those, ask for it. **No price, weight, availability, certification, harvest
date or event goes in because it sounded right**, and no line about a customer, a competitor or
last year's weather comes from anywhere but the operator.

For the opening, their words do not have to arrive in this session. Search their past messages
(`session_search` with `role_filter='user'`) for sentences they actually wrote for a customer or
dictated about the week, and quote those with where each came from. A message that asks you to
invoice, record or look something up is a work order, not their voice — an opening built from one of
those is your prose wearing their name. If nothing customer-facing is on file, leave the opening as a
marked gap for them to fill rather than writing it.

## Claims are checked, not written

- **Organic, provenance and environmental lines each trace to a record or they do not appear.** A
  certificate is checked against the product being sold, not against the business: a certified farm
  can have an uncertified product, and the certificate's scope decides.
- **A generic green word is refused outright** — *sustainable*, *eco-friendly*, *natural*, *green*.
  In the EU these become an unfair commercial practice from 27 September 2026 (EmpCo, Directive (EU)
  2024/825), and they were never a fact.
- **Health claims are refused, at all.** No health or nutrition claim goes out in marketing copy until
  the rule that backs one is authored; the claim lint refuses them, including the ordinary ones —
  *good for your gut*, *full of antioxidants*.
- **No testimonial you were not given with permission**, no invented review, and no *our customers
  love it*, *award-winning* or *most popular* without a record and a permission behind it. Customer
  words are a different job with its own rules; bring the message and the permission, or leave it out.

## Prices and sums stay out

**A price comes off a dated price sheet, a count comes off the operator's mail tool and a date comes
off their calendar; you quote those, and you do not add, subtract, convert, round or work out a
percentage off anything** (the design notes invariant 1).

- Write a price only as the sheet states it, with the sheet's date beside it, and say in the handover
  that it is the date a reader will hold them to.
- No percentage off, no total, no saving, no weight conversion, no *about a kilo*, no subscriber count
  and no sell-through. If they want a figure, name the tool that computes it; if it is not built, say
  so and leave the sum to them.
- A date they gave — "order by Thursday", "at the market Saturday" — is fine as given. Which date that
  is, is not yours to work out.

## The blocks of an issue

1. **A subject line**, two options, short, factual, no claim: what is ready, or what the week is.
2. **The opening**, two or three sentences of the operator's own news, in their voice.
3. **What is ready this week**, from the availability list, with the quantity words they used.
4. **The season note**, if they gave one: what is ending, what is starting, what the weather did.
5. **The recipe**, only theirs, with their amounts left exactly as they are.
6. **The ask and the date** — order by, collect on, find us at — as they said them.
7. **The sign-off**: their business name and the way they want to be reached, as they gave it.

No unsubscribe line, no footer and no sender block written by you; those are the mail tool's. Keep the
whole thing as one block they can copy, marked `draft` with the date and the records it was written
from.

## When a fact cannot be supported

Say what is missing in one line and offer the true sentence beside it.

> "I can write *boxes this week: cavolo nero, kale, the last of the tomatoes*, because that is in your
> availability list. I can't write *20% off boxes until Friday* — I have no price sheet and no discount
> in front of me, and working out twenty per cent is a sum, not a sentence. Give me the sheet, or the
> words you want, and it goes in as you said it. And I can't write *good for your gut* at all: no
> health claim goes into a customer email until the rule behind one is authored."

Then stop. Do not write the claim with a hedge in front of it, and do not write around it so a reader
hears it anyway. If the operator says it is fine, it still stays out: the issue carries what the
records carry.

## Before you hand it over

Read it back as one email, in the order a customer reads it, and name what you left out:

- the issue, as a block they can copy, subject lines first;
- each factual sentence with the document it came from, and the date on any price;
- every claim and every number you dropped, and what would unlock it;
- what you could not check — the consent behind the list, a certificate's scope, a date.

Then the operator's part, said plainly: read it, cut anything that does not sound like them, check
that these people asked to hear from them, and send it from their own account. A shorter honest issue
they actually send is worth more than a fuller one that sits unsent.
