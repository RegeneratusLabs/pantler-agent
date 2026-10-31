---
name: design-review
description: Check and fix a design someone already made.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the rubric is the studio's, and the audit is its tool
---

# Design review

Use this when something already exists and the operator wants to know whether it is any good — a
page, a card they made themselves, a flyer from their printer, a draft you produced two turns ago, or
a screenshot of their own shop front. The job is a diagnosis and a bounded repair, not a redesign.

A new card is `design`; a new page is `website`; a logo is `brand-identity`. This skill does not start
over.

## Answer the question they asked

Most review requests are one of three, and they want different work:

| They ask | They want |
|---|---|
| "Does this look right?" | a short, honest verdict and the two or three things that matter |
| "Why does it look cheap?" | the diagnosis, in plain language, not a lecture |
| "Fix it" | the fix applied, and a before/after |

Ask which one if it is not clear. Do not deliver a six-page critique to somebody who asked whether
their flyer is fine.

## Look at it properly first

1. **Get the artifact.** A file path, a screenshot, a URL they are willing to share. If it is a URL,
   the browser tool reads it; if it is an image, `vision_analyze`.
2. **Say what you are looking at** in one line: "a 1080 square, dark ground, one serif, a photo
   across the top". This catches the case where you were sent the wrong file.
3. **Measure what can be measured.** If it is one of ours, `design_audit` with the brief gives the
   contrast, margins, type sizes and placeholders. If it is theirs, run the checks you can
   honestly run and say what you could not.

## The review, in this order

Do not start with colour. Colour is the last thing that is wrong, and it is the thing people ask
about first.

1. **The idea** — what is this saying, and is it saying one thing?
2. **The composition** — is there a shape, or did things land where they fit?
3. **The type** — how many sizes, is the hierarchy real, does the display face fight the text face?
4. **The colour** — does the ink clear 4.5:1, is the accent doing a job or decorating?
5. **The finish** — clipped words, a 6 px mismatch, a placeholder, a fake badge.

The rubric, with what a 0, 1 and 2 look like on each, is
[`references/rubric.md`](references/rubric.md). Score before you speak; say the score only if it
helps.

## Say it so it can be acted on

- **Lead with what works.** One line, and mean it. A review that opens with a fault is a review the
  operator stops listening to.
- **Name the two or three things that matter**, not twelve. "The headline and the list are fighting
  for the same weight, and the photo is competing with both" is a review. A list of eighteen nits is
  a mood.
- **Give the fix, not the principle.** "Set the list two steps smaller and let the headline be the
  only thing that big" — not "improve hierarchy".
- **Separate taste from defect.** A defect is clipped text, a contrast failure, a fake certification
  badge, an invented price. Taste is "I would have used the serif". Say which is which.

## If they asked you to fix it

- Fix the two or three things you named, and nothing else. A review that turns into a redesign is a
  review nobody asked for.
- Keep a copy of the original beside the new file, and show both.
- Re-measure after the fix. "Fixed" without a check is a claim.
- Say what you did **not** change, and why — especially if you left a defect you could not fix
  without new copy or a new photo.

## When the honest answer is "this needs a designer"

There are things a studio cannot fix: an illustration that has to be drawn, a mark that has to be
designed rather than set, a print job that needs a dieline, a brand that needs a strategy. Say so in
one line, say what you *can* do instead, and do not pretend a recolour is a rebrand.

## What this skill will not do

- It will not claim a visual check it did not make — if `vision_analyze` is unavailable, say the
  review is measurements only.
- It will not score a design it has not looked at.
- It will not praise to be kind, or invent a fault to seem rigorous.
- It will not "modernise" the operator's existing logo, or remove a certification mark that is
  genuinely theirs.
