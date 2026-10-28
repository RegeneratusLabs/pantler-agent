import { describe, expect, it } from 'vitest'
import {
  FRAME_SANDBOX_DEFAULT,
  embedUrlFor,
  isHtml,
  isMarkdown,
  attachmentTarget,
  extensionOf,
  fileTarget,
  hostOf,
  nameOf,
  rawUrl,
  refusalFor,
  sanitizeSandbox,
  previewPlan,
  sitePlan,
  siteTarget,
  targetKey,
  targetName,
  type FileMeta
} from './preview'

function meta(overrides: Partial<FileMeta> = {}): FileMeta {
  return {
    path: '/w/order.csv',
    name: 'order.csv',
    mime: 'text/csv',
    size: 25,
    size_human: '25 B',
    kind: 'text',
    render: 'text',
    content_type: 'application/octet-stream',
    disposition: 'attachment',
    inline: false,
    ...overrides
  }
}

describe('targets', () => {
  it('names a file by its last segment, and a site by its host', () => {
    expect(nameOf('/home/you/out/bean order.csv')).toBe('bean order.csv')
    expect(nameOf('C:\\Notes\\soil.md')).toBe('soil.md')
    expect(nameOf('/a/b/')).toBe('b')
    expect(hostOf('https://www.example.com/path')).toBe('example.com')
    expect(hostOf('not a url')).toBeUndefined()
    expect(targetName({ kind: 'site', url: 'https://www.example.com/x' })).toBe('example.com')
  })

  it('gives every target a stable key', () => {
    expect(targetKey(attachmentTarget({ id: 'a1', path: '/p/x.pdf', name: 'x.pdf' }))).toBe(
      'attachment:a1'
    )
    expect(targetKey(fileTarget('/p/x.pdf'))).toBe('file:/p/x.pdf')
    expect(targetKey({ kind: 'site', url: 'https://x.dev' })).toBe('site:https://x.dev')
  })

  it('reads an extension for an icon, and never for a decision', () => {
    expect(extensionOf('report.PDF')).toBe('pdf')
    expect(extensionOf('no-extension')).toBe('')
  })

})

describe('urls', () => {

  it('encodes a path that would otherwise change the query', () => {
    const file = fileTarget('/w/a&b=c#d.csv')
    expect(rawUrl(file)).toContain('%26')
    expect(rawUrl(file)).toContain('%3D')
    expect(rawUrl(file)).toContain('%23')
  })
})

describe('previewPlan', () => {
  const url = '/api/files/raw?path=x'

  it('frames a pdf the server will inline', () => {
    const plan = previewPlan(meta({ render: 'pdf', inline: true, mime: 'application/pdf' }), url)
    expect(plan.mode).toBe('pdf')
    expect(plan.url).toBe(url)
  })

  it('paints an image the server will inline', () => {
    expect(previewPlan(meta({ render: 'image', inline: true }), url).mode).toBe('image')
  })

  it('never points an element at a file the server will not inline', () => {
    // `render` says image and `inline` says no: a TIFF. The plan must not produce an <img>.
    const plan = previewPlan(meta({ render: 'image', inline: false, mime: 'image/tiff' }), url)
    expect(plan.mode).toBe('download')
    expect(plan.reason).toContain('not a format the browser can paint')
  })

  it('reads a text file, and says when it is showing only the beginning', () => {
    const text = meta({ mime: 'text/plain', name: 'notes.txt', size: 100 })
    expect(previewPlan(text, url).mode).toBe('text')
    expect(previewPlan(text, url).note).toBeUndefined()
    const big = meta({
      mime: 'text/plain',
      name: 'notes.txt',
      size: 2 * 1024 * 1024,
      size_human: '2.0 MB'
    })
    expect(previewPlan(big, url).mode).toBe('text')
    expect(previewPlan(big, url).note).toContain('first 512 KB')
  })

  it('renders a markdown file as a document, and still says when it is truncated', () => {
    const md = meta({ mime: 'text/markdown', name: 'notes.md' })
    expect(previewPlan(md, url).mode).toBe('markdown')
    const big = previewPlan(
      meta({ mime: 'text/markdown', name: 'notes.md', size: 2 * 1024 * 1024, size_human: '2.0 MB' }),
      url
    )
    expect(big.mode).toBe('markdown')
    expect(big.note).toContain('first 512 KB')
    // The extension is the fallback for a store that called it plain text; a `.txt` is not one.
    expect(isMarkdown(meta({ mime: 'text/plain', name: 'notes.markdown' }))).toBe(true)
    expect(isMarkdown(meta({ mime: 'text/plain', name: 'notes.txt' }))).toBe(false)
    // A page is a page whatever it is named: the HTML rule is not weakened by a `.md` mime.
    expect(
      previewPlan(meta({ mime: 'text/markdown', name: 'notes.html', render: 'download' }), url).mode
    ).toBe('html')
  })

  it('plays sound and video from the route, and knows which element', () => {
    const video = previewPlan(
      meta({ render: 'media', inline: true, mime: 'video/mp4', name: 'clip.mp4' }),
      url
    )
    expect(video.mode).toBe('media')
    expect(video.element).toBe('video')
    const audio = previewPlan(
      meta({ render: 'media', inline: true, mime: 'audio/mpeg', name: 'note.mp3' }),
      url
    )
    expect(audio.element).toBe('audio')
  })

  it('opens a page rendered, with its source one click away', () => {
    const plan = previewPlan(meta({ mime: 'text/html', name: 'report.html', render: 'download' }), url)
    expect(plan.mode).toBe('html')
    expect(plan.reason).toContain('sandboxed frame')
    expect(plan.note).toContain('own origin')
    expect(plan.note).toContain('relative asset')
    expect(isHtml(meta({ mime: 'application/xhtml+xml', name: 'x' }))).toBe(true)
    expect(isHtml(meta({ mime: 'text/plain', name: 'x.html' }))).toBe(true)
    expect(isHtml(meta({ mime: 'text/plain', name: 'x.txt' }))).toBe(false)
  })

  it('draws a delimited file as a table, and does not force a non-text one', () => {
    const csv = previewPlan(meta({ mime: 'text/csv', name: 'order.csv' }), url)
    expect(csv.mode).toBe('csv')
    expect(csv.delimiter).toBe(',')

    const tsv = previewPlan(meta({ mime: 'text/plain', name: 'order.tsv' }), url)
    expect(tsv.mode).toBe('csv')
    expect(tsv.delimiter).toBe('\t')

    // A `.csv` the server did not call text is a download, not a table to fetch.
    const refused = previewPlan(meta({ mime: 'text/csv', name: 'order.csv', render: 'download' }), url)
    expect(refused.mode).toBe('download')
  })

  it('rewrites the two hosts whose watch page refuses to be framed', () => {
    expect(embedUrlFor('https://www.youtube.com/watch?v=dQw4w9WgXcQ')).toBe(
      'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
    )
    expect(embedUrlFor('https://youtu.be/dQw4w9WgXcQ?t=30')).toBe(
      'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
    )
    expect(embedUrlFor('https://vimeo.com/123456789')).toBe(
      'https://player.vimeo.com/video/123456789'
    )
  })

  it('rebuilds an embed from a validated id, and leaves anything else alone', () => {
    // A path segment that is not an eleven-character id is not an id.
    expect(embedUrlFor('https://www.youtube.com/watch?v=short')).toBe(
      'https://www.youtube.com/watch?v=short'
    )
    expect(embedUrlFor('https://example.com/watch?v=dQw4w9WgXcQ')).toBe(
      'https://example.com/watch?v=dQw4w9WgXcQ'
    )
    expect(embedUrlFor('https://vimeo.com/album/12')).toBe('https://vimeo.com/album/12')
    expect(embedUrlFor('not a url')).toBe('not a url')
  })

  it('explains every refusal rather than showing an empty frame', () => {
    expect(refusalFor(meta({ mime: 'text/html', name: 'x.html' }))).toContain('sandboxed preview')
    expect(refusalFor(meta({ mime: 'image/svg+xml', name: 'x.svg' }))).toContain('script')
    expect(
      refusalFor(
        meta({
          mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          name: 'q.docx',
          kind: 'document'
        })
      )
    ).toContain('document')
    expect(refusalFor(meta({ mime: 'application/zip', name: 'x.zip', kind: 'archive' }))).toContain(
      'archive'
    )
    expect(refusalFor(meta({ mime: 'application/octet-stream', kind: 'other' }))).toContain(
      'No inline preview'
    )
  })
})

describe('frames', () => {
  it('makes a site target only out of an http(s) address', () => {
    // The gate lives here, not in the callers: every one of these is an address some renderer
    // would otherwise have been handed (the internal security audit A19-WEB-3).
    expect(siteTarget('https://example.com/prices')).toEqual({
      kind: 'site',
      url: 'https://example.com/prices',
      label: undefined
    })
    expect(siteTarget('  http://example.com/x  ', 'Prices')?.url).toBe('http://example.com/x')
    for (const url of [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      'data:text/html,<script>x</script>',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
      '//example.com/x',
      '/api/files/raw?path=/etc/passwd',
      'example.com',
      'mailto:x@y.dev',
      'https://exa mple.com',
      ''
    ]) {
      expect(siteTarget(url), url).toBeNull()
    }
  })

  it('allows an absolute http(s) URL on another origin', () => {
    expect(sitePlan('https://example.com/x', 'http://127.0.0.1:5175').embeddable).toBe(true)
    expect(sitePlan('http://example.com', 'http://127.0.0.1:5175').embeddable).toBe(true)
  })

  it('refuses anything that is not an absolute http(s) URL', () => {
    for (const url of [
      'javascript:alert(1)',
      'data:text/html,<script>x</script>',
      'file:///etc/passwd',
      'blob:http://localhost/abc',
      '/api/files/raw?path=/etc/passwd',
      'example.com',
      '',
      'mailto:x@y.dev'
    ]) {
      expect(sitePlan(url, 'http://127.0.0.1:5175').embeddable, url).toBe(false)
    }
  })

  it('refuses its own origin, which is the one a sandbox cannot save us from', () => {
    const plan = sitePlan('http://127.0.0.1:5175/api/health', 'http://127.0.0.1:5175')
    expect(plan.embeddable).toBe(false)
    expect(plan.reason).toContain('own origin')
  })

  it('refuses a URL carrying credentials', () => {
    expect(sitePlan('https://user:pw@example.com', 'http://localhost').embeddable).toBe(false)
  })

  it('drops a token it does not know, whatever its spelling', () => {
    // The reference's lesson: the attribute is case-insensitive, so a blocklist is only as good
    // as its spelling. An allowlist cannot be spelled around.
    expect(sanitizeSandbox('ALLOW-TOP-NAVIGATION allow-scripts')).toBe('allow-scripts')
    expect(sanitizeSandbox('Allow-Same-Origin allow-Forms')).toBe('allow-same-origin allow-forms')
    expect(sanitizeSandbox('allow-scripts allow-top-navigation')).toBe('allow-scripts')
    expect(sanitizeSandbox('allow-top-navigation-by-user-activation')).toBe(FRAME_SANDBOX_DEFAULT)
    expect(sanitizeSandbox('')).toBe(FRAME_SANDBOX_DEFAULT)
    expect(sanitizeSandbox(undefined)).toBe(FRAME_SANDBOX_DEFAULT)
  })

  it('keeps the tokens it does know, once each', () => {
    expect(sanitizeSandbox('allow-forms allow-scripts allow-forms')).toBe('allow-forms allow-scripts')
  })
})
