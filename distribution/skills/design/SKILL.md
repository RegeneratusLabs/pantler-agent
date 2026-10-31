---
name: design
description: Design a card, poster, flyer, sign or menu.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the renderer, library and audit are the studio plugin's
---

# Design

Use this when the operator wants something made to look at: a social card, a poster, a flyer, a stall
sign, a menu, a price board or a label proof. This skill owns the first step, the look and the check.
The studio plugin does the measuring.

| The request | The skill |
|---|---|
| A card, poster, flyer, sign, menu or price board | **this skill** |
| A one-page website | `website` |
| A logo, colours or a consistent look | `brand-identity` |
| A document to send, print or sign | `documents` |
| Captions with no artwork | `social-post-batch` |
| "Does this look right?" about something that exists | `design-review` |

Do not shop skill after skill. If `design` is the closest, use it.

## The first reply is the job

Say what you will make, then ask the one or two questions the layout depends on. Do not open with a
records survey; do not read a record before you have replied.

> Yes — I'll make a square feed card and the caption to go with it. Two things: what's the one line
> that has to land, and where are you posting it? If you don't have the line yet, tell me what's
> actually ready this week and I'll draft from that.

- **Name the deliverable and its shape** — "a square feed card at 1080", "a portrait story card".
- **Ask at most two questions.** Everything else can be a marked blank.
- **Make the draft when the words are enough.** A `[PRICE]` the operator can fill beats a third
  question.

## No brand? That is the first job

A card with no brand is a one-off, and a week of one-offs is a business that looks like six
businesses. Look for `output/brand/brand.json` first.

- **It exists** → pass it to `design_render` as `brand`. Every design reads it; that is the whole
  point of the file.
- **It does not exist** → ask the two brand questions from `brand-identity` (how it should feel, and
  where people will meet it first), save a **starter** kit, and design from it. Say in one line that
  you started a brand so everything matches, and that it is a starter they can change.
- **Never invent a palette and call it theirs.** "I've started you on a warm cream and a terracotta —
  say if you'd rather something else" is honest; a silent purple gradient is not.

Do not run the full identity interview inside a card request. Two questions and a starter is enough;
`brand-identity` is where a business goes to do it properly.

## Name the surface before the look

Most generic design is a composition mistake, not a colour mistake:

| Surface | The reader is | The composition |
|---|---|---|
| **Decide / learn** | being convinced or taught | one idea, a hero is allowed |
| **Operate** | taking an action | the action and its state dominate |
| **Compare** | weighing options | aligned columns, parity |
| **Monitor** | watching state | density, no marketing framing |

A market stall poster is *decide*. A price board is *compare*. A dashboard is *monitor* and gets no
centred hero.

## Choose a direction; do not invent one

Ask `design_templates` for the library, then pick a direction whose argument fits the operator's
words. Deal three when they have asked to choose; otherwise choose one and say why in a line.

- **One idea per card.** One message, one accent, one action.
- **Hierarchy is scale, weight and space** — not a coloured rail, a badge or a shadow.
- **Composition before colour.** If the layout is centred because you did not decide, it will read
  as undecided.
- **Use their photos.** A type-only card is finished; a fake product photo is not.

The full tell list and the composition rules are in [`references/composition.md`](references/composition.md).

## Render it — never draw it by hand

`design_render` takes a brief and returns a self-contained SVG, an exact-size PNG and a preview page,
plus the checks. You supply the words; the tool supplies every number.

```json
{"spec": {
  "template": "feed-square-day",
  "direction": "01-quiet-ledger",
  "brand": "output/brand/brand.json",
  "content": {"eyebrow": "Availability", "headline": "Local veggie boxes",
              "day": "Every Thursday", "footer": "BELLVIEW FARM"},
  "out": "output/design/2026-10-31-veg-boxes"
}}
```

- **Do not look for a renderer in the workspace.** There is no script to find and nothing to
  inspect: the tool is the renderer. Call `design_templates` at most once if you need a direction,
  then `design_render`. Do not read old output, list the workspace, or draw with the terminal.
- **Never supply coordinates, font sizes or margins.** If a template cannot hold the words, choose
  another template or cut the words.
- **List rows are `Item | 12`** — the vertical bar separates the item from its quantity or price.
- **Read the checks.** A hard failure means the card is not finished. Fix the brief and render again.
- **Look at the PNG** with `vision_analyze`: every word present, nothing clipped, the right size. If
  vision is unavailable, say so and lean on the measurements — never claim a look you did not take.
- **One revision is normal.** A card the operator had to rebuild is worse than a shorter honest one.

## The words are theirs

- **Never invent** a product, price, date, quantity, certification, origin, handle or claim. A card
  with `[YOUR PRICE]` is not finished; a card with a price you guessed is worse.
- **Keep their spelling** for their own words. Correct a plain typo and say so in one line.
- **A claim is checked, not written.** Run `claim_check` over the copy. `refuse` means the words come
  out; `needs_evidence` means find the record or leave it out.
- **A face needs consent.** Check `consent_check` before a person appears on a public card.
- **A photo you were not shown is not a photo you can describe.** Never suggest an image of a product
  the business does not have.

## Print and signs

For anything printed, the SVG is the deliverable and the PNG is the proof: `documents` makes the PDF.
Four templates are sized in millimetres — `poster-a3`, `sign-a3`, `menu-a4` and `label-proof` — and
the SVG is written at its physical size (`width="297mm"`), so it opens correctly in a print
application. Quote the `physical_mm` from the report, never the pixels.

Leave 3 mm of bleed and keep every word inside the trim. A dieline, a folded leaflet or a die-cut
shape is not in the library: say so rather than stretching a card into it.
Type below 2.5 mm is decorative, not readable. A label's mandatory particulars are not this skill's
to invent — `labelling-honey-and-juices` and `packaging-and-epr` own them, and the label proof is
where they are checked. Never draw a certification badge; the certifier owns the mark.

More in [`references/print.md`](references/print.md).

## A recurring series

A series is a frame, a subject and a cadence: the same direction, the same type sizes, a different
subject each week. Render one proof, agree the subject and the day, save a `campaign` record, and
extend the same brief each week rather than writing a new one. A card designed on its own drifts
within two versions.

Nothing here posts, schedules or queues anything. The operator posts it.

## Hand it over

- `MEDIA:/absolute/path/card.png` on a line of its own, and the SVG path beside it.
- Say what is a placeholder, in one line, and what you need to replace it.
- The file must be under the operator's own workspace; another business's path is not yours to open.
- Offer one revision.

## What not to do

- Do not invent a logo, a brand story, a testimonial or a certification.
- Do not add prices, dates or produce the operator did not give.
- Do not use a font that is not in the studio's licensed set, and do not download one.
- Do not put Pantler's own brand on the operator's card.
- Do not promise that a card was posted, scheduled or sent.
- Do not use the engine's bundled design skills in this product.
