// @vitest-environment jsdom
/**
 * What a `MEDIA:` directive draws.
 *
 * The rule the component exists to keep is that **the server decides**, not the file name: an
 * image is painted only after `/api/files/meta` says `render: "image"` *and* `inline: true`, and
 * everything else — a document, a path outside the read roots, a file that has been deleted — is
 * a card. That is the same rule the preview pane follows, which is why these tests stub the
 * server's answer rather than a path: the answer is the input.
 */

import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PreviewMeta } from '@shared/wire'

/** The answer `/api/files/meta` will give, per path, for the test that is running. */
const answers = new Map<string, PreviewMeta | Error>()
const asked: string[] = []

vi.mock('../seam/bff', () => ({
  BffClient: class {
    async fileMeta(path: string): Promise<PreviewMeta> {
      asked.push(path)
      const answer = answers.get(path)
      if (answer instanceof Error) throw answer
      if (!answer) throw new Error('no such file')
      return answer
    }
  }
}))

const { AppProvider } = await import('../state/app-context')
const { PreviewHost } = await import('./preview-context')
const { MediaFigures } = await import('./MediaFigure')

const CARD = '/home/you/projects/pantler/output/instagram/markets/northey-street-sundays.png'
const CARD2 = '/home/you/projects/pantler/output/instagram/markets/pomona-saturdays.png'

const meta = (patch: Partial<PreviewMeta> = {}): PreviewMeta => ({
  path: CARD,
  name: 'northey-street-sundays.png',
  mime: 'image/png',
  size: 47_551,
  size_human: '46.4 KB',
  kind: 'image',
  render: 'image',
  content_type: 'image/png',
  disposition: 'inline',
  inline: true,
  ...patch
})

function draw(paths: readonly string[]) {
  return render(
    <AppProvider settings={{ baseUrl: '/seam', apiKey: '' }} updateSettings={() => {}}>
      <PreviewHost>
        <MediaFigures paths={paths} />
      </PreviewHost>
    </AppProvider>
  )
}

beforeEach(() => {
  answers.clear()
  asked.length = 0
})

afterEach(cleanup)

describe('MediaFigures', () => {
  it('paints an image the server said may be inline', async () => {
    answers.set(CARD, meta())
    const { container } = draw([CARD])

    await waitFor(() => expect(container.querySelector('img')).not.toBeNull())
    const image = container.querySelector('img') as HTMLImageElement

    expect(asked).toEqual([CARD])
    expect(image.getAttribute('src')).toBe(`/api/files/raw?path=${encodeURIComponent(CARD)}`)
    expect(image.getAttribute('alt')).toBe('northey-street-sundays.png')
    // A download that needs no pane, and a caption that names the file and its size.
    const download = container.querySelector('a[download]') as HTMLAnchorElement
    expect(download.getAttribute('download')).toBe('northey-street-sundays.png')
    expect(container.textContent).toContain('46.4 KB')
  })

  it('paints every image a turn handed over, in the order it named them', async () => {
    answers.set(CARD, meta())
    answers.set(CARD2, meta({ path: CARD2, name: 'pomona-saturdays.png', size_human: '41.6 KB' }))
    const { container } = draw([CARD, CARD2])

    await waitFor(() => expect(container.querySelectorAll('img')).toHaveLength(2))
    expect(container.querySelector('[data-slot="turn-media"]')).not.toBeNull()
    expect(asked).toEqual([CARD, CARD2])
  })

  it('falls back to a card for a file that is not an image', async () => {
    // `render: "text"` is the server saying "do not point an img at this".
    answers.set(CARD, meta({ render: 'text', inline: false, kind: 'text', mime: 'text/markdown' }))
    const { container } = draw([CARD])

    await waitFor(() => expect(container.textContent).toContain('northey-street-sundays.png'))
    expect(container.querySelector('img')).toBeNull()
  })

  it('falls back to a card when the server refuses the path', async () => {
    // Outside the read roots, or gone since the turn: the card is still an honest thing to draw,
    // because the file was named and the operator can be told it cannot be shown.
    answers.set(CARD, new Error('outside the directories this server may read'))
    const { container } = draw([CARD])

    await waitFor(() => expect(container.textContent).toContain('northey-street-sundays.png'))
    expect(container.querySelector('img')).toBeNull()
  })

  it('draws nothing at all for a turn that handed over nothing', () => {
    const { container } = draw([])
    expect(container.querySelector('[data-slot="turn-media"]')).toBeNull()
  })
})
