# Provenance

Everything the studio ships is authored for Pantler and released under the MIT licence, except the
four font families, which are used under the SIL Open Font License 1.1 and carry their licence files
in `fonts/LICENSES/`.

## Fonts

| Family | Files | Licence |
|---|---|---|
| Young Serif | `YoungSerif-Regular.ttf` | `fonts/LICENSES/OFL-YoungSerif.txt` |
| Barlow | `Barlow-{Regular,Medium,SemiBold,Bold}.ttf` | `fonts/LICENSES/OFL-Barlow.txt` |
| Barlow Condensed | `BarlowCondensed-{SemiBold,Bold}.ttf` | `fonts/LICENSES/OFL-BarlowCondensed.txt` |
| IBM Plex Mono | `IBMPlexMono-{Regular,Medium}.ttf` | `fonts/LICENSES/OFL-IBMPlexMono.txt` |

All four are distributed by [google/fonts](https://github.com/google/fonts). None is modified, so no
Reserved Font Name applies. The licence text must travel with the fonts; `design_render` refuses a
face whose family has no licence file, which is what stops an unlicensed font reaching an operator's
card.

## Method

The library, templates, audit rules and process were informed by public work listed below. **No text
or code from any of them ships** — the shipped product is first-party under invariant 2, and the
licence ladder in the repository's design-inventory document is what decides that. The debt is
methodological and is recorded here rather than quietly absorbed.

| Project | Licence | What informed the design |
|---|---|---|
| [nexu-io/open-design](https://github.com/nexu-io/open-design) | Apache-2.0 | brand contract + template + critique gate as separate planes |
| [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design) | MIT | deal several directions and choose; the design check-up |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | MIT | a researched library, dealing with history, house rules checked in a browser, and the look-and-fix loop |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | Apache-2.0 | audit → critique → polish → harden as named passes |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT | the fields a usable style/palette/pairing library needs |
| [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) | MIT | the shape of a brand contract file |
| [mcpware/logoloom](https://github.com/mcpware/logoloom) | MIT | what a complete brand kit contains (lockups, icons, usage sheet) |
| [anthropics/skills](https://github.com/anthropics/skills) | no licence file | read, not used; nothing may be vendored |
| [meodai/skill.color-expert](https://github.com/meodai/skill.color-expert) | CC-BY-4.0 | colour science read; not shipped, because an attribution licence is not the payload's permission |
| [smixs/creative-director-skill](https://github.com/smixs/creative-director-skill) | CC-BY-4.0 | ideation methods read; not shipped |

## Text and rules

The directions, palettes, template arguments, the twelve tells and the five-dimension rubric were
written for Pantler's market — growers, makers, markets, labels and delivery. Where a rule restates a
public standard it says so and cites the standard in the repository (WCAG 2.2 contrast minimums), and
where a rule is a judgement it is written as one.
