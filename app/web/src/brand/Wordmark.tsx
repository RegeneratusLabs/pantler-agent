/**
 * The wordmark, exactly as shipped.
 *
 * The brand package is explicit that the wordmark is outlined paths, not live text: it needs no
 * font, cannot be re-typed into something else, and is set tight on purpose. So this renders the
 * two approved artwork files rather than the display font, and lets CSS choose between them by
 * theme. The height is 40px, which makes the artwork about 107px wide — above the 96px minimum.
 */

import ink from '../../../../brand/logo/pantler-wordmark-ink.svg?url'
import cream from '../../../../brand/logo/pantler-wordmark-cream.svg?url'
import { cn } from '../ui/cn'

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      role="img"
      aria-label="pantler"
      className={cn('inline-flex items-center', className)}
    >
      <img
        className="brand-wordmark brand-wordmark--ink"
        src={ink}
        alt=""
        draggable={false}
      />
      <img
        className="brand-wordmark brand-wordmark--cream"
        src={cream}
        alt=""
        draggable={false}
      />
    </span>
  )
}
