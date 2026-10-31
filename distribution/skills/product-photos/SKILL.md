---
name: product-photos
description: Prepare the operator's own photos for a card.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the operations are the studio plugin's, on the operator's own files
---

# Product photos

Use this when the operator has photos and wants them to look like something — a phone shot of a crate
under a fluoro light, a label on a jar at an angle, a stall taken from too far away. The job is to
make their photograph usable, not to make a different photograph.

This is not image generation. There is no version of this where the studio produces a picture of
produce the business did not grow.

## What can honestly be fixed

| Problem | What the tool does |
|---|---|
| The phone held the wrong way | orientation from EXIF, corrected |
| A 12 MP file nobody needs | resized to 2400 px on the long edge, metadata stripped |
| The wrong shape for a feed | a 1080 square and a 1080 × 1350 portrait, cropped on the subject |
| The subject is off-centre | the crop is centred where the operator says (`focus`) |
| Too many to choose from | a contact sheet with the file names, so they choose |
| Colour is cold or green | say it; a tint is a treatment, not a fix, and it is offered, not applied silently |

What it does **not** do: remove a background, add a product, "improve" a plate, change a label, or
make a small photo large. Say that plainly rather than shipping a soft upscale.

## The first reply

One line of what you can do, and the question the crop depends on:

> Yes — send the photos and I'll get them to a square and a portrait, cropped on the produce. Where
> should the crop sit: the middle, or nearer the top of the frame?

- **Ask for the files**, not for a description of them.
- **Do not describe a photo you have not opened.** Read it first.
- **If they have no photos**, say so and design a type-only card. Never offer a stock image of "a
  farmer".

## Prepare them

```json
{"inputs": ["attachments/tomatoes-1.jpg", "attachments/tomatoes-2.jpg"],
 "mode": "social-crops", "focus": [0.5, 0.42], "out": "output/photos/tomatoes"}
```

- `clean` — orientation, size, metadata. The default, and the safest.
- `social-crops` — a 1080 square and a 1080 × 1350 portrait per photo.
- `contact-sheet` — every photo on one page with its file name, for choosing.

Then render the card with `design` and the chosen photo as `image.path`.

## The rules that are not about pixels

- **A face needs consent.** Before a person appears on a public card, `consent_check` against the
  consent record: who, what they agreed to, where it may be used. A photo of a person from a market
  stall is not a photo the business may put on Instagram because it was taken in public.
- **A customer's label is not yours to change.** Cropping a competitor's or a supplier's packaging
  into a card is a claim about a product the business may not make.
- **Do not crop a person out to avoid asking.** Ask.
- **Do not retouch a product into something it is not** — no "fuller" boxes, no greener leaves, no
  cleaner bench. A card that misrepresents the produce is a complaint waiting to happen, and in some
  markets it is a statutory one.
- **Keep the original.** The tool writes new files; the operator's photo stays as it was.

## Hand it over

- The card PNG with `MEDIA:`, and the photo files' paths if they want them too.
- Say which crop you used and what you did to the file, in one line.
- If a photo was too small, soft, or badly lit to use, say so and suggest the shot that would fix
  it — "a photo at the stall in daylight, from about a metre, with the label facing the camera".
- Offer one revision of the crop.
