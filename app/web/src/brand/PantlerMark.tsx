/**
 * The Pantler mark, as a stateful little object.
 *
 * The artwork is the canonical mark from `brand/logo/pantler-mark-ink.svg`. Its body, feet, stem
 * and leaves are copied verbatim — a test compares them against the file — and the eyes and mouth
 * stay true holes (a mask, not white shapes), so the mark works on any surface.
 *
 * The five faces are not new drawings. They are the asset's own primitives, posed: the two eye
 * ellipses and the one smile path are scaled, flattened, reused for the listening mouth, and
 * flipped for the frown. `brand/FOR-THE-AGENT.md` §2 describes those states; the construction
 * sheet fixes the proportions. When official state exports arrive, only the face table here
 * changes.
 *
 * Colour comes from the brand tokens through CSS variables: `--pl-mark` is cream on the dark
 * canvas and ink on the light one, and the wheat cheeks are the one permitted accent. Nothing
 * here hard-codes a brand hex.
 *
 * `outfit` is the one costume the mark wears: *The Monocle*, picked from the ten drawn in
 * `brand/reference/pantler-learning-variants.png` for the learning strip. A costume is not a
 * second drawing — everything above is untouched — it is a group added around the loaf.
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { cn } from '../ui/cn'
import { MASCOT_LABEL, type MascotState } from './mascot'

const VIEWBOX = '-186 -361 372 401'
const VIEWBOX_W = 372
const VIEWBOX_H = 401

const BODY =
  'M-158.0,4 C-158.0,-92.0 -96.0,-158.0 0,-158.0 C96.0,-158.0 158.0,-92.0 158.0,4 ' +
  'C158.0,8 154.0,12 148.0,12 H-148.0 C-154.0,12 -158.0,8 -158.0,4 Z'
const STEM = 'M0,-146 L0,-216'
const LEAF =
  'M0,49.0 C51.480000000000004,29.4 40.92,-25.48 0,-49.0 ' +
  'C-34.32,-21.56 -30.360000000000003,27.44 0,49.0 Z'
const MIDRIB = 'M0,33.32 Q10.56,0 0,-35.28'
const SMILE = 'M-26.0,-60 C-13.0,-47 13.0,-47 26.0,-60'

const EYE_Y = -86
const EYE_X = 52
const MOUTH_Y = -60

/** The two bright dots the construction sheet gives the happy face. */
const CHEEK_X = 78
const CHEEK_Y = -58

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * A blink every 2–4 seconds while idle, and only while idle.
 *
 * The face is a mask, so the blink is a different set of holes rather than a CSS transform on the
 * mask contents — SVG masks do not reliably repaint an animation inside themselves, and a blink
 * that misses is worse than no blink. Reduced motion turns it off entirely.
 */
function useIdleBlink(active: boolean): boolean {
  const [blinking, setBlinking] = useState(false)

  useEffect(() => {
    if (!active) {
      setBlinking(false)
      return
    }
    if (typeof window === 'undefined' || prefersReducedMotion()) return

    let next: ReturnType<typeof setTimeout> | undefined
    let close: ReturnType<typeof setTimeout> | undefined
    const schedule = () => {
      next = setTimeout(
        () => {
          setBlinking(true)
          close = setTimeout(() => setBlinking(false), 120)
          schedule()
        },
        2000 + Math.random() * 2000
      )
    }
    schedule()
    return () => {
      if (next) clearTimeout(next)
      if (close) clearTimeout(close)
    }
  }, [active])

  return blinking
}

/** One settle when the face changes, so a state change reads as the same object moving. */
function useSettle(state: MascotState): boolean {
  const [settling, setSettling] = useState(false)
  const previous = useRef(state)

  useEffect(() => {
    if (previous.current === state) return
    previous.current = state
    if (prefersReducedMotion()) return
    setSettling(true)
    const timer = setTimeout(() => setSettling(false), 200)
    return () => clearTimeout(timer)
  }, [state])

  return settling
}

/** The costumes the mark can wear. One at a time; the loaf itself never changes. */
export type Outfit = 'none' | 'monocle'

/**
 * The monocle.
 *
 * Drawn the way the face is — as a cut, in the mark's own hole colour (`--pl-cut`) — because a
 * rim in the mark's colour disappears into the mark's colour. That is the one rule a costume has
 * to obey and the reason this is not simply a second silhouette.
 *
 * Detail is fattened rather than thinned at small sizes: the chain and its beads get *heavier*
 * below 48 px, because at 32 px a hairline is a smudge and a smudge is worse than an omission.
 */
function OutfitLayer({ outfit, size }: { outfit: Outfit; size: number }) {
  if (outfit !== 'monocle') return null
  const fine = size >= 48
  return (
    <g data-outfit={outfit}>
      <circle
        cx={EYE_X}
        cy={EYE_Y}
        r="26"
        fill="none"
        stroke="var(--pl-cut)"
        strokeWidth="15"
      />
      <path
        d="M76,-98 C94,-94 102,-76 100,-56"
        fill="none"
        stroke="var(--pl-cut)"
        strokeWidth={fine ? 5 : 9}
        strokeLinecap="round"
      />
      <circle cx="100" cy="-48" r={fine ? 5 : 8} fill="var(--pl-cut)" />
      <circle cx="102" cy="-30" r={fine ? 5 : 8} fill="var(--pl-cut)" />
      <circle cx="72" cy="-106" r={fine ? 8 : 10} fill="var(--pl-wheat)" />
    </g>
  )
}

export interface PantlerMarkProps {
  state?: MascotState
  /** A costume laid over the canonical mark. `none` is the bare loaf. */
  outfit?: Outfit
  /** Height in px; the width follows the mark's own aspect ratio. */
  size?: number
  interactive?: boolean
  /** The accessible name when interactive. Defaults to the brand name and the state. */
  label?: string
  /** Drop in and squash on mount, for a mark that is arriving rather than resting. */
  enter?: boolean
  className?: string
}

export function PantlerMark({
  state = 'idle',
  outfit = 'none',
  size = 32,
  interactive = false,
  label,
  enter = false,
  className
}: PantlerMarkProps) {
  const blink = useIdleBlink(state === 'idle')
  const settling = useSettle(state)
  // A pat remounts the motion wrapper, which restarts the one-shot CSS squash. A counter is
  // simpler and more reliable than toggling a class and racing the animation. The settle lives
  // on a nested wrapper so a pat and a state change can animate at the same time rather than
  // one class's `animation` shorthand winning over the other.
  const [pats, setPats] = useState(0)
  const pat = useCallback(() => {
    if (prefersReducedMotion()) return
    setPats(value => value + 1)
  }, [])

  // `useId` is server-safe and unique per instance. SVG references cannot use the colons React
  // puts in the id, so they are stripped; any two marks still keep distinct names.
  const rawId = useId()
  const maskId = `pl-mark-${rawId.replace(/[^a-zA-Z0-9_-]/g, '') || 'x'}`

  const working = state === 'working'
  const listening = state === 'listening'
  const done = state === 'done'
  const cant = state === 'cant'

  const eyeRx = listening ? 14.5 : 13
  const eyeRy = working ? 5 : listening ? 14 : blink ? 1.5 : 13
  // Pivot below the feet, like a mark tipped on its base: rotating about the feet themselves
  // pushed the left foot out of the 401-unit viewBox and clipped it.
  const tilt = listening ? 'rotate(-7 0 60)' : undefined
  const dim = cant ? 0.55 : undefined

  const height = size
  const width = (size * VIEWBOX_W) / VIEWBOX_H

  const mark = (
    <svg
      viewBox={VIEWBOX}
      width={width}
      height={height}
      aria-hidden="true"
      focusable="false"
      className="block shrink-0"
    >
      <defs>
        <mask
          id={maskId}
          maskUnits="userSpaceOnUse"
          x="-260"
          y="-400"
          width="520"
          height="460"
        >
          <rect x="-260" y="-400" width="520" height="460" fill="#fff" />
          <g fill="#000">
            <ellipse cx={-EYE_X} cy={EYE_Y} rx={eyeRx} ry={eyeRy} />
            <ellipse cx={EYE_X} cy={EYE_Y} rx={eyeRx} ry={eyeRy} />
          </g>
          {working || listening ? (
            <ellipse
              cx="0"
              cy={MOUTH_Y}
              rx={working ? 22 : 9}
              ry={working ? 5 : 9}
              fill="#000"
            />
          ) : (
            <path
              d={SMILE}
              fill="none"
              stroke="#000"
              strokeWidth="11"
              strokeLinecap="round"
              transform={
                done
                  ? 'translate(0 -60) scale(1.15 1.25) translate(0 60)'
                  : cant
                    ? 'translate(0 -60) scale(1 -1) translate(0 60)'
                    : undefined
              }
            />
          )}
        </mask>
      </defs>

      <g transform={tilt}>
        <g opacity={dim}>
          <g mask={`url(#${maskId})`}>
            <path d={BODY} fill="var(--pl-mark)" />
            <rect x="-118.0" y="6" width="52.0" height="18" rx="9" fill="var(--pl-mark)" />
            <rect x="66.0" y="6" width="52.0" height="18" rx="9" fill="var(--pl-mark)" />
            <path
              d={STEM}
              fill="none"
              stroke="var(--pl-mark)"
              strokeWidth="15"
              strokeLinecap="round"
            />
            <g transform="translate(-24,-268) rotate(-52)">
              <path d={LEAF} fill="var(--pl-mark)" />
              <path
                d={MIDRIB}
                fill="none"
                stroke="var(--pl-cream)"
                strokeWidth="6.6"
                strokeLinecap="round"
              />
            </g>
            <g transform="translate(24,-268) rotate(52)">
              <path d={LEAF} fill="var(--pl-mark)" />
              <path
                d={MIDRIB}
                fill="none"
                stroke="var(--pl-cream)"
                strokeWidth="6.6"
                strokeLinecap="round"
              />
            </g>
          </g>

          {outfit !== 'none' && <OutfitLayer outfit={outfit} size={size} />}

          {done && (
            <>
              <ellipse cx={-CHEEK_X} cy={CHEEK_Y} rx="5" ry="5" fill="var(--pl-wheat)" />
              <ellipse cx={CHEEK_X} cy={CHEEK_Y} rx="5" ry="5" fill="var(--pl-wheat)" />
            </>
          )}
        </g>
      </g>
    </svg>
  )

  const motion = (
    <span
      key={pats}
      className={cn(
        'mascot-motion',
        enter && pats === 0 && 'mascot-enter',
        pats > 0 && 'mascot-pop'
      )}
    >
      <span className={cn('mascot-motion', settling && 'mascot-settle')}>
        <span className={cn('mascot-motion', working && 'mascot-thinking')}>{mark}</span>
      </span>
    </span>
  )

  if (!interactive) {
    return (
      <span aria-hidden="true" className={cn('inline-flex shrink-0 leading-none', className)}>
        {motion}
      </span>
    )
  }

  return (
    <button
      type="button"
      onClick={pat}
      aria-label={label ?? `Pantler — ${MASCOT_LABEL[state]}`}
      className={cn(
        'inline-flex shrink-0 cursor-pointer items-center justify-center rounded-lg leading-none',
        className
      )}
    >
      {motion}
    </button>
  )
}
