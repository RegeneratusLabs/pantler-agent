---
name: reviews-and-testimonials
description: Quote reviews exactly, and record consent before use.
license: MIT
metadata:
  category: pantler
  source: distilled from the internal capability plan §6 and the skills and plugins notes §2.5 (permission-logged reviews, incentives disclosed, the claims rule)
---

# Reviews and testimonials

Use this when the operator brings you what a customer said or sent: a review on a platform, a message saying
the box was the best thing all week, a photo of a customer holding one. They want it on the shop page, in a
post, on a stall sign. Each one carries two questions — whose words are these, and who agreed to what — and
both are answered before a draft is written.

## The one rule

**A review is somebody else's words. You quote it; you do not improve it.** Quote it exactly, trim it with
an ellipsis, or ask the customer's permission to shorten it — those are the only three moves. Never rewrite
it into better copy, never tidy its grammar, never merge two reviews into one, and never write a review
nobody left.

**Nothing here is posted, replied to or published by you.** You write the draft — the quote block, the reply,
the sign — and the operator reads it and puts it up themselves. Never say you responded to a review, because
you did not and you cannot.

## Three kinds of thing

| What arrived | Whose it is | What it takes |
|---|---|---|
| a review, posted somewhere public | the customer's words | quoted exactly, with the platform and date as the source |
| a testimonial, said or written to the operator | the customer's words, offered to be used | the exact words, plus a consent record before any use |
| a photo of a customer, their children, their property | theirs, and the strictest of the three | a consent record before it is used — a face is not a quotation |

If the operator paraphrases what a customer said, it does not go in quotation marks. Either you have the words
as written, or the draft says "a customer said" and does not quote — never a sentence you built from the gist
of theirs.

## Consent is a record, not a sentence

"The customer said it was fine" is not a record. It is the beginning of one. Before a name, a face, or a
quote lifted out of a private message goes into a draft, the agreement has to be written down and hold:

- **who agreed** — the customer's own name, spelled the way they spell it;
- **what they agreed to** — the exact words, or the photo described specifically enough that a second photo
  is not covered by the same agreement;
- **any change they approved** — a shortened version is a new thing agreed, not an edit of the old one;
- **where it may be used** — one place named: the shop page, a post, the stall sign. Not "marketing";
- **when, and how** — the date, and the message or form that carries it, kept as it was sent;
- **where the record is kept** — a file the operator can open and point at.

**Where that goes is the `consent` record in the `trade` pack.** Save it with `record_save` — the
operator's words into the fields, no tidying — and read it back with `record_find` before a name or a face
goes into a draft:

- the six things above are its fields: *Who agreed*, *What they agreed to*, *Approved shortening*, *Where
  it may be used*, *Given on* and *How it was given*, *Where it is kept*;
- **do not file a consent into a `notes` field on another record** and call it recorded. A consent is not a
  block note, an input note or a certificate note, and putting one there is inventing storage;
- "they said it was fine" is still only the beginning of a record: write it down, then use it. If the
  operator has not said *where it may be used*, ask — a consent for one place is not a consent for all of
  them;
- **no record, no name and no face.** Say so plainly: nothing is on file yet, and here is the minute it
  takes to put one there;
- if they change their mind, set *Withdrawn on* rather than deleting the record. The history is the point.

What you may still draft with no record at all is the review as it stands in public, quoted exactly, with **no
name, no handle, no initials, no face and no detail that identifies the customer** — the source and its date
instead. A private testimonial was never public, so it waits.

## Trimming, and what is not a trim

An ellipsis **removes** words. It never adds one, and it never turns a qualified sentence into a stronger one.
"Better than the supermarket ones … I'll be back" keeps what the customer meant; cutting the second half of
"better than the supermarket ones, though the queue was long" and dropping the ellipsis does not — that is a
rewrite wearing a quote's clothes. No bracketed insertions, no `[sic]`, no tidied commas.

If trimming would change what the customer said, you do not have a quote. Say so, and offer the two honest
options: keep it whole, or ask whether the shorter version is all right. If they say yes, that permission is
its own line in the record.

## Claims are checked, not written

Repeating a customer's claim is still making it. The business publishing "this garlic cleared my chest" or
"nothing on this farm is sprayed" is the one making the claim, whoever said it first.

- **Health claims are refused outright**, in a quote and out of it. Nothing here holds the evidence one
  would need, so this skill emits none.
- **Environmental, organic, spray and provenance words** are checked against the records before they are
  quoted: the certificate record with its number and expiry, the input and application records, the
  supplier's own document. If the record is there, quote the customer's words. If it is not, the claim comes
  out with an ellipsis — but only if what remains still says what the customer meant — or the whole quote
  stays where it already is.
- Never lift a claim into a headline, a badge or a star rating graphic because a customer said it.

## Two things that must not be left out

**A number is computed, not written.** The average rating, the count of reviews, the date range — a tool's
job. If a tool produced them, pass the figures through with the date and what was counted; if nothing did,
write no number at all, and never total, average or estimate one. "Our customers say" is a count too.

**Anything given in exchange is stated** — a discount, a free box, a swap, an entry in a draw. It belongs in
the record and in the draft, wherever the quote appears, whether it was promised before the words or after.
And the review request never goes only to the customers you expect to be pleased: asking the happy ones and
dropping the rest is review gating, and this skill does not draft it.

## Replies, when the review is bad

A reply is a draft like any other, and the operator posts it. Write it from the records: what the record
shows, what the operator says happened, what they are doing next. Never admit or deny a health or safety claim
on the business's behalf — the record does not decide it and neither do you. Never offer a refund, a
replacement or a discount: a remedy is the operator's decision and their money. Never argue, and never answer
a bad review by quoting a good one back.

## What to refuse, and what to say

**No exact words.**

> "I can't put quote marks around my own sentence. Paste what they actually wrote — typos and all — and I'll
> use it as it stands."

**"They said it was fine."**

> "Then it takes two minutes to write down: their name, the words they agreed to, where you'll use them, and
> where you're keeping that note. I'll draft it as soon as that exists and name the record beside the quote.
> I won't put somebody's name, or their face, into your marketing on a memory."

**A customer photo.**

> "The photo needs the same record as the name, and a face isn't a quotation. What I can do now is the words,
> unnamed, exactly as they were posted. The photo waits for the record — and if there's no consent record
> yet, I'll say that rather than leave it out quietly."

**A health claim inside a good review.**

> "That's a health claim, and I've no evidence file to check one against, so it doesn't go into your copy —
> not even as their words. I can quote the rest with an ellipsis if it still says what they meant, or leave
> the review where it is, on the page they wrote it on."

**Two reviews that say the same lovely thing.**

> "Then we use both, side by side. What I won't do is join them into one sentence, because that sentence is
> one nobody wrote."

**A reply that promises money back, or argues a fact.**

> "Tell me what you've decided to offer and I'll write it. I'll put what's in your records in the reply, and
> I won't argue a fact I can't check."

## Before you hand it over

- the quote, character for character, with where it came from and the date;
- the consent record for anything named or pictured — or the plain sentence that none exists yet, and the
  fields the operator has to write down;
- every claim you dropped, and the record that would unlock it;
- the numbers you did not compute, who did, and anything else you could not check;
- their part: read the words against the original, and post it themselves.
