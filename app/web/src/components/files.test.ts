import { describe, expect, it } from 'vitest'
import { basenameOf, isAbsolutePath, referencesInTool } from './files'

describe('isAbsolutePath', () => {
  it('accepts a unix path and a windows drive, and nothing else', () => {
    expect(isAbsolutePath('/home/you/out/beans.csv')).toBe(true)
    expect(isAbsolutePath('C:\\Users\\josh\\notes.md')).toBe(true)
    expect(isAbsolutePath('notes.md')).toBe(false)
    expect(isAbsolutePath('https://example.com/a')).toBe(false)
    expect(isAbsolutePath('//host/share/x')).toBe(false)
    expect(isAbsolutePath('')).toBe(false)
    expect(isAbsolutePath('/' + 'x'.repeat(5000))).toBe(false)
  })

  it('names the last segment', () => {
    expect(basenameOf('/home/you/out/beans.csv')).toBe('beans.csv')
    expect(basenameOf('C:\\notes\\soil.md')).toBe('soil.md')
  })
})

describe('referencesInTool', () => {
  it('reads the path a write actually landed on, not the one it was asked for', () => {
    const result = JSON.stringify({
      success: true,
      resolved_path: '/home/you/out/beans-2026.csv',
      files_modified: ['/home/you/out/beans-2026.csv']
    })
    const found = referencesInTool('write_file', {
      argsPreview: '{"path": "beans.csv", "content": "…"}',
      args: '{"path": "beans.csv", "content": "…"}',
      result
    })
    expect(found).toHaveLength(1)
    expect(found[0]).toEqual({
      path: '/home/you/out/beans-2026.csv',
      name: 'beans-2026.csv',
      role: 'produced'
    })
  })

  it('reads a read_file result and marks it as context, not a deliverable', () => {
    const found = referencesInTool('read_file', {
      argsPreview: '{"path": "/w/soil-test.pdf"}',
      result: JSON.stringify({ path: '/w/soil-test.pdf', content: '…' })
    })
    expect(found[0].role).toBe('read')
    expect(found[0].path).toBe('/w/soil-test.pdf')
  })

  it('falls back to a bare absolute path in the argument preview', () => {
    const found = referencesInTool('read_file', { argsPreview: '/w/notes.md' })
    expect(found.map(reference => reference.path)).toEqual(['/w/notes.md'])
  })

  it('ignores a relative path, because a transcript carries no working directory', () => {
    expect(
      referencesInTool('write_file', {
        argsPreview: '{"path": "notes.md"}',
        result: JSON.stringify({ path: 'notes.md' })
      })
    ).toEqual([])
  })

  it('ignores a tool that is not on the list, whatever its result holds', () => {
    expect(
      referencesInTool('terminal', { result: JSON.stringify({ path: '/etc/hostname' }) })
    ).toEqual([])
  })

  it('ignores a URL that happens to sit in a path-shaped key', () => {
    expect(
      referencesInTool('read_file', { result: JSON.stringify({ path: 'https://x.dev/a.txt' }) })
    ).toEqual([])
  })

  it('does not walk into a nested envelope looking for something to offer', () => {
    // A nested `path` is a diagnostic, not the turn's deliverable.
    const found = referencesInTool('read_file', {
      result: JSON.stringify({ data: { path: '/w/other.pdf' }, ok: true })
    })
    expect(found).toEqual([])
  })

  it('de-duplicates and caps what it offers', () => {
    const found = referencesInTool('patch', {
      args: JSON.stringify({ path: '/w/a.ts' }),
      result: JSON.stringify({
        resolved_path: '/w/a.ts',
        files_modified: ['/w/a.ts', '/w/b.ts', '/w/c.ts', '/w/d.ts']
      })
    })
    expect(found.map(reference => reference.path)).toEqual(['/w/a.ts', '/w/b.ts', '/w/c.ts'])
  })

  it('survives a result wrapped in the engine’s untrusted preamble', () => {
    const found = referencesInTool('write_file', {
      result: '<untrusted_tool_result>\n{"resolved_path": "/w/x.csv"}\n</untrusted_tool_result>'
    })
    expect(found[0].path).toBe('/w/x.csv')
  })

  it('survives a truncated result rather than throwing', () => {
    expect(
      referencesInTool('write_file', { result: '{"resolved_path": "/w/x.cs' })
    ).toEqual([])
  })
})
