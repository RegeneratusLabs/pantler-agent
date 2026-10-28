---
name: campaign-calendar
description: Plan what to talk about, month by month, from records.
license: MIT
metadata:
  category: pantler
  source: distilled from the internal capability plan §6 and the skills and plugins notes §2.5 (draft-only as the mechanism, the claims rule, dates and sums are code's job)
---

# Campaign calendar

Use this when the operator asks what to talk about, or when a quiet fortnight is coming and they know
something will be ready in it. When they ask for a recurring theme across their posts, that is a
series and not a calendar — jump to *A recurring series* below. What they bring is what they already know: what is in season, the
markets they sell at, the days their customers cook for, what sold out last year, and the dates
somebody else gave them. Your job is to put that in date order and say, week by week, what to talk
about and which record stands behind each line.

## The one rule

**You write a plan. Nothing here sends, posts, schedules or reminds.** There is no path from this skill
to a social platform, a mailing list or the operator's own calendar: no account of theirs, no consent,
no integration a small producer can switch on. So the artefact is text — a dated list they read, cut
down, and paste into whatever calendar they actually keep. **Never say you added it, scheduled it, set
a reminder or queued anything, because you cannot.**

## Where a line comes from

| The line in the plan | Where it comes from |
|---|---|
| a market day, a stall, a delivery run, a holiday they trade on | the operator's own calendar, or the words they just gave you |
| what is in season, and when it starts and ends | the operator. Nothing in the product holds a seasonality table, so a crop's month is theirs, never yours |
| what came off, and when | the harvest records: a lot, a date, a block |
| what to offer this week | this week's availability list, or what they said while walking the rows |
| a claim — organic, provenance, an environmental outcome | the certificate or input record that backs it, checked before it is written |
| what worked last year | the operator's own file. The season review that would hold sell-through is not built, so ask |

**A campaign can be saved; the calendar itself is a document.** The `trade` pack holds a `campaign`
record — *Name*, *Subject*, *Starts*, *Ends*, *Main channel*, *Status* — so when a plan becomes a thing
the operator is running, save it with `record_save` and read it back with `record_find`. What the pack
still does not hold is a seasonality table, a market date, a subscriber count or a season review, so any
figure from those comes from the operator or from a tool, never from you. Say that plainly rather than
implying the product already knows.

If a line needs a fact that is in none of those places, ask for it. **No price, weight, availability,
certification, harvest date or event enters the plan because it sounded right.**

## Dates are not yours to work out

**Every date comes off the operator's own calendar and every figure comes off a tool; you place a line
under a date you were given and you compute nothing — not a date, an interval, a week number, a lead
time, a percentage off or a count of anything** (the design notes invariant 1).

- "Pumpkins through March" is fine when they said March. Which day that is, and how many weeks away,
  is not yours to work out.
- If a date is missing, keep the line and mark it `date needed`. Do not fill one in from a pattern.
- An order cut-off, a picking day, a delivery day and the gap between them are three facts. Take all
  three from them; never derive the third.
- If a figure needs arithmetic — a percentage off, a sell-through, a count of how many people get the
  newsletter — name the tool that computes it. If that tool is not built, say so and leave the figure
  to the operator's own mail tool or spreadsheet.

## The turns

1. **Ask for the horizon and the anchors.** How far ahead — a month, a quarter, twelve months. Then
   the fixed dates: markets, stall days, order cut-offs, deliveries, holidays their customers cook
   for, anything they have been told by a wholesaler or a fair. Take them as given, in their words.
2. **Take the season from them.** Crop by crop, month by month, in the names they use — "the cavolo
   nero runs to September, the tomatoes are a gamble after February". Where they are unsure, write
   what they said and mark it as theirs.
3. **Pull the record-backed lines.** Harvests already recorded, this week's availability list,
   certificates that cover what is being talked about, anything from last year's file. Name the
   document each line came from.
4. **Put it in date order, one block per week or month** — whichever the operator asked for, and never
   a block you invented between two dates they gave.
5. **Keep talk-about and do-this apart.** A campaign calendar says what to talk about and where the
   facts are; it is not a task list, and it does not become one. If they want reminders, that is their
   own calendar's job.
6. **Mark the gaps, one line each**, with the question that closes it: no photo of that crop, no
   certificate covering that product, no date for that market.
7. **Read it back** in date order and stop. Nothing on the list is approved by being written.

## The shape of a line

| Date, as given | What to talk about | Behind it | Still needed |
|---|---|---|---|
| Thu 5 | the first of the new season garlic | harvest record, lot GAR-04 | a photo, or say it without one |
| market Saturday | the stall, and what is on it | Saturday stall, their calendar | the availability list for that week |
| week of the 19th | the glut — zucchini, every way | their words; no record yet | quantity, if any is to be promised |

A dated list in a table is enough. Do not dress it up with a month-by-month narrative the operator
has to read twice to find the dates.

## A recurring series

A "recurring theme across our posts" is a series, not a month of ideas: one frame, one subject, one
cadence, repeated. The operator is asking to be recognisable, so the win is one thing done again
rather than twelve things done once.

1. **Find the frame already on file before proposing one.** Look at the card families in every
   `output/instagram/source/` (see `social-carousel`) and at the campaign records. Two cards sharing a
   frame is a series already half-decided — say so, because it is free and it is theirs.
2. **Name the three parts and ask only for the ones that are missing.** The frame (art and type), the
   subject (the one thing said again — a produce line, a day, a method), the cadence (as a recurrence:
   "every Thursday", never a date you worked out). Offer two or three candidate spines in their own
   vocabulary and say each one needs their words before it can be rendered.
3. **Do not invent the spine, the cadence or the first card's copy.** A series is a promise kept every
   week, so the wrong spine is a weekly wrong promise. With empty records and no copy, the honest
   hand-over is the frame plus one short question — not a rendered placeholder, and not a themed month.
4. **The chosen series becomes a campaign record.** Once they say what it is and how often, save it
   with `record_save` (channel `social`, status `running`, the subject and the recurrence in the notes)
   and read it back with `record_find`, so next month's post, the availability list and the calendar
   hang off one id. Do not create it while the series is still a question: a record says the thing is
   running.

## What you refuse

- **A date you cannot point to** — a public holiday, a market day, a fair, a festival, a "national
  avocado day". If the operator gave it, it goes in; if not, it does not, however well known it is.
- **A claim with no record behind it.** A month themed on *certified organic* needs a certificate
  whose scope covers that product. Not softened, not implied, not in a hashtag.
- **A health claim, at all.** No health or nutrition claim goes in marketing copy until the rule
  behind one is authored; the claim lint refuses them outright.
- **A generic green word** — *sustainable*, *eco-friendly*, *natural* — as a theme. In the EU these
  become an unfair commercial practice from 27 September 2026 (EmpCo, Directive (EU) 2024/825).
- **A price, a percentage, a weight, a subscriber count, a sell-through** — and never a discount you
  worked out.
- **A promise that something will be posted, scheduled, sent or reminded.** There is no such path.
- **A crop or a product the business does not have.** A plan is their year, not an imagined one.

## When the record does not back the line

Say what is missing in one line and offer the true version beside it.

> "I can put *garlic, first of the season* in the first week of November, because your harvest record
> has it. I can't theme the month *certified organic* — there's a certificate on file, but its scope
> doesn't name the garlic, and a claim a customer can check is the one that costs you. If the
> certificate covers it, or your certifier confirms it, the theme changes."

Then stop. If the operator says the claim is fine, it still stays out: the plan carries what the
records carry, and what they tell you is a fact to record first, not a licence to assert.

## Before you hand it over

Read the plan back in date order and name what you left out:

- the dated lines, each with the document or the person behind it;
- the gaps, as questions, in the week they matter;
- every claim and every figure you dropped, and what would unlock it;
- what you could not check — a date, a licence, a season the operator was unsure of.

Then the operator's part, said plainly: read it, cut what is not true any more, and paste it into their
own calendar. A plan they had to rewrite is a worse plan than a shorter one that was already true.
