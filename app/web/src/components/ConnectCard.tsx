import { ExternalLink, PlugZap } from 'lucide-react'
import { connectOffers } from './connect'

/**
 * A connection offer, as a card with a button on it.
 *
 * The engine's connector tool answers a turn with `connect_url`s and a note addressed to the
 * *model* — *"Show each connect_url to the user; they open it in a browser to authorize"*. That
 * instruction is the whole design: the operator has to be able to click it. Left to the activity
 * line, the envelope would be one more folded JSON blob, and a login nobody can see is a login
 * that does not happen (the front-end design §4 — *"a JSON envelope in front of an operator…
 * is a rendering of the implementation rather than of the work"*).
 *
 * Three rules, and they are why this is a card and not a link in the prose:
 *
 *   - **It opens in the operator's own browser**, not a frame. The sign-in page is the provider's,
 *     with the provider's certificate in the address bar, and the engine's gateway does the
 *     handshake. Nothing here touches the URL beyond putting it on an anchor (`connect.ts` refuses
 *     any address that is not absolute `http(s)` first).
 *   - **It says what the click does before it does it** — a browser tab, the app's own sign-in,
 *     nothing shared until they approve it there.
 *   - **It never claims the connection happened.** The card is an offer; the state belongs to the
 *     engine, and the operator's next message is what checks it. A card that flipped to
 *     "Connected ✓" on click would be reporting something no one has witnessed.
 */
export function ConnectCard({
  result,
  onAsk
}: {
  result: string | undefined
  /** Send a turn as if the operator typed it — used by the one button that is not a link. */
  onAsk?: (text: string) => void
}) {
  const offers = connectOffers(result)
  if (offers.length === 0) return null

  const many = offers.length > 1

  return (
    <div className="flex flex-col gap-2.5 rounded-card border border-accent/40 bg-accent/[0.05] px-3.5 py-3">
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border border-accent/40 bg-accent/10 text-accent"
        >
          <PlugZap className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="text-sm text-ink">
            {many ? `Connect ${offers.length} apps` : `Connect ${offers[0].label}`}
          </p>
          <p className="text-xs leading-relaxed text-ink-3">
            Opens {many ? 'each app' : 'the app'} in a new tab so you can sign in there. Nothing is
            shared with the assistant until you approve it on that page.
          </p>
        </div>
      </div>

      <ul className="flex flex-wrap items-center gap-2">
        {offers.map(offer => (
          <li key={offer.url}>
            <a
              href={offer.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-8 items-center gap-2 rounded-lg bg-accent px-3 text-sm font-medium text-accent-ink transition-colors hover:brightness-110"
            >
              Connect {offer.label}
              <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-[0.68rem] text-ink-disabled">
          When you have finished, say so here and the assistant will check it.
        </p>
        {onAsk && (
          <button
            type="button"
            onClick={() => onAsk(I_FINISHED)}
            className="text-[0.68rem] text-ink-2 underline underline-offset-2 hover:text-ink"
          >
            Check now
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * What "Check now" sends, in the operator's own voice.
 *
 * It is a real turn — the engine's `status` action is the only thing that can witness a
 * connection — so it is written the way a person would say it, and it is never sent for them: the
 * click is theirs, and a background model call is not something to spend silently.
 */
export const I_FINISHED = 'I have finished connecting — check the connections now.'
