---
name: design
description: Design a card, poster or social image.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the renderer is first-party PIL on the system's fonts
---

# Design

Use this when the operator wants something made to look at: a social card, a poster, a flyer,
a stall sign, a menu, a label proof or a recurring visual series. This skill owns the first
step and the look. It does not write a caption-only batch — that is `social-post-batch` — and
it does not make a document to send or print — that is `documents`.

## The first reply is the job

A vague request is not a reason to open the whole skill shelf. Say what you will make, then ask
the one or two questions the layout depends on. The operator asked for help, not for a survey.

- **Name the deliverable and its shape.** "A square feed card at 1080, plus the caption" or "a
  portrait story card at 1080×1350". If they asked for a set, name the set.
- **Ask at most two questions.** The one line that has to land, and where it is going. If they
  do not know, offer two concrete shapes — one line vs a short list, a day card vs an
  announcement — and let them pick.
- **Do not open with what is missing.** If the records are empty, say what you can still make
  from their words, then ask for the words. A list of missing records is not a first step.
- **Do not shop skill after skill.** If `design` is the closest, use it. Open
  `social-post-batch` only when the job is captions; open `documents` only when the job is a
  PDF. This skill carries its own renderer. Do not use the engine's bundled design skills in
  this product.
- **Make a draft when the words are enough.** If they gave the line, render the line. If they
  gave a date, use that date. Do not hold the card back for a third question.

A good first reply is short enough to answer on a phone:

> Yes — I'll make a square feed card and the caption to go with it. Two things: what's the one
> line that has to land, and where are you posting it? If you don't have the line yet, tell me
> what's actually ready this week and I'll draft from that.

## The brief, in one breath

| What | Where it comes from |
|---|---|
| The one message | the operator's own sentence, or the record they pointed at |
| The audience and the action | the operator; if unknown, ask once |
| The format and size | where it is going — feed, story, print, a sign |
| The copy | the operator's words, quoted exactly |
| The visual direction | their brand, their photo, or a neutral starter |
| The facts | the records; never a plausible number |

Look on the business's own file before asking: `record_find` for products, harvests, campaigns
and consents, and the profile's own `output/design/` or `output/` for a card family already in
use. Name what you found in one line. If the file has no family, say that and start one; do not
borrow another business's.

## The words are theirs

- **Never invent** a product, a price, a date, a quantity, a certification, an origin, a handle
  or a claim. A card with `[YOUR PRICE]` on it is not finished; a card with a price you guessed
  is worse.
- **Keep their spelling** for their own words (`jalapenos` stays `jalapenos`). Correct a plain
  typo and say in one line that you did (`thurday` → `Thursday`); a public card is the one place
  the wrong word is the only thing people take away.
- **A claim is checked, not written.** Run `claim_check` over the copy before hand-over. If it
  says `refuse`, the words come out; if it says `needs_evidence`, find the record or leave the
  claim out.
- **A photo of a person needs consent.** Check the consent record before a face goes on a public
  card; if there is none, use a different image or ask.
- **A photo you were not shown is not a photo you can describe.** Never suggest an image of a
  product the business does not have, and never generate a fake product photo.

## The look

- **One idea per surface.** One message, one accent, one call to action. A card that says three
  things is a card nobody reads.
- **Use their brand first.** Their colours, their type, their logo if they own it. If they have
  none, use a neutral starter palette and say it is a starter they can replace. Never put
  Pantler's brand on a customer's card.
- **Layout is measured, not eyeballed.** Fix the margins first (8–10% of the short side), then
  the top block, then the bottom block, then divide what is left. Print the numbers.
- **Two or three type sizes.** A headline, a band line or list, a small tracked label. Body copy
  is not the headline's job.
- **Contrast is a check.** Ink on the ground at least 4.5:1; large display text may go to 3:1.
  Wheat on cream is decoration, never text.
- **System fonts only.** Lato, DejaVu, Liberation or Arial are normal. Do not download a font
  at render time; if the operator has a licensed brand face, use it only when they supplied it.
- **No stock photos, no gradients, no glass effects, no fake badges.** The card is type on a
  ground unless the operator supplied an image.

| Target | Pixels |
|---|---|
| Instagram / Facebook feed square | 1080 × 1080 |
| Instagram portrait (4:5) | 1080 × 1350 |
| LinkedIn / link preview | 1200 × 627 |
| A4 print, label or sign | make a PDF with `documents`, not a PNG |

## Render

`scripts/render_card.py` is the type-only route. It measures the layout and prints every check.
Run it from this skill's directory — the `skill_view` result gives that path as `skill_dir` — or
pass the script's absolute path; the workspace is a different directory.

```bash
python3 "$SKILL_DIR/scripts/render_card.py" --out output/design/boxes.png \
  --headline "Local veggie boxes" --day "Every Thursday"

python3 "$SKILL_DIR/scripts/render_card.py" --out output/design/this-week.png \
  --eyebrow AVAILABILITY --headline "This week" \
  --items "Lettuce,Broccoli,Cauliflower" --footer "WEEK OF 19 OCTOBER" \
  --size 1080x1350 --ground "#F7F3EA" --ink "#1F2933" --accent "#B4552D"
```

The defaults are a neutral starter palette and the system fonts that are actually installed.
Pass the operator's colours; the script refuses a palette below 4.5:1 rather than shipping it.
If `python3 -c "import PIL"` fails, use the HTML/Playwright route or the interpreter the engine
already runs with; do not install a package without asking. Write under `output/design/` in this
workspace and keep the script beside the PNG in
`output/design/source/` so a copy edit is a re-run, not a rebuild.

For a richer layout — a photo, a logo, several blocks — write one self-contained HTML file and
screenshot it at the exact pixel size with Playwright, as the engine's carousel skill does. For
anything that has to be printed or sent, use `documents` and make a PDF. A screenshot of a page
is a preview, not the document.

## A recurring series

A series is a **frame**, a **subject** and a **cadence**: the same ground, type sizes and rules;
a subject that changes weekly; a day it lands. It is not a new design every week.

1. Render one proof in the frame from the operator's words.
2. Ask which subject and which day; do not invent either.
3. When they agree, save it as a `campaign` record with `record_save` (name, subject, channel,
   status, notes; there is no cadence field, so put the cadence in the name and notes).
4. Next week, extend the same family script — do not write a one-off file beside it. A card
   designed on its own drifts within two versions.

Nothing here posts, schedules or queues anything. The operator posts it themselves.

## Check and hand it over

- **Read the PNG back** with `vision_analyze`: every word present, no clipped text, the size
  exact, the contrast as printed. A render that wrote the file is not a card that reads.
- **Say what is a placeholder**, in one line, and what you need to replace it.
- **Hand over with `MEDIA:/absolute/path.png`** on a line of its own. The file must be under the
  profile's own workspace; a path outside it is not shown, and another business's path is not
  yours to open.
- **Offer one revision.** A card they had to rebuild is worse than a shorter honest one.

## What not to do

- Do not invent a logo, a brand story, a testimonial or a certification.
- Do not crop a person out of a photo to avoid the consent question; ask.
- Do not add prices, dates or produce the operator did not give.
- Do not use a font or an image you cannot establish a licence for.
- Do not promise that the card was posted, scheduled or sent.
- Do not use another business's card as a template or a "reference on file"; this workspace is
  the only one you can read.
