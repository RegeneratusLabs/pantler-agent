---
name: product-description
description: Write product page copy from the operator's own record.
license: MIT
metadata:
  category: pantler
  source: distilled from the internal capability plan §6 and the skills and plugins notes §2.5 (from the product record, claim-linted)
---

# Product description

Use this when the operator needs the words that go with a product — the shop page, the stall sign, the
market listing, the blurb on a wholesale sheet. They have the product; what they need is a paragraph
they can put their name to, and they would rather not write it at nine at night.

## The one rule

**Every fact in the description comes from the operator's own record.** Their product record, their
label, their certificate, the words they just said. You write the sentences; you do not supply the
facts, and you do not fill a gap with an adjective.

If the record does not say it, the description does not either. That is the whole skill: what is left
after you have refused to invent anything is a short description that is right, and a short
description that is right beats a longer one a customer can catch out.

## Four kinds of sentence

| The sentence | Where it comes from | What you do |
|---|---|---|
| **What it is** — name, what is in it, what it is like to eat or use | the product record and the label | write it, in the operator's words |
| **What you sell** — pack, weight, count, unit | the record, as given | state it; never work it out |
| **What it costs** | a price list or an invoice | leave it out |
| **What it claims** — organic, provenance, an environmental outcome, a health benefit | a document that backs it | check it before writing it |

Gather the first two into a fact list before you write a word, each line with where it came from. If
the list is thin, the description is short — that is not a failure, it is the honest shape of what the
record holds. Then ask for the missing piece instead of working around it.

**Build the fact list from the types this install declares.** Call `record_types` before hunting for a
record — a `product` type is not guaranteed to exist. Where it does not, the facts sit in whatever the
install does declare: a harvest lot, an input record, a certificate, a note the operator wrote.
`record_find` on a type the list did not return is an error, and an error is not evidence — it says
nothing about whether the operator holds the record, so it can never be reported as one.

## Claims are checked, not written

A claim is anything a customer, a competitor or a regulator could hold the business to: **certified
organic**, **spray-free**, **local**, **regenerative**, **pasture-raised**, **no added sugar**. Each
one needs a record behind it — a certificate with its number and expiry, an input or spray record, a
supplier's document, the label itself.

- **Never invent one, and never upgrade a fact into one.** "Grown here" and "chemical-free" are not
  the same sentence, and the second one is the one that gets a complaint.
- **A certificate is checked against the product, not the business.** A certified farm can have an
  uncertified product, and the certificate's scope is the thing that decides. A whole-farm scope does
  not name the product either: it covers what the farm grows, so a block or a harvest lot still has to
  tie *this* product to the farm — produce bought in for resale is the trap.
- **Call `claim_check` on the copy before you offer it.** It is a lookup over the claim list, not a
  judgement: it names each claim, says whether it matched confidently or might be an ordinary word, and
  says what would have to stand behind it. Then do what it says — a `refuse` verdict means the claim
  comes out, and for `needs_evidence` look for the record it names (`record_find`) before the sentence
  stays.
- **Health claims are refused, not softened.** The verdict is `refuse` because no record and no wording
  settles one until the health-claims research is done. Take it out and say what the food is instead.
- **A clean check is not a clearance.** The list is a checklist: a sentence can mislead without using
  any of its words, and the operator is the one making the claim.
- **Health benefits are the strictest of the four.** If nothing in the record supports it, it does not
  appear, however ordinary it sounds.

## When the record does not support the claim

Say what is missing in one line, and offer the true sentence beside it.

> "I can write *tomatoes from the Bellview block*, because that is in your harvest record. I can't
> write *organic* — there's no certificate on file for this product, and I won't put a claim in your
> shop page that you can't produce a document for. If you add the certificate, or point me at it, the
> sentence changes."

Then stop. Do not write the claim with a hedge in front of it, and do not write around it so a
customer reads it anyway. If the operator tells you it is fine, it still stays out: the description
carries what the records carry, and what they tell you is a new fact to record first, not a licence to
assert.

## Prices, weights and arithmetic stay out

- **No price in a description.** Not even one from the record. A price belongs to the dated price
  sheet, the invoice or the quote — a number in a description goes stale where nobody looks, and an
  old price on a shop page is a promise the operator has to honour.
- **No computed weight, pack size or yield.** If the record says a 500 g punnet, write 500 g. If it
  does not say, ask. Never add up, divide, convert or round.
- **Anything a tool can work out, you do not.** If the operator needs those figures, that is the price
  sheet's work, not this description's.
- **Label wording is not this job.** Mandatory particulars — ingredients in order, allergen
  declarations, country of origin, net weight, a nutrition panel — belong on the label, and a
  checklist decides what is required. If the copy is headed for a package rather than a page, say so
  and point at that job rather than guessing at a panel.

## The draft

Write it as the operator would say it at the stall, and keep it to what the record holds. A useful
shape, not a template to fill:

1. what it is, in the operator's own name for it;
2. what is in it, or how it was grown or made — the facts from the list;
3. how to use it or keep it, when the record says;
4. where it comes from, when the record says.

**When the fact list is empty, hand the shape over anyway.** The description is the product's name in
the operator's own words and nothing else. Run `claim_check` on a fuller version so the claim's verdict
is on the record, keep the claim out of the draft, and offer the claim's true sentence beside it with
what would unlock it. Close with the two or three questions whose answers write the rest — what it is,
how it is sold (heads, kilos, bunches), which block it came from. A name-only draft plus those
questions is the finished job; padding it with adjectives is not.

No adjectives standing in for facts, and nothing about being the best at anything. Mark the block
`draft` with its date, and name the product record it was written from, so the operator can see this
description is the one that matches the record they have now.

## Before you hand it over

Read it back, and name what you left out — the second list is the one they will need later:

- the description, as a block they can copy;
- each factual sentence with the record it came from;
- every claim you dropped and what document would unlock it;
- the numbers you did not write, and where they actually live.

Then the operator's part: read it, change anything that does not sound like them, and put it where it
is going. A description they had to rewrite is a worse description than a shorter one that was already
true.
